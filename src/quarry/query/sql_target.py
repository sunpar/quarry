"""Compile a QuerySpec to a single DuckDB SQL statement, for a connection or a relation."""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Final

from quarry.query.columns import check_columns
from quarry.query.spec import Agg, AggFn, Filter, Json, Pivot, QueryError, QuerySpec

SQL_AGG: Final[dict[AggFn, str]] = {
    "sum": "sum",
    "mean": "avg",
    "min": "min",
    "max": "max",
    "count": "count",
    "median": "median",
    "std": "stddev_samp",
    "first": "first",
    "last": "last",
}


def to_sql(spec: QuerySpec, relation: str, *, columns: Sequence[str] | None = None) -> str:
    """Render `spec` as one DuckDB statement reading from the identifier `relation`.

    When `columns` is given, unknown column references raise QueryError before rendering.
    A pivot spec's sort and select are not checked: its columns come from the data.
    """
    if columns is not None:
        check_columns(spec, set(columns))
    inner = f"SELECT * FROM {quote_ident(relation)}"
    if spec.filters:
        inner += " WHERE " + " AND ".join(filter_sql(f) for f in spec.filters)
    if spec.group_by is not None:
        keys = ", ".join(quote_ident(c) for c in spec.group_by)
        aggs = ", ".join(agg_sql(a) for a in spec.aggs)
        inner = f"SELECT {keys}, {aggs} FROM ({inner}) GROUP BY {keys}"
    elif spec.pivot is not None:
        inner = pivot_sql(inner, spec.pivot)
    projection = "*" if spec.select is None else ", ".join(quote_ident(c) for c in spec.select)
    outer = f"SELECT {projection} FROM ({inner})"
    if spec.sort:
        # Nulls sort first in both directions, matching the polars target.
        outer += " ORDER BY " + ", ".join(
            f"{quote_ident(s.col)} {'DESC' if s.desc else 'ASC'} NULLS FIRST" for s in spec.sort
        )
    if spec.limit is not None:
        outer += f" LIMIT {spec.limit}"
    if spec.offset:
        outer += f" OFFSET {spec.offset}"
    return outer


def relation_view(dataset: str) -> str:
    """The name a DuckDB relation's `query` gives `dataset` in its SQL.

    Under the dataset's own name, a relation over a same-named table would read itself, and
    the view would shadow that table afterwards.
    """
    return f"_quarry_{dataset}"


def split_for_relation(spec: QuerySpec) -> tuple[QuerySpec, QuerySpec | None]:
    """`spec` as the part a relation's `query` runs as SQL, and the part, if any, left for polars.

    DuckDB plans PIVOT without an IN list as a MULTI statement, which `relation.query` cannot
    run: a pivot spec's SQL only filters and selects the pivot's inputs, and the pivot onward
    runs in polars on its result.

    `first` and `last` raise QueryError: a relation has no row order, so they would pick
    arbitrary rows, different ones from run to run.
    """
    pivot_agg = [] if spec.pivot is None else [spec.pivot.agg]
    for fn in [*(a.fn for a in spec.aggs), *pivot_agg]:
        if fn in ("first", "last"):
            message = (
                f"{fn!r} needs a row order, which a DuckDB relation does not have; "
                "use 'min' or 'max', or convert it with .pl() first"
            )
            raise QueryError(message, dataset=spec.dataset)
    if spec.pivot is None:
        return spec, None
    pre_pivot = spec.model_copy(
        update={"pivot": None, "sort": [], "limit": None, "offset": 0, "select": spec.pivot.inputs}
    )
    return pre_pivot, spec.model_copy(update={"filters": []})


def filter_sql(f: Filter) -> str:
    col = quote_ident(f.col)
    match f.op:
        case "eq":
            return f"{col} = {quote_literal(f.value)}"
        case "ne":
            return f"{col} <> {quote_literal(f.value)}"
        case "lt":
            return f"{col} < {quote_literal(f.value)}"
        case "le":
            return f"{col} <= {quote_literal(f.value)}"
        case "gt":
            return f"{col} > {quote_literal(f.value)}"
        case "ge":
            return f"{col} >= {quote_literal(f.value)}"
        case "in":
            return f"{col} IN ({_literal_list(f.value)})"
        case "not_in":
            return f"{col} NOT IN ({_literal_list(f.value)})"
        case "between":
            lo, hi = _as_list(f.value)
            return f"{col} BETWEEN {quote_literal(lo)} AND {quote_literal(hi)}"
        case "contains":
            return f"contains({col}, {quote_literal(str(f.value))})"
        case "starts_with":
            return f"starts_with({col}, {quote_literal(str(f.value))})"
        case "is_null":
            return f"{col} IS NULL"
        case "not_null":
            return f"{col} IS NOT NULL"


def agg_sql(a: Agg) -> str:
    return f"{SQL_AGG[a.fn]}({quote_ident(a.col)}) AS {quote_ident(a.name)}"


def pivot_sql(source: str, pivot: Pivot) -> str:
    index = ", ".join(quote_ident(c) for c in pivot.index)
    using = f"{SQL_AGG[pivot.agg]}({quote_ident(pivot.values)})"
    return f"PIVOT ({source}) ON {quote_ident(pivot.columns)} USING {using} GROUP BY {index}"


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: Json) -> str:
    match value:
        case None:
            return "NULL"
        case bool():
            return "TRUE" if value else "FALSE"
        case float() if not math.isfinite(value):
            # A bare inf or nan would parse as a column reference.
            return f"'{value!r}'::DOUBLE"
        case int() | float():
            return repr(value)
        case str():
            return "'" + value.replace("'", "''") + "'"
        case list():
            return "[" + ", ".join(quote_literal(v) for v in value) + "]"
        case dict():
            raise TypeError("dict literals are not supported in filters")


def _as_list(value: Json) -> list[Json]:
    if not isinstance(value, list):
        raise TypeError("expected a list value")
    return value


def _literal_list(value: Json) -> str:
    return ", ".join(quote_literal(v) for v in _as_list(value))
