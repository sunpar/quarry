"""Render a QuerySpec as Python source a researcher can read and run.

The source assumes `pl` and the dataset variable are in scope, and imports `date`,
`datetime` or `ZoneInfo` itself only when a literal needs one. The polars rendering mirrors
`polars_target` method for method. A DuckDB relation runs `to_sql` through
`relation.query`, so the dataset is read by its Python name, on its own connection, and a
pivot spec is split as the executor splits it (`split_for_relation`): its filters run as
SQL, and the pivot onward runs as the polars chain. The source then drops the view
`relation.query` registered, through the relation again, as the executor does, in a `finally`
so a failing query releases it too.

Filter literals depend on `schema`. When it is given, they are coerced exactly as
`to_polars` coerces them against the frame's dtypes. Without it, a string that is a whole
valid ISO date renders as `date.fromisoformat`, a whole valid ISO datetime as
`datetime.fromisoformat`, any other string (even "2024-99-99") as a plain literal, and
numbers as given. polars 2.0 `is_in` is strictly typed, so without a schema `ret in [0]`
against a float column fails when run.

`sum` depends on `schema` too. When it is given, an integer column of up to 64 bits sums as
Decimal(38, 0), as in `to_polars`. Without it, the source sums plainly, so an Int64 sum can
wrap on overflow.
"""

from __future__ import annotations

import json
import keyword
import re
from collections.abc import Callable, Mapping
from datetime import date, datetime
from typing import Final
from zoneinfo import ZoneInfo

import polars as pl

from quarry.query.columns import check_columns
from quarry.query.polars_target import (
    CoercedLiteral,
    CompareOp,
    coerce_literal,
    sums_as_decimal,
)
from quarry.query.spec import (
    NULL_OPS,
    TEXT_OPS,
    Agg,
    AggFn,
    Backing,
    Filter,
    Json,
    QueryError,
    QuerySpec,
)
from quarry.query.sql_target import quote_ident, relation_view, split_for_relation, to_sql

DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")
# Matched whole (fullmatch): `$` would also accept a trailing newline.
IDENT_RE: Final = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
# The module each name a literal can need is imported from.
IMPORTED_FROM: Final[dict[str, str]] = {
    "date": "datetime",
    "datetime": "datetime",
    "ZoneInfo": "zoneinfo",
}
OPERATORS: Final[dict[str, str]] = {
    "eq": "==",
    "ne": "!=",
    "lt": "<",
    "le": "<=",
    "gt": ">",
    "ge": ">=",
}

Schema = Mapping[str, pl.DataType]


def to_source(
    spec: QuerySpec,
    backing: Backing,
    *,
    result_name: str = "result",
    schema: Schema | None = None,
    relation_projection: str | None = None,
) -> str:
    """Render `spec` as Python that assigns the polars DataFrame `to_polars` yields.

    `relation_projection`, for a DuckDB relation, is the DuckDB select list the kernel reads
    the relation through (`importable_projection`): it renames repeated columns and casts
    INTERVAL and UNION columns to VARCHAR so `.pl()` can import them. Every failure caused by
    the spec is a QueryError.
    """
    _require_identifier(spec.dataset, "dataset", spec)
    _require_identifier(result_name, "result_name", spec)
    if schema is not None:
        check_columns(spec, set(schema))
    try:
        return _render(spec, backing, result_name, schema, relation_projection)
    except (ValueError, TypeError) as exc:
        # The SQL target's literal checks raise plain errors; the caller sees one type.
        raise QueryError(str(exc), dataset=spec.dataset) from exc


def _render(
    spec: QuerySpec,
    backing: Backing,
    result_name: str,
    schema: Schema | None,
    relation_projection: str | None,
) -> str:
    if backing != "duckdb":
        chain = _chain_source(
            spec,
            result_name=result_name,
            schema=schema,
            head=f"{spec.dataset}.lazy()",
            head_is_lazy=True,
        )
        imported = _imported_names(spec, schema)
        if spec.dataset in imported:
            raise QueryError(
                f"dataset {spec.dataset!r} would be shadowed by the generated import; rename it",
                dataset=spec.dataset,
            )
        return f"{_import_lines(imported)}{chain}\n"
    if result_name == spec.dataset:
        # The view is dropped through the dataset after the result is assigned.
        raise QueryError(
            f"result_name {result_name!r} must differ from the dataset for a relation",
            dataset=spec.dataset,
        )
    sql_part, polars_part = split_for_relation(spec)
    view = relation_view(spec.dataset)
    source_rel = spec.dataset
    if relation_projection is not None:
        source_rel = f"{spec.dataset}.project({py_literal(relation_projection)})"
    head = f"{source_rel}.query({py_literal(view)}, {py_literal(to_sql(sql_part, view))}).pl()"
    if polars_part is None:
        assign = f"{result_name} = {head}"
    else:
        # No imports: the filters, the only literals, run in the SQL.
        assign = _chain_source(
            polars_part, result_name=result_name, schema=schema, head=head, head_is_lazy=False
        )
    # The view stays on the relation's connection, pinning its data, until something drops it,
    # so it is dropped even when the query fails.
    drop_sql = py_literal(f"DROP VIEW {quote_ident(view)}")
    drop = f"# release the temporary view\n{spec.dataset}.query({py_literal(view)}, {drop_sql})"
    return f"try:\n{_indent(assign)}\nfinally:\n{_indent(drop)}\n"


