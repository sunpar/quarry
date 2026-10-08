"""Generated source must read clearly and produce exactly the polars target's frame."""

import ast
from datetime import date, datetime

import duckdb
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quarry.query import (
    Agg,
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
from quarry.query.sql_target import relation_view
from tests.query.fixtures import (
    INT_SUM_IDS,
    INT_SUM_SPECS,
    NAIVE_OFFSET_FILTERS,
    NAIVE_OFFSET_IDS,
    NAIVE_UNITS,
    SPECS,
    ZONED_FILTERS,
    ZONED_IDS,
    TimeUnit,
    naive_rows,
    new_york_rows,
    overflowing,
    past_decimal_38,
    trades,
    utc_connection,
)

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

# Order-dependent aggregates: a DuckDB relation has no row order to take them in.
FIRST_LAST_SPECS: list[QuerySpec] = [
    QuerySpec(dataset="trades", group_by=["ticker"], aggs=[Agg(col="ret", fn="first")]),
    QuerySpec(
        dataset="trades",
        pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="last"),
    ),
]
FIRST_LAST_IDS = ["first", "pivot_last"]
# How relation source ends: it drops the view `relation.query` registered, even on failure.
DROP_LINES = [
    "finally:",
    "    # release the temporary view",
    '    trades.query("_quarry_trades", "DROP VIEW \\"_quarry_trades\\"")',
]


def bind(frame: pl.DataFrame, backing: Backing) -> object:
    if backing == "duckdb":
        con = utc_connection()
        con.register("frame_src", frame)
        return con.sql("SELECT * FROM frame_src")
    if backing == "polars_lazy":
        return frame.lazy()
    return frame


def execute(source: str, datasets: dict[str, object]) -> pl.DataFrame:
    # No `duckdb` in scope: generated code reaches DuckDB only through the relation.
    namespace: dict[str, object] = {"pl": pl, **datasets}
    exec(source, namespace)  # the test executes generated code on purpose
    result = namespace["result"]
    assert isinstance(result, pl.DataFrame)
    return result


def assert_same_rows(expected: pl.DataFrame, actual: pl.DataFrame) -> None:
    expected = expected.select(sorted(expected.columns)).sort(sorted(expected.columns))
    actual = actual.select(sorted(actual.columns)).sort(sorted(actual.columns))
    assert_frame_equal(expected, actual, check_dtypes=False, rel_tol=1e-9)


def assert_matches_polars_target(spec: QuerySpec, backing: Backing) -> None:
    frame = trades()
    source = to_source(spec, backing, schema=frame.schema)
    actual = execute(source, {"trades": bind(frame, backing)})
    assert_same_rows(to_polars(spec, frame).collect(), actual)


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


@pytest.mark.parametrize(
    "value", ["2024-99-99", "2024-01-03T09:30 market-open"], ids=["bad_date", "datetime_prefix"]
)
def test_iso_shaped_string_that_is_not_a_valid_temporal_stays_a_string(value: str) -> None:
    spec = QuerySpec(dataset="events", filters=[Filter(col="tag", op="eq", value=value)])
    src = to_source(spec, "polars")
    assert "from datetime" not in src
    assert f'pl.col("tag") == {py_literal(value)}' in src


@pytest.mark.parametrize(
    ("value", "rendered"),
    [
        ("2024-01-03", 'date.fromisoformat("2024-01-03")'),
        ("2024-01-03 09:30", 'datetime.fromisoformat("2024-01-03T09:30:00")'),
        ("2024-01-03T09:30:00+00:00", 'datetime.fromisoformat("2024-01-03T09:30:00+00:00")'),
    ],
)
def test_valid_iso_strings_render_as_temporal_literals(value: str, rendered: str) -> None:
    spec = QuerySpec(dataset="events", filters=[Filter(col="ts", op="ge", value=value)])
    assert f'pl.col("ts") >= {rendered}' in to_source(spec, "polars")


def test_duckdb_source_uses_sql() -> None:
    lines = to_source(QuerySpec(dataset="trades", limit=1), "duckdb").splitlines()
    assert lines[0] == "try:"
    assert lines[1].startswith('    result = trades.query("_quarry_trades", ')
    assert lines[1].endswith(".pl()")
    assert lines[2:] == DROP_LINES


