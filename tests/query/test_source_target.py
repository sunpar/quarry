"""Generated source must read clearly and produce exactly the polars target's frame."""

import ast
import math
from datetime import date, datetime

import duckdb
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quarry.query import (
    Backing,
    Filter,
    Json,
    Pivot,
    QueryError,
    QuerySpec,
    Sort,
    to_polars,
    to_source,
)
from quarry.query.source_target import py_literal
from tests.query.fixtures import SPECS, trades

BACKINGS: list[Backing] = ["polars", "polars_lazy", "duckdb"]

# Cases the fixture SPECS do not reach: a fractional literal against an integer column,
# string bounds (is_between reads bare strings as column names), ISO-string date bounds,
# and a filtered pivot with a slice and a select, which a relation runs split.
EXTRA_SPECS: list[QuerySpec] = [
    QuerySpec(dataset="trades", filters=[Filter(col="volume", op="lt", value=300.5)]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="between", value=["A", "B"])]),
    QuerySpec(
        dataset="trades",
        filters=[Filter(col="date", op="between", value=["2024-01-03", "2024-01-04"])],
    ),
    QuerySpec(
        dataset="trades",
        filters=[Filter(col="volume", op="gt", value=150)],
        pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="sum"),
        sort=[Sort(col="date", desc=True)],
        limit=2,
        offset=1,
        select=["date", "MSFT"],
    ),
]


def run_source(source: str, backing: Backing) -> pl.DataFrame:
    # No `duckdb` in scope: generated code reaches DuckDB only through the relation.
    namespace: dict[str, object] = {"pl": pl}
    frame = trades()
    if backing == "duckdb":
        duckdb.register("trades_src", frame)
        namespace["trades"] = duckdb.sql("SELECT * FROM trades_src")
    elif backing == "polars_lazy":
        namespace["trades"] = frame.lazy()
    else:
        namespace["trades"] = frame
    exec(source, namespace)  # the test executes generated code on purpose
    result = namespace["result"]
    assert isinstance(result, pl.DataFrame)
    return result


def assert_matches_polars_target(spec: QuerySpec, backing: Backing) -> None:
    frame = trades()
    expected = to_polars(spec, frame).collect()
    actual = run_source(to_source(spec, backing, schema=frame.schema), backing)
    expected = expected.select(sorted(expected.columns)).sort(sorted(expected.columns))
    actual = actual.select(sorted(actual.columns)).sort(sorted(actual.columns))
    assert_frame_equal(expected, actual, check_dtypes=False, rel_tol=1e-9)


def test_polars_source_is_readable() -> None:
    src = to_source(
        QuerySpec.model_validate(
            {
                "dataset": "trades",
                "filters": [{"col": "ticker", "op": "eq", "value": "AAPL"}],
                "sort": [{"col": "volume", "desc": True}],
                "limit": 2,
            }
        ),
        "polars",
    )
    assert 'pl.col("ticker") == "AAPL"' in src
    assert '.sort(["volume"], descending=[True])' in src
    assert ".slice(0, 2)" in src
    assert src.strip().startswith("result = (")
    assert src.strip().endswith(".collect()\n)")


def test_date_literal_imports_date() -> None:
    src = to_source(
        QuerySpec.model_validate(
            {"dataset": "trades", "filters": [{"col": "date", "op": "ge", "value": "2024-01-03"}]}
        ),
        "polars",
    )
    assert "from datetime import date" in src
    assert 'date.fromisoformat("2024-01-03")' in src


def test_datetime_literal_imports_datetime() -> None:
    spec = QuerySpec(
        dataset="events", filters=[Filter(col="ts", op="lt", value="2024-01-03T09:30:00")]
    )
    src = to_source(spec, "polars")
    assert src.startswith("from datetime import datetime\n\n")
    assert 'datetime.fromisoformat("2024-01-03T09:30:00")' in src


def test_duckdb_source_uses_sql() -> None:
    src = to_source(QuerySpec(dataset="trades", limit=1), "duckdb")
    assert 'trades.query("trades", ' in src
    assert ".pl()" in src
    assert src.count("\n") == 1


