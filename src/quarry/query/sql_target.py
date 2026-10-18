"""Compile a QuerySpec to a single DuckDB SQL statement, for a connection or a relation."""

from __future__ import annotations

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
}
LINE_CONNECTION_CONFIG: Final[dict[str, str | bool | int | float | list[str]]] = {
    "threads": 1,
    "memory_limit": "256MiB",
    "max_temp_directory_size": "0B",
}


def to_sql(
    spec: QuerySpec,
    relation: str,
    *,
    columns: Sequence[str] | None = None,
    reduction_stats: bool = False,
) -> str:
    """Render `spec` as one DuckDB statement reading from the identifier `relation`.

    When `columns` is given, unknown column references raise QueryError before rendering.
    A pivot spec's sort and select are not checked: its columns come from the data.
    `first` and `last` raise QueryError: this SQL serves DuckDB relations, which have no order.
    """
    _reject_first_last(spec)
    if columns is not None:
        check_columns(spec, set(columns))
    inner = f"SELECT * FROM {quote_ident(relation)}"
    if spec.filters:
        inner += " WHERE " + " AND ".join(filter_sql(f) for f in spec.filters)
    if spec.line_reduce is not None:
        return line_sql(spec, inner, reduction_stats=reduction_stats)
    if spec.group_by is not None:
        keys = ", ".join(quote_ident(c) for c in spec.group_by)
        aggs = ", ".join(agg_sql(a) for a in spec.aggs)
        inner = f"SELECT {keys}, {aggs} FROM ({inner}) GROUP BY {keys}"
    elif spec.pivot is not None:
        inner = pivot_sql(inner, spec.pivot)
    projection = "*" if spec.select is None else ", ".join(quote_ident(c) for c in spec.select)
    outer = f"SELECT {projection} FROM ({inner})"
    if order := spec.row_order:
        # Nulls sort first in both directions, matching the polars target.
        outer += " ORDER BY " + ", ".join(
            f"{quote_ident(s.col)} {'DESC' if s.desc else 'ASC'} NULLS FIRST" for s in order
        )
    if spec.limit is not None:
        outer += f" LIMIT {spec.limit}"
    if spec.offset:
        outer += f" OFFSET {spec.offset}"
    return outer


def line_sql(
    spec: QuerySpec,
    source: str,
    *,
    reduction_stats: bool = False,
    time_ticks: str | None = None,
    value_expression: str | None = None,
    output_value: str = "v",
) -> str:
    """Select M4 representatives and every null-run endpoint within one row budget.

    Ordering is time, then value (null first). Exact duplicates are interchangeable.
    Equal-width time bins retain first, last, min and max, with earliest ties.
    Null-run endpoints consume budget before bins; insufficient budgets fail explicitly.
    """
    reduction = spec.line_reduce
    assert reduction is not None
    time, value = quote_ident(reduction.time), quote_ident(reduction.value)
    budget = reduction.max_rows
    ticks = time_ticks or (
        f"CASE WHEN typeof({time}) = 'TIMESTAMP_NS' THEN epoch_ns({time})::HUGEINT "
        f"ELSE epoch_us({time})::HUGEINT * 1000 END"
    )
    values = value_expression or value
    time_type = f"typeof((SELECT {time} FROM ({source}) LIMIT 0))"
    value_type = f"typeof((SELECT {values} FROM ({source}) LIMIT 0))"
    temporal = (
        f"WHEN {time_type} NOT IN ('DATE', 'TIMESTAMP', 'TIMESTAMP_S', "
        "'TIMESTAMP_MS', 'TIMESTAMP_NS', 'TIMESTAMP WITH TIME ZONE') "
        "THEN error('line_reduce time must be Date or Datetime') "
        if time_ticks is None
        else ""
    )
    numeric = (
        f"{value_type} IN ('TINYINT', 'SMALLINT', 'INTEGER', 'BIGINT', 'HUGEINT', "
        "'UTINYINT', 'USMALLINT', 'UINTEGER', 'UBIGINT', 'UHUGEINT', 'FLOAT', 'DOUBLE') "
        f"OR starts_with({value_type}, 'DECIMAL(')"
    )
    stats = ", n AS " + quote_ident(reduction_count_name(spec)) if reduction_stats else ""
    # The metadata branch is evaluated even with no surviving points. Its scalar typeof
    # expressions inspect schema without materializing the source a second time.
    return f"""WITH axis_contract AS MATERIALIZED (
    SELECT CASE {temporal}WHEN NOT ({numeric}) THEN
        error('line_reduce value must be numeric') ELSE 0 END AS checked
), points AS (
    SELECT {time} AS t, {ticks} AS ticks,
        CASE WHEN isfinite({values}) THEN {values} END AS v
    FROM ({source}) WHERE {time} IS NOT NULL
), ordered AS (
    SELECT *, row_number() OVER w AS i,
        v IS NULL AND (NOT lag(v IS NULL, 1, false) OVER w
            OR NOT lead(v IS NULL, 1, false) OVER w) AS gap
    FROM points WINDOW w AS (ORDER BY t, v NULLS FIRST)
), counts AS (
    SELECT count(*) AS n, count(*) FILTER (WHERE gap) AS gaps,
        min(ticks::HUGEINT) AS lo, max(ticks::HUGEINT) AS hi,
        count(v) AS finite FROM ordered
), budget AS (
    SELECT *, CASE WHEN n <= {budget} OR (finite = 0 AND gaps <= {budget}) THEN 1
        WHEN {budget} - gaps >= 4 THEN ({budget} - gaps) // 4
        ELSE error('line_reduce row budget cannot preserve gaps and four extrema; '
            || 'increase max_rows or filter the time range')
        END AS bins FROM counts
), binned AS (
    SELECT *, CASE WHEN hi = lo THEN 0
        ELSE least(bins - 1, (ticks::HUGEINT - lo) * bins // (hi - lo)) END AS bucket
    FROM ordered CROSS JOIN budget
), representatives AS (
    SELECT unnest([min(i), max(i), arg_min(i, struct_pack(val := v, idx := i)),
        arg_max(i, struct_pack(val := v, idx := -i))]) AS i
    FROM binned WHERE v IS NOT NULL GROUP BY bucket
), reduced AS (
    SELECT t, v, n, i FROM binned
    WHERE n <= {budget} OR gap OR i IN (SELECT i FROM representatives)
    UNION ALL SELECT NULL, NULL, NULL, NULL FROM axis_contract WHERE checked <> 0
)
SELECT t AS {time}, {output_value} AS {value}{stats} FROM reduced
ORDER BY reduced.i"""


