"""What counts as a dataset in the kernel namespace, and how to describe one."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final, TypeGuard

import duckdb
import polars as pl
from polars.datatypes import DataTypeClass
from pydantic import BaseModel, ConfigDict, Field

from quarry.query.spec import Backing, Json

PREVIEW_ROWS: Final = 20
# write_json separates a naive datetime's date and time with a space; ISO 8601 wants `T`.
# `%.f` adds fractional seconds only when they are nonzero.
_NAIVE_ISO_FORMAT: Final = "%Y-%m-%dT%H:%M:%S%.f"
_JSON_MAP_KEY_TYPES: Final = (pl.String, pl.Categorical, pl.Enum)

Dataset = pl.DataFrame | pl.LazyFrame | duckdb.DuckDBPyRelation


class Column(BaseModel):
    name: str
    dtype: str


class DatasetMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    backing: Backing
    schema_: list[Column] = Field(alias="schema")
    rows: int | None
    preview: list[dict[str, Json]]


def is_dataset(obj: object) -> TypeGuard[Dataset]:
    return isinstance(obj, pl.DataFrame | pl.LazyFrame | duckdb.DuckDBPyRelation)


def backing_of(obj: Dataset) -> Backing:
    if isinstance(obj, pl.DataFrame):
        return "polars"
    if isinstance(obj, pl.LazyFrame):
        return "polars_lazy"
    return "duckdb"


def describe(name: str, obj: Dataset, *, count_rows: bool) -> DatasetMeta:
    """Schema as polars dtype strings, a preview, and a row count when it is cheap or asked for."""
    if isinstance(obj, pl.DataFrame):
        rows: int | None = obj.height
        head = obj.head(PREVIEW_ROWS)
    elif isinstance(obj, pl.LazyFrame):
        rows = obj.select(pl.len()).collect().item() if count_rows else None
        head = obj.head(PREVIEW_ROWS).collect()
    else:
        rows = _relation_row_count(obj) if count_rows else None
        head = obj.limit(PREVIEW_ROWS).pl()
    return DatasetMeta(
        name=name,
        backing=backing_of(obj),
        schema=[Column(name=n, dtype=str(t)) for n, t in head.schema.items()],
        rows=rows,
        preview=to_json_rows(head),
    )


def dataset_names(namespace: Mapping[str, object]) -> set[str]:
    return {n for n, v in namespace.items() if not n.startswith("_") and is_dataset(v)}


def to_json_rows(df: pl.DataFrame) -> list[dict[str, Json]]:
    """Rows of JSON-native values, for every dtype, without write_json's panics or errors."""
    # pl.nth, not pl.col: a column named like a regex (`^a.*$`) or `*` would select others.
    converted = [
        expr.alias(name)
        for index, (name, dtype) in enumerate(df.schema.items())
        if (expr := _json_native(pl.nth(index), dtype)) is not None
    ]
    rows: list[dict[str, Json]] = json.loads(df.with_columns(converted).write_json())
    return rows


def _relation_row_count(rel: duckdb.DuckDBPyRelation) -> int:
    (count,) = rel.aggregate("count(*)").fetchall()[0]
    return int(count)


def _json_native(expr: pl.Expr, dtype: pl.DataType | DataTypeClass) -> pl.Expr | None:
    """`expr` converted so write_json emits JSON-native values, or None if it already does.

    polars types nested dtypes as instance or class; a frame's schema always holds instances.
    """
    match dtype:
        case pl.Decimal():
            return expr.cast(pl.Float64)
        case pl.Binary():
            return expr.bin.encode("base64")
        case pl.Datetime(time_zone=None):
            return expr.dt.to_string(_NAIVE_ISO_FORMAT)
        case pl.Object():
            return expr.map_batches(_object_strings, return_dtype=pl.String)
        case pl.List(inner=inner):
            element = _json_native(pl.element(), inner)
            return None if element is None else expr.list.eval(element)
        case pl.Array(inner=inner):
            element = _json_native(pl.element(), inner)
            return None if element is None else expr.arr.eval(element)
        case pl.Struct(fields=fields):
            changed = [
                field.alias(f.name)
                for f in fields
                if (field := _json_native(pl.field(f.name), f.dtype)) is not None
            ]
            return expr.struct.with_fields(changed) if changed else None
        case pl.Map(key=key, value=value):
            return _json_native_map(expr, key=key, value=value)
        case pl.BaseExtension():
            storage = expr.ext.storage()
            converted = _json_native(storage, dtype.ext_storage())
            return storage if converted is None else converted
    return None


def _json_native_map(
    expr: pl.Expr, *, key: pl.DataType | DataTypeClass, value: pl.DataType | DataTypeClass
) -> pl.Expr | None:
    """A JSON object when write_json can emit one, else a list of `{key, value}` entries."""
    entries = _json_native(expr.map.entries(), pl.List(pl.Struct({"key": key, "value": value})))
    if entries is not None:
        return entries
    return None if isinstance(key, _JSON_MAP_KEY_TYPES) else expr.map.entries()


def _object_strings(series: pl.Series) -> pl.Series:
    return pl.Series(series.name, [None if v is None else str(v) for v in series], dtype=pl.String)