def imported_names(spec: QuerySpec, backing: Backing, *, schema: Schema | None = None) -> list[str]:
    """The names `to_source(spec, backing, schema=schema)` binds with its import lines."""
    # Relation source imports nothing: its filters, the only literals, run in the SQL.
    return [] if backing == "duckdb" else _imported_names(spec, schema)


def filter_source(f: Filter, dtype: pl.DataType | None = None) -> str:
    """Render one filter as a polars expression, mirroring `polars_target.filter_expr`."""
    col = f"pl.col({py_literal(f.col)})"
    match f.op:
        case "contains":
            return f"{col}.str.contains({py_literal(str(f.value))}, literal=True)"
        case "starts_with":
            return f"{col}.str.starts_with({py_literal(str(f.value))})"
        case "is_null":
            return f"{col}.is_null()"
        case "not_null":
            return f"{col}.is_not_null()"
        case op:
            literal = _literal(f.value, dtype)
            operand = f"{col}.cast(pl.Float64)" if literal.compare_as_float else col
            return _compare_source(op, operand, literal.value)


def agg_source(a: Agg, dtype: pl.DataType | None = None) -> str:
    """Render one aggregate, mirroring `polars_target.agg_expr`."""
    values = f"pl.col({py_literal(a.col)})"
    return f"{_aggregate_source(a.fn, values, dtype)}.alias({py_literal(a.name)})"


def py_literal(value: object) -> str:
    """Render `value` as a Python expression; strings get JSON's double-quoted escaping."""
    match value:
        case str():
            return "".join(map(_escape_unprintable, json.dumps(value, ensure_ascii=False)))
        case None | bool() | int() | float():
            return repr(value)
        case list():
            return "[" + ", ".join(py_literal(item) for item in value) + "]"
        case datetime(tzinfo=ZoneInfo() as zone):
            # The zone, not only the offset isoformat keeps: polars compares a zoned column only
            # with a literal in that zone.
            iso, key = py_literal(value.isoformat()), py_literal(zone.key)
            return f"datetime.fromisoformat({iso}).astimezone(ZoneInfo({key}))"
        case datetime():
            return f"datetime.fromisoformat({py_literal(value.isoformat())})"
        case date():
            return f"date.fromisoformat({py_literal(value.isoformat())})"
        case _:
            raise TypeError(f"cannot render a {type(value).__name__} as a Python literal")


def _chain_source(
    spec: QuerySpec,
    *,
    result_name: str,
    schema: Schema | None,
    head: str,
    head_is_lazy: bool,
) -> str:
    """The statement assigning the chain to `result_name`, with no import line."""
    lines = [
        head,
        *_filter_steps(spec, schema),
        *_reshape_steps(spec, schema, head_is_lazy),
        *_tail_steps(spec),
        ".collect()",
    ]
    body = _indent("\n".join(lines))
    return f"{result_name} = (\n{body}\n)"


def _indent(source: str) -> str:
    # str.splitlines (and so textwrap.indent) also breaks on U+0085, U+2028 and U+2029.
    return "\n".join(f"    {line}" for line in source.split("\n"))


def _filter_steps(spec: QuerySpec, schema: Schema | None) -> list[str]:
    if not spec.filters:
        return []
    # LazyFrame.filter combines its predicates with all_horizontal, as to_polars does.
    predicates = [_filter_predicate(spec, f, schema) for f in spec.filters]
    return [_method_call("filter", predicates)]


def _filter_predicate(spec: QuerySpec, f: Filter, schema: Schema | None) -> str:
    try:
        return filter_source(f, _dtype(schema, f.col))
    except (ValueError, TypeError, OverflowError) as exc:
        # Literal coercion names neither the column nor the value ("month must be in 1..12").
        message = f"filter on {f.col!r} cannot use {f.value!r}: {exc}"
        raise QueryError(message, dataset=spec.dataset, column=f.col) from exc


def _reshape_steps(spec: QuerySpec, schema: Schema | None, head_is_lazy: bool) -> list[str]:
    if spec.group_by is not None:
        aggs = _method_call("agg", [agg_source(a, _dtype(schema, a.col)) for a in spec.aggs])
        return [f".group_by({py_literal(spec.group_by)})", aggs]
    if spec.pivot is None:
        return []
    values_dtype = _dtype(schema, spec.pivot.values)
    pivot = _method_call(
        "pivot",
        [
            f"on={py_literal(spec.pivot.columns)}",
            f"index={py_literal(spec.pivot.index)}",
            f"values={py_literal(spec.pivot.values)}",
            f"aggregate_function={_aggregate_source(spec.pivot.agg, 'pl.element()', values_dtype)}",
            "sort_columns=True",
        ],
    )
    if not head_is_lazy:  # the relation's SQL already selected the pivot's inputs
        return [pivot, ".lazy()"]
    return [f".select({py_literal(spec.pivot.inputs)})", ".collect()", pivot, ".lazy()"]


