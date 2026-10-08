"""Compile a QuerySpec to a polars LazyFrame."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import polars as pl

from quarry.query.columns import check_columns, check_output_columns
from quarry.query.spec import Agg, AggFn, Filter, Json, Pivot, QuerySpec

CompareOp = Literal["eq", "ne", "lt", "le", "gt", "ge", "in", "not_in", "between"]


@dataclass(frozen=True, slots=True)
class CoercedLiteral:
    """A filter's JSON literal as plain Python values its column can be compared with."""

    value: object
    compare_as_float: bool


def to_polars(spec: QuerySpec, frame: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
    lf = frame.lazy()
    schema = lf.collect_schema()
    check_columns(spec, set(schema.names()))
    if spec.filters:
        lf = lf.filter(pl.all_horizontal([filter_expr(f, schema[f.col]) for f in spec.filters]))
    if spec.group_by is not None:
        lf = lf.group_by(spec.group_by).agg([agg_expr(a) for a in spec.aggs])
    elif spec.pivot is not None:
        lf = _pivot(lf, spec.pivot)
        # Pivot output columns come from the data, so they can only be checked now.
        check_output_columns(spec, set(lf.collect_schema().names()))
    if spec.sort:
        lf = lf.sort([s.col for s in spec.sort], descending=[s.desc for s in spec.sort])
    if spec.limit is not None or spec.offset:
        lf = lf.slice(spec.offset, spec.limit)
    if spec.select is not None:
        lf = lf.select(spec.select)
    return lf


def filter_expr(f: Filter, dtype: pl.DataType) -> pl.Expr:
    col = pl.col(f.col)
    match f.op:
        case "contains":
            return col.str.contains(str(f.value), literal=True)
        case "starts_with":
            return col.str.starts_with(str(f.value))
        case "is_null":
            return col.is_null()
        case "not_null":
            return col.is_not_null()
        case op:
            literal = coerce_literal(f.value, dtype)
            operand = col.cast(pl.Float64) if literal.compare_as_float else col
            return _compare(op, operand, literal.value)


def coerce_literal(value: Json, dtype: pl.DataType) -> CoercedLiteral:
    """Coerce a JSON literal, or each item of a list literal, to match `dtype`.

    polars 2.0 `is_in` is strictly typed, and JSON from JS drops the `.0` of whole floats.
    An integer column compared with a fractional number must be compared as Float64,
    which `compare_as_float` signals; whole floats against it simply become ints.
    """
    items = value if isinstance(value, list) else [value]
    as_float = dtype.is_integer() and any(_is_fractional(item) for item in items)
    target = pl.Float64() if as_float else dtype
    coerced = [_coerce_item(item, target) for item in items]
    return CoercedLiteral(coerced if isinstance(value, list) else coerced[0], as_float)


def _compare(op: CompareOp, col: pl.Expr, value: object) -> pl.Expr:
    match op:
        case "eq":
            return col == pl.lit(value)
        case "ne":
            return col != pl.lit(value)
        case "lt":
            return col < pl.lit(value)
        case "le":
            return col <= pl.lit(value)
        case "gt":
            return col > pl.lit(value)
        case "ge":
            return col >= pl.lit(value)
        case "in":
            return col.is_in(_as_list(value))
        case "not_in":
            return ~col.is_in(_as_list(value))
        case "between":
            lo, hi = _as_list(value)
            return col.is_between(pl.lit(lo), pl.lit(hi))


def _is_fractional(item: Json) -> bool:
    return isinstance(item, float) and not item.is_integer()


def _coerce_item(item: Json, dtype: pl.DataType) -> object:
    match item:
        case bool():
            return item
        case int() if dtype.is_float():
            return float(item)
        case float() if dtype.is_integer() and item.is_integer():
            return int(item)
        case str() if dtype == pl.Date:
            return date.fromisoformat(item)
        case str() if isinstance(dtype, pl.Datetime):
            return datetime.fromisoformat(item)
        case _:
            return item


def _as_list(value: object) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("expected a list value")
    return value


def agg_expr(a: Agg) -> pl.Expr:
    return _aggregate(a.fn, pl.col(a.col)).alias(a.name)


def _aggregate(fn: AggFn, values: pl.Expr) -> pl.Expr:
    """Aggregate with SQL semantics, shared by group_by (`pl.col`) and pivot (`pl.element`)."""
    match fn:
        case "sum":
            # SQL SUM over no non-null values is NULL; polars would return 0.
            return pl.when(values.count() > 0).then(values.sum())
        case "mean":
            return values.mean()
        case "min":
            return values.min()
        case "max":
            return values.max()
        case "count":
            return values.count()
        case "median":
            return values.median()
        case "std":
            return values.std()
        case "first":
            return values.first()
        case "last":
            return values.last()


def _pivot(lf: pl.LazyFrame, pivot: Pivot) -> pl.LazyFrame:
    wide = lf.collect().pivot(
        on=pivot.columns,
        index=pivot.index,
        values=pivot.values,
        aggregate_function=_aggregate(pivot.agg, pl.element()),
        sort_columns=True,
    )
    return wide.lazy()