def test_duckdb_source_runs_over_a_table_of_the_same_name() -> None:
    frame = trades()
    con = utc_connection()
    con.register("fixture", frame)
    con.execute("CREATE TABLE trades AS SELECT * FROM fixture")
    relation = con.table("trades")
    specs = [
        QuerySpec(dataset="trades", filters=[Filter(col="volume", op="gt", value=250)]),
        QuerySpec(
            dataset="trades",
            pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="sum"),
            sort=[Sort(col="date")],
        ),
    ]
    for spec in specs:
        actual = execute(to_source(spec, "duckdb"), {"trades": relation})
        assert_same_rows(to_polars(spec, frame).collect(), actual)
    # The query's view must not shadow the researcher's table.
    assert con.sql("SELECT count(*) FROM trades").fetchone() == (5,)


def trades_view(con: duckdb.DuckDBPyConnection) -> list[tuple[str]]:
    """The view a query on `trades` registers, if it is still on `con`."""
    views = "SELECT view_name FROM duckdb_views() WHERE view_name = ?"
    return con.execute(views, [relation_view("trades")]).fetchall()


@pytest.mark.parametrize(
    "spec",
    [
        QuerySpec(dataset="trades", filters=[Filter(col="volume", op="gt", value=250)]),
        QuerySpec(
            dataset="trades",
            pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="sum"),
        ),
    ],
    ids=["plain", "pivot"],
)
def test_duckdb_source_drops_its_view(spec: QuerySpec) -> None:
    con = utc_connection()
    con.register("fixture", trades())
    execute(to_source(spec, "duckdb"), {"trades": con.sql("SELECT * FROM fixture")})
    assert trades_view(con) == []


@pytest.mark.parametrize("pivoted", [False, True], ids=["plain", "pivot"])
def test_failing_duckdb_source_raises_and_still_drops_its_view(pivoted: bool) -> None:
    con = utc_connection()
    con.register("fixture", trades())
    spec = QuerySpec(
        dataset="trades",
        filters=[Filter(col="volume", op="eq", value="two")],  # fails as the SQL runs
        pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="sum")
        if pivoted
        else None,
    )
    with pytest.raises(duckdb.ConversionException, match="two"):
        execute(to_source(spec, "duckdb"), {"trades": con.sql("SELECT * FROM fixture")})
    assert trades_view(con) == []


def test_duckdb_pivot_runs_filters_in_sql_and_the_pivot_in_polars() -> None:
    spec = QuerySpec(
        dataset="trades",
        filters=[Filter(col="volume", op="gt", value=150)],
        pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="sum"),
        sort=[Sort(col="date")],
    )
    lines = to_source(spec, "duckdb").splitlines()
    assert lines[:2] == ["try:", "    result = ("]
    assert lines[2].startswith('        trades.query("_quarry_trades", ')
    assert lines[2].endswith(".pl()")
    assert "WHERE" in lines[2]
    assert "        .pivot(" in lines
    assert "            sort_columns=True," in lines
    assert not any("PIVOT" in line or ".filter(" in line for line in lines)
    assert lines[-5:] == ["        .collect()", "    )", *DROP_LINES]


@pytest.mark.parametrize("spec", FIRST_LAST_SPECS, ids=FIRST_LAST_IDS)
def test_duckdb_source_rejects_first_and_last(spec: QuerySpec) -> None:
    with pytest.raises(QueryError, match="needs a row order"):
        to_source(spec, "duckdb")


@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize("spec", FIRST_LAST_SPECS, ids=FIRST_LAST_IDS)
def test_polars_source_runs_first_and_last(spec: QuerySpec, backing: Backing) -> None:
    assert_matches_polars_target(spec, backing)


