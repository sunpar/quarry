"""What counts as a dataset in the kernel namespace, and how to describe one."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final, TypeGuard

import duckdb
import polars as pl
from duckdb.sqltypes import DuckDBPyType
from polars.datatypes import DataTypeClass
from pydantic import BaseModel, ConfigDict, Field

from quarry.query.spec import Backing, Json
from quarry.query.sql_target import quote_ident

PREVIEW_ROWS: Final = 20
# write_json separates a naive datetime's date and time with a space; ISO 8601 wants `T`.
# `%.f` adds fractional seconds only when they are nonzero.
_NAIVE_ISO_FORMAT: Final = "%Y-%m-%dT%H:%M:%S%.f"
_JSON_MAP_KEY_TYPES: Final = (pl.String, pl.Categorical, pl.Enum)
# chrono's NaiveDate::MIN (-262143-01-01) and MAX (+262142-12-31) as days since 1970-01-01.
# write_json panics on a Date or Datetime outside them, such as DuckDB's 'infinity'.
_CHRONO_MIN_DAY: Final = -96_465_292
_CHRONO_MAX_DAY: Final = 95_026_236
_TICKS_PER_DAY: Final = {"ms": 86_400_000, "us": 86_400_000_000, "ns": 86_400_000_000_000}
_I64_MIN: Final = -(2**63)
_I64_MAX: Final = 2**63 - 1
# `.pl()` raises or panics on these DuckDB types, at any depth.
_UNIMPORTABLE_DUCKDB_TYPES: Final = frozenset({"interval", "union"})
_NESTED_DUCKDB_TYPES: Final = frozenset({"list", "array", "struct", "map"})

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
    # "<ExcType>: <message>", with schema and preview empty, when the dataset exists but could
    # not be described.
    error: str | None = None


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
        head = relation_frame(obj, PREVIEW_ROWS)
    return DatasetMeta(
        name=name,
        backing=backing_of(obj),
        schema=[Column(name=n, dtype=str(t)) for n, t in head.schema.items()],
        rows=rows,
        preview=to_json_rows(head),
    )


def undescribed(name: str, obj: Dataset, *, error: str) -> DatasetMeta:
    """Metadata for a dataset `describe` failed on: its name and backing, and why it failed."""
    return DatasetMeta(
        name=name, backing=backing_of(obj), schema=[], rows=None, preview=[], error=error
    )


def dataset_names(namespace: Mapping[str, object]) -> set[str]:
    # Step code can add a non-str key (`globals()[1] = 1`), which no step can reference.
    return {
        n
        for n, v in namespace.items()
        if isinstance(n, str) and not n.startswith("_") and is_dataset(v)
    }


def relation_frame(rel: duckdb.DuckDBPyRelation, limit: int | None = None) -> pl.DataFrame:
    """`rel` as a polars frame; INTERVAL and UNION columns, which polars cannot import, as VARCHAR.

    Columns are projected by position (`#n`), so duplicate names cannot pick the wrong column.
    """
    if any(_unimportable(t) for t in rel.types):
        columns = enumerate(zip(rel.columns, rel.types, strict=True), start=1)
        rel = rel.project(", ".join(_importable(n, name, t) for n, (name, t) in columns))
    return (rel if limit is None else rel.limit(limit)).pl()


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


def _unimportable(column_type: DuckDBPyType) -> bool:
    if column_type.id in _UNIMPORTABLE_DUCKDB_TYPES:
        return True
    return column_type.id in _NESTED_DUCKDB_TYPES and any(
        isinstance(child, DuckDBPyType) and _unimportable(child)
        for _, child in column_type.children
    )


def _importable(position: int, name: str, column_type: DuckDBPyType) -> str:
    source = f"#{position}"
    if _unimportable(column_type):
        source = f"CAST({source} AS VARCHAR)"
    return f"{source} AS {quote_ident(name)}"


def _json_native(expr: pl.Expr, dtype: pl.DataType | DataTypeClass) -> pl.Expr | None:
    """`expr` converted so write_json emits JSON-native values, or None if it already does.

    polars types nested dtypes as instance or class; a frame's schema always holds instances.
    """
    match dtype:
        case pl.Decimal():
            return expr.cast(pl.Float64)
        case pl.Binary():
            return expr.bin.encode("base64")
        case pl.Date():
            return _representable(expr, ticks_per_day=1)
        case pl.Datetime(time_unit=unit, time_zone=None):
            in_range = _representable(expr, ticks_per_day=_TICKS_PER_DAY[unit])
            return in_range.dt.to_string(_NAIVE_ISO_FORMAT)
        case pl.Datetime(time_unit=unit):
            return _representable(expr, ticks_per_day=_TICKS_PER_DAY[unit])
        case pl.Duration():
            # write_json panics on i64::MIN milliseconds.
            return pl.when(expr.to_physical() != _I64_MIN).then(expr)
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


def _representable(expr: pl.Expr, *, ticks_per_day: int) -> pl.Expr:
    """`expr`, with null where chrono cannot represent the value.

    The guard wraps the input, not the converted output: when/then evaluates both branches.
    """
    low = max(_CHRONO_MIN_DAY * ticks_per_day, _I64_MIN)
    high = min((_CHRONO_MAX_DAY + 1) * ticks_per_day - 1, _I64_MAX)
    return pl.when(expr.to_physical().is_between(low, high)).then(expr)


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