def test_duckdb_pivot_runs_filters_in_sql_and_the_pivot_in_polars() -> None:
    spec = QuerySpec(
        dataset="trades",
        filters=[Filter(col="volume", op="gt", value=150)],
        pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="sum"),
        sort=[Sort(col="date")],
    )
    lines = to_source(spec, "duckdb").splitlines()
    assert lines[0] == "result = ("
    assert lines[1].startswith('    trades.query("trades", ')
    assert lines[1].endswith(".pl()")
    assert "WHERE" in lines[1]
    assert "    .pivot(" in lines
    assert "        sort_columns=True," in lines
    assert not any("PIVOT" in line or ".filter(" in line for line in lines)
    assert lines[-2:] == ["    .collect()", ")"]


def test_schema_coerces_integral_list_items_to_a_float_column() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="ret", op="in", value=[0])])
    src = to_source(spec, "polars", schema=trades().schema)
    assert 'pl.col("ret").is_in([0.0])' in src


def test_schema_compares_an_integer_column_with_a_fraction_as_float() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="volume", op="lt", value=300.5)])
    src = to_source(spec, "polars", schema=trades().schema)
    assert 'pl.col("volume").cast(pl.Float64) < 300.5' in src


def test_unknown_column_raises_when_schema_given() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="nope", op="eq", value=1)])
    with pytest.raises(QueryError) as info:
        to_source(spec, "polars", schema=trades().schema)
    assert info.value.column == "nope"


@pytest.mark.parametrize(
    ("dataset", "result_name"),
    [("trades; import os", "result"), ("class", "result"), ("trades", "x = 1; y")],
)
def test_names_must_be_python_identifiers(dataset: str, result_name: str) -> None:
    with pytest.raises(ValueError, match="is not a Python identifier"):
        to_source(QuerySpec(dataset=dataset), "polars", result_name=result_name)


@pytest.mark.parametrize(
    "value",
    ['say "hi"', "back\\slash", "new\nline", "café", "nul\x00", 0, -3, 2.5, True, None],
)
def test_py_literal_round_trips(value: Json) -> None:
    assert ast.literal_eval(py_literal(value)) == value
    assert ast.literal_eval(py_literal([value, [value]])) == [value, [value]]


def test_py_literal_uses_double_quotes() -> None:
    assert py_literal("AAPL") == '"AAPL"'
    assert py_literal(["note col", 'q"uote']) == '["note col", "q\\"uote"]'


@pytest.mark.parametrize("value", [math.inf, -math.inf, math.nan])
def test_py_literal_non_finite_float_is_runnable(value: float) -> None:
    rendered = py_literal(value)
    assert rendered == f'float("{value!r}")'
    assert repr(eval(rendered)) == repr(value)  # the test evaluates generated code on purpose


def test_py_literal_renders_dates_by_iso_string() -> None:
    assert py_literal(date(2024, 1, 3)) == 'date.fromisoformat("2024-01-03")'
    assert py_literal(datetime(2024, 1, 3, 9, 30)) == (
        'datetime.fromisoformat("2024-01-03T09:30:00")'
    )


def test_py_literal_rejects_objects() -> None:
    with pytest.raises(TypeError):
        py_literal({"a": 1})


@pytest.mark.parametrize("backing", BACKINGS)
@pytest.mark.parametrize("spec", SPECS, ids=[s.model_dump_json() for s in SPECS])
def test_source_matches_polars_target(spec: QuerySpec, backing: Backing) -> None:
    assert_matches_polars_target(spec, backing)


@pytest.mark.parametrize("backing", BACKINGS)
@pytest.mark.parametrize("spec", EXTRA_SPECS, ids=[s.model_dump_json() for s in EXTRA_SPECS])
def test_source_matches_polars_target_beyond_fixtures(spec: QuerySpec, backing: Backing) -> None:
    assert_matches_polars_target(spec, backing)