@pytest.mark.parametrize("backing", BACKINGS)
def test_pivot_collects_only_its_input_columns(backing: Backing) -> None:
    spec = QuerySpec(
        dataset="trades",
        pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="sum"),
    )
    lines = to_source(spec, backing).splitlines()
    if backing == "duckdb":
        assert 'SELECT \\"date\\", \\"ticker\\", \\"volume\\" FROM' in lines[2]
    else:
        collect = lines.index("    .collect()")
        assert lines[collect - 1] == '    .select(["date", "ticker", "volume"])'


@pytest.mark.parametrize("backing", BACKINGS)
@pytest.mark.parametrize("pivoted", [False, True], ids=["filter", "pivot"])
@pytest.mark.parametrize("ch", ["\u2028", "\x85"], ids=["U+2028", "U+0085"])
def test_line_break_characters_stay_inside_literals(
    ch: str, pivoted: bool, backing: Backing
) -> None:
    note = f"note{ch}"
    frame = pl.DataFrame({note: [f"a{ch}b", "a b", "c"], "kind": ["x", "y", "x"], "v": [1, 2, 3]})
    spec = QuerySpec(
        dataset="notes",
        filters=[Filter(col=note, op="eq", value=f"a{ch}b")],
        pivot=Pivot(index=[note], columns="kind", values="v", agg="sum") if pivoted else None,
    )
    expected = to_polars(spec, frame).collect()
    actual = execute(to_source(spec, backing, schema=frame.schema), {"notes": bind(frame, backing)})
    assert expected.height == 1
    assert_same_rows(expected, actual)


def test_schema_coerces_integral_list_items_to_a_float_column() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="ret", op="in", value=[0])])
    src = to_source(spec, "polars", schema=trades().schema)
    assert 'pl.col("ret").is_in([0.0])' in src


def test_schema_compares_an_integer_column_with_a_fraction_as_float() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="volume", op="lt", value=300.5)])
    src = to_source(spec, "polars", schema=trades().schema)
    assert 'pl.col("volume").cast(pl.Float64) < 300.5' in src


# Not duckdb: a relation's filters run in its SQL, which test_equivalence checks.
@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize(("filter_", "selected"), ZONED_FILTERS, ids=ZONED_IDS)
def test_schema_reads_iso_strings_against_a_zoned_column_as_duckdb_does(
    filter_: Filter, selected: list[int], backing: Backing
) -> None:
    spec = QuerySpec(dataset="t", filters=[filter_], select=["n"], sort=[Sort(col="n")])
    frame = new_york_rows()
    out = execute(to_source(spec, backing, schema=frame.schema), {"t": bind(frame, backing)})
    assert out["n"].to_list() == selected


# Not duckdb: a relation's filters run in its SQL, which test_equivalence checks.
@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize("unit", NAIVE_UNITS)
@pytest.mark.parametrize(("filter_", "selected"), NAIVE_OFFSET_FILTERS, ids=NAIVE_OFFSET_IDS)
def test_schema_reads_offset_strings_against_a_naive_column_as_duckdb_does(
    filter_: Filter, selected: dict[TimeUnit, list[int]], unit: TimeUnit, backing: Backing
) -> None:
    spec = QuerySpec(dataset="t", filters=[filter_], select=["n"], sort=[Sort(col="n")])
    frame = naive_rows(unit)
    out = execute(to_source(spec, backing, schema=frame.schema), {"t": bind(frame, backing)})
    assert out["n"].to_list() == selected[unit]


def test_schema_renders_an_offset_string_against_a_naive_column_by_its_unit() -> None:
    spec = QuerySpec(
        dataset="t", filters=[Filter(col="ts", op="ge", value="2024-01-03T09:30:00+02:00")]
    )
    wall_clock = to_source(spec, "polars", schema=naive_rows("us").schema)
    assert 'pl.col("ts") >= datetime.fromisoformat("2024-01-03T09:30:00")' in wall_clock
    utc = to_source(spec, "polars", schema=naive_rows("ns").schema)
    assert 'pl.col("ts") >= datetime.fromisoformat("2024-01-03T07:30:00")' in utc


