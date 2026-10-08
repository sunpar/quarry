"""Compile a QuerySpec to a polars LazyFrame."""

from __future__ import annotations

from datetime import date, datetime

import polars as pl

from quarry.query.spec import Agg, AggFn, Filter, Json, Pivot, QueryError, QuerySpec


def to_polars(spec: QuerySpec, frame: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
    lf = frame.lazy()
    schema = lf.collect_schema()
    _check_columns(spec, set(schema.names()))
    if spec.filters:
        lf = lf.filter(pl.all_horizontal([filter_expr(f, schema[f.col]) for f in spec.filters]))
    if spec.group_by is not None:
        lf = lf.group_by(spec.group_by).agg([agg_expr(a) for a in spec.aggs])
    elif spec.pivot is not None:
        lf = _pivot(lf, spec.pivot)
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
        case "eq":
            return col == _lit(f.value, dtype)
        case "ne":
            return col != _lit(f.value, dtype)
        case "lt":
            return col < _lit(f.value, dtype)
        case "le":
            return col <= _lit(f.value, dtype)
        case "gt":
            return col > _lit(f.value, dtype)
        case "ge":
            return col >= _lit(f.value, dtype)
        case "in":
            return col.is_in(_py_list(f.value, dtype))
        case "not_in":
            return ~col.is_in(_py_list(f.value, dtype))
        case "between":
            lo, hi = _py_list(f.value, dtype)
            return col.is_between(pl.lit(lo), pl.lit(hi))
        case "contains":
            return col.str.contains(str(f.value), literal=True)
        case "starts_with":
            return col.str.starts_with(str(f.value))
        case "is_null":
            return col.is_null()
        case "not_null":
            return col.is_not_null()


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
    )
    return wide.lazy()


def _lit(value: Json, dtype: pl.DataType) -> pl.Expr:
    return pl.lit(_py(value, dtype))


def _py(value: Json, dtype: pl.DataType) -> object:
    """Convert a JSON literal to the Python value polars should compare against."""
    if isinstance(value, str):
        if dtype == pl.Date:
            return date.fromisoformat(value)
        if isinstance(dtype, pl.Datetime):
            return datetime.fromisoformat(value)
    return value


def _py_list(value: Json, dtype: pl.DataType) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("expected a list value")
    return [_py(item, dtype) for item in value]


def _check_columns(spec: QuerySpec, names: set[str]) -> None:
    referenced: list[str] = [f.col for f in spec.filters]
    if spec.group_by is not None:
        referenced += spec.group_by
        referenced += [a.col for a in spec.aggs]
    if spec.pivot is not None:
        referenced += [*spec.pivot.index, spec.pivot.columns, spec.pivot.values]
    for name in referenced:
        if name not in names:
            raise QueryError(name, spec.dataset)
    # sort and select run after aggregation, so they see only the columns it produced.
    produced = names if spec.group_by is None else {*spec.group_by, *(a.name for a in spec.aggs)}
    if spec.pivot is None:
        for s in spec.sort:
            if s.col not in produced:
                raise QueryError(s.col, spec.dataset)
        for name in spec.select or []:
            if name not in produced:
                raise QueryError(name, spec.dataset)