def _tail_steps(spec: QuerySpec) -> list[str]:
    steps: list[str] = []
    if spec.sort:
        cols = py_literal([s.col for s in spec.sort])
        steps.append(f".sort({cols}, descending={py_literal([s.desc for s in spec.sort])})")
    if spec.limit is not None or spec.offset:
        steps.append(f".slice({spec.offset}, {py_literal(spec.limit)})")
    if spec.select is not None:
        steps.append(f".select({py_literal(spec.select)})")
    return steps


def _method_call(method: str, args: list[str]) -> str:
    """One argument stays on the line; several go one per line, as a formatter lays them out."""
    if len(args) == 1:
        return f".{method}({args[0]})"
    return f".{method}(" + "".join(f"\n    {arg}," for arg in args) + "\n)"


def _aggregate_source(fn: AggFn, values: str, dtype: pl.DataType | None) -> str:
    """Mirror `polars_target._aggregate`: every other AggFn is a polars method of its name."""
    if fn == "sum":
        exact = dtype is not None and sums_as_decimal(dtype)
        total = f"{values}.cast(pl.Decimal(38, 0))" if exact else values
        # SQL SUM over no non-null values is NULL; polars would return 0.
        return f"pl.when({values}.count() > 0).then({total}.sum())"
    return f"{values}.{fn}()"


def _compare_source(op: CompareOp, col: str, value: object) -> str:
    match op:
        case "in":
            return f"{col}.is_in({py_literal(value)})"
        case "not_in":
            return f"~{col}.is_in({py_literal(value)})"
        case "between":
            lo, hi = _as_pair(value)
            # is_between reads bare strings as column names, so the bounds are pl.lit.
            return f"{col}.is_between(pl.lit({py_literal(lo)}), pl.lit({py_literal(hi)}))"
        case _:
            return f"{col} {OPERATORS[op]} {py_literal(value)}"


def _literal(value: Json, dtype: pl.DataType | None) -> CoercedLiteral:
    if dtype is not None:
        return coerce_literal(value, dtype)
    return CoercedLiteral(_infer_temporal(value), compare_as_float=False)


def _infer_temporal(value: Json) -> object:
    match value:
        case list():
            return [_infer_temporal(item) for item in value]
        case str() if DATE_RE.match(value):
            parse: Callable[[str], date] = date.fromisoformat
        case str() if DATETIME_RE.match(value):
            parse = datetime.fromisoformat
        case _:
            return value
    # The patterns only check the shape; parsing checks the whole string is a real date.
    try:
        return parse(value)
    except ValueError:  # "2024-99-99", "2024-01-03T09:30 market-open"
        return value


def _imported_names(spec: QuerySpec, schema: Schema | None) -> list[str]:
    """The names the generated import lines bind, for the temporal literals the filters need."""
    literals = [
        _literal(f.value, _dtype(schema, f.col)).value
        for f in spec.filters
        if f.op not in TEXT_OPS | NULL_OPS
    ]
    return sorted({name for value in literals for name in _temporal_names(value)})


def _import_lines(names: list[str]) -> str:
    lines = [
        f"from {module} import {', '.join(n for n in names if IMPORTED_FROM[n] == module)}\n"
        for module in sorted({IMPORTED_FROM[n] for n in names})
    ]
    return "".join(lines) + "\n" if lines else ""


def _temporal_names(value: object) -> set[str]:
    match value:
        case list():
            return {name for item in value for name in _temporal_names(item)}
        case datetime(tzinfo=ZoneInfo()):
            return {"datetime", "ZoneInfo"}
        case datetime():
            return {"datetime"}
        case date():
            return {"date"}
        case _:
            return set()


def _dtype(schema: Schema | None, col: str) -> pl.DataType | None:
    return None if schema is None else schema[col]


def _as_pair(value: object) -> tuple[object, object]:
    if not (isinstance(value, list) and len(value) == 2):
        raise TypeError("expected a two-element list value")
    return value[0], value[1]


def _escape_unprintable(ch: str) -> str:
    # Raw line separators would split the literal across lines, and raw bidi controls
    # (U+202E) would make the source read differently from what it runs.
    if ch.isprintable():
        return ch
    code = ord(ch)
    return f"\\u{code:04x}" if code <= 0xFFFF else f"\\U{code:08x}"


def _require_identifier(name: str, role: str, spec: QuerySpec) -> None:
    # Both names are pasted into code that will run, so nothing else may get through.
    # Python NFKC-folds identifiers at parse time, so a name that is not ASCII could run as a
    # different name than the one checked here.
    if not IDENT_RE.fullmatch(name) or keyword.iskeyword(name):
        raise QueryError(
            f"{role} {name!r} must be a Python identifier of ASCII letters, digits and underscores",
            dataset=spec.dataset,
        )