def reduction_count_name(spec: QuerySpec) -> str:
    """A metadata column outside the two requested axis names."""
    assert spec.line_reduce is not None
    name = "_quarry_input_rows"
    while name.lower() in {spec.line_reduce.time.lower(), spec.line_reduce.value.lower()}:
        name += "_"
    return name


def relation_view(dataset: str) -> str:
    """The name a DuckDB relation's `query` gives `dataset` in its SQL; the executor adds a
    per-query suffix.

    Under the dataset's own name, a relation over a same-named table would read itself, and
    the view would shadow that table afterwards.
    """
    return f"_quarry_{dataset}"


def split_for_relation(spec: QuerySpec) -> tuple[QuerySpec, QuerySpec | None]:
    """`spec` as the part a relation's `query` runs as SQL, and the part, if any, left for polars.

    DuckDB plans PIVOT without an IN list as a MULTI statement, which `relation.query` cannot
    run: a pivot spec's SQL only filters and selects the pivot's inputs, and the pivot onward
    runs in polars on its result.

    `first` and `last` raise QueryError, as in `to_sql`, also as the pivot agg: that runs in
    polars, but on rows the relation returns in no order.
    """
    _reject_first_last(spec)
    if spec.pivot is None:
        return spec, None
    pre_pivot = spec.model_copy(
        update={"pivot": None, "sort": [], "limit": None, "offset": 0, "select": spec.pivot.inputs}
    )
    return pre_pivot, spec.model_copy(update={"filters": []})


def _reject_first_last(spec: QuerySpec) -> None:
    """Raise QueryError for `first` or `last`, in the aggs or as the pivot agg.

    A relation has no row order, so they would pick arbitrary rows, different ones from run to
    run.
    """
    pivot_agg = [] if spec.pivot is None else [spec.pivot.agg]
    for fn in [*(a.fn for a in spec.aggs), *pivot_agg]:
        if fn in ("first", "last"):
            message = (
                f"{fn!r} needs a row order, which a DuckDB relation does not have; "
                "use 'min' or 'max', or convert it with .pl() first"
            )
            raise QueryError(message, dataset=spec.dataset)


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
        case int() | float():
            return repr(value)
        case str():
            return "'" + value.replace("'", "''") + "'"
        case _:  # a filter's value, or each of its items, is a scalar
            raise TypeError(f"cannot render a {type(value).__name__} as a SQL literal")


def _as_list(value: Json) -> list[Json]:
    if not isinstance(value, list):
        raise TypeError("expected a list value")
    return value


def _literal_list(value: Json) -> str:
    return ", ".join(quote_literal(v) for v in _as_list(value))