def test_schema_renders_a_naive_string_against_a_zoned_column_in_its_zone() -> None:
    spec = QuerySpec(dataset="t", filters=[Filter(col="ts", op="ge", value="2024-01-01T02:00")])
    src = to_source(spec, "polars", schema=new_york_rows().schema)
    assert src.startswith("from datetime import datetime\nfrom zoneinfo import ZoneInfo\n\n")
    assert (
        'pl.col("ts") >= datetime.fromisoformat("2023-12-31T21:00:00-05:00")'
        '.astimezone(ZoneInfo("America/New_York"))'
    ) in src


@pytest.mark.parametrize("backing", BACKINGS)
@pytest.mark.parametrize("spec", INT_SUM_SPECS, ids=INT_SUM_IDS)
def test_schema_sums_integers_without_overflow(spec: QuerySpec, backing: Backing) -> None:
    frame = overflowing()
    out = execute(to_source(spec, backing, schema=frame.schema), {"nums": bind(frame, backing)})
    assert out.dtypes[1] == pl.Decimal(38, 0)
    assert out.rows() == [("a", 2**63), ("b", None)]  # Decimal equals int exactly


@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize("dtype", [pl.Int128(), pl.UInt128()], ids=str)
@pytest.mark.parametrize("spec", INT_SUM_SPECS, ids=INT_SUM_IDS)
def test_schema_sums_128_bit_integers_natively(
    spec: QuerySpec, dtype: pl.DataType, backing: Backing
) -> None:
    frame = past_decimal_38(dtype)
    out = execute(to_source(spec, backing, schema=frame.schema), {"nums": bind(frame, backing)})
    assert out.dtypes[1] == dtype
    assert out.rows() == [("a", 10**38), ("b", None)]


def test_integer_sum_casts_only_with_a_schema() -> None:
    spec = INT_SUM_SPECS[0]
    plain = 'pl.when(pl.col("n").count() > 0).then(pl.col("n").sum())'
    exact = 'pl.when(pl.col("n").count() > 0).then(pl.col("n").cast(pl.Decimal(38, 0)).sum())'
    assert exact in to_source(spec, "polars", schema=overflowing().schema)
    assert plain in to_source(spec, "polars")


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
    ("dataset", "dtype", "value"),
    [
        ("date", pl.Date(), "2024-01-02"),
        ("datetime", pl.Datetime(), "2024-01-02T09:30:00"),
        ("ZoneInfo", pl.Datetime(time_zone="UTC"), "2024-01-02T09:30:00"),
    ],
)
def test_dataset_named_like_a_generated_import_is_rejected(
    dataset: str, dtype: pl.DataType, value: str
) -> None:
    # The import line would rebind the dataset before the chain reads it.
    spec = QuerySpec(dataset=dataset, filters=[Filter(col="ts", op="ge", value=value)])
    with pytest.raises(ValueError, match="shadowed by the generated import"):
        to_source(spec, "polars", schema={"ts": dtype})


def test_relation_source_needs_a_result_name_other_than_the_dataset() -> None:
    # The generated code drops its view through the dataset after assigning the result.
    with pytest.raises(ValueError, match="must differ from the dataset"):
        to_source(QuerySpec(dataset="trades"), "duckdb", result_name="trades")
    source = to_source(QuerySpec(dataset="trades"), "polars", result_name="trades")
    assert source.startswith("trades = (\n    trades.lazy()")


@pytest.mark.parametrize(
    "value",
    ['say "hi"', "back\\slash", "new\nline", "café", "nul\x00", 0, -3, 2.5, True, None],
)
def test_py_literal_round_trips(value: Json) -> None:
    assert ast.literal_eval(py_literal(value)) == value
    assert ast.literal_eval(py_literal([value, [value]])) == [value, [value]]


def test_py_literal_escapes_non_printable_characters() -> None:
    assert py_literal("a\u202eb") == '"a\\u202eb"'
    assert py_literal("\U000e0001") == '"\\U000e0001"'
    tricky = "x\u2028\x85\u2029\u202e\xa0\ud800\U000e0001\U0001f600y"
    assert ast.literal_eval(py_literal(tricky)) == tricky


def test_py_literal_uses_double_quotes() -> None:
    assert py_literal("AAPL") == '"AAPL"'
    assert py_literal(["note col", 'q"uote']) == '["note col", "q\\"uote"]'


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
