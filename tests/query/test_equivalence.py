"""Every fixture spec must agree across direct targets and generated source."""

from decimal import Decimal

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quarry.query import Filter, Pivot, QuerySpec, Sort, to_source
from quarry.query.polars_target import to_polars
from quarry.query.sql_target import to_sql
from tests.query.fixtures import (
    BACKINGS,
    INT_SUM_IDS,
    INT_SUM_SPECS,
    NAIVE_OFFSET_FILTERS,
    NAIVE_OFFSET_IDS,
    NAIVE_UNITS,
    SPECS,
    ZONED_FILTERS,
    ZONED_IDS,
    TimeUnit,
    assert_same_rows,
    bind,
    execute,
    naive_rows,
    new_york_rows,
    overflowing,
    trades,
    utc_connection,
)


@pytest.mark.parametrize("spec", SPECS, ids=[s.model_dump_json() for s in SPECS])
def test_targets_agree(spec: QuerySpec) -> None:
    frame = trades()
    via_polars = to_polars(spec, frame).collect()
    conn = utc_connection()
    conn.register("trades", frame)
    via_sql = conn.sql(to_sql(spec, "trades")).pl()
    assert_same_rows(spec, via_polars, via_sql)
    for backing in BACKINGS:
        source = to_source(spec, backing, schema=frame.schema)
        actual = execute(source, {"trades": bind(frame, backing)})
        assert_same_rows(spec, via_polars, actual)


def _grouped(keys: list[str], fn: str = "sum", **update: object) -> QuerySpec:
    return QuerySpec.model_validate(
        {"dataset": "t", "group_by": keys, "aggs": [{"col": "v", "fn": fn}], **update}
    )


@pytest.mark.parametrize(
    ("spec", "col", "expected"),
    [
        pytest.param(_grouped(["k"]), "k", [None, "a", "b", "c"], id="no-sort"),
        # Counts 2, 1, 2, 1 tie in pairs; each pair follows g, then k.
        pytest.param(
            _grouped(["g", "k"], "count", sort=[{"col": "v_count", "desc": True}]),
            "k",
            ["b", "a", None, "c"],
            id="ties",
        ),
        pytest.param(
            _grouped(["k"], sort=[{"col": "k", "desc": True}]), "k", [None, "c", "b", "a"], id="key"
        ),
        pytest.param(_grouped(["g", "k"], select=["v_sum"]), "v_sum", [2, 6, 9, 4], id="select"),
        pytest.param(_grouped(["k"], offset=1, limit=2), "k", ["a", "b"], id="page"),
        pytest.param(
            QuerySpec(dataset="t", pivot=Pivot(index=["k"], columns="g", values="v", agg="sum")),
            "k",
            [None, "a", "b", "c"],
            id="pivot",
        ),
    ],
)
def test_grouped_rows_follow_their_keys_on_every_target(
    spec: QuerySpec, col: str, expected: list[object]
) -> None:
    frame = pl.DataFrame(
        {"k": ["b", None, "a", "c", "b", "a"], "g": [1, 1, 2, 2, 1, 2], "v": [1, 2, 3, 4, 5, 6]}
    )
    results = _column_on_every_target(spec, frame, col)
    assert results == dict.fromkeys(results, expected)


def _column_on_every_target(
    spec: QuerySpec, frame: pl.DataFrame, col: str
) -> dict[str, list[object]]:
    """`col` of `spec`'s result over `frame`, registered as `t`, from each target."""
    conn = utc_connection()
    conn.register("t", frame)
    results: dict[str, pl.DataFrame] = {
        "to_polars": to_polars(spec, frame).collect(),
        "to_sql": conn.sql(to_sql(spec, "t")).pl(),
        **{
            f"source {b}": execute(to_source(spec, b, schema=frame.schema), {"t": bind(frame, b)})
            for b in BACKINGS
        },
    }
    return {target: df[col].to_list() for target, df in results.items()}


# Each integer dtype DuckDB can read from polars, with its largest value.
INT_MAX: dict[pl.DataType, int] = {
    pl.Int8(): 2**7 - 1,
    pl.Int16(): 2**15 - 1,
    pl.Int32(): 2**31 - 1,
    pl.Int64(): 2**63 - 1,
    pl.UInt8(): 2**8 - 1,
    pl.UInt16(): 2**16 - 1,
    pl.UInt32(): 2**32 - 1,
    pl.UInt64(): 2**64 - 1,
}


@pytest.mark.parametrize("dtype", INT_MAX, ids=str)
@pytest.mark.parametrize("spec", INT_SUM_SPECS, ids=INT_SUM_IDS)
def test_integer_sums_agree_exactly(spec: QuerySpec, dtype: pl.DataType) -> None:
    # DuckDB sums every integer type as HUGEINT, which .pl() reads as Decimal(38, 0). A direct
    # compare, as assert_same_rows ignores dtypes: both sides must be Decimal(38, 0).
    top = INT_MAX[dtype]
    frame = overflowing(top, dtype)
    via_polars = to_polars(spec, frame).collect()
    conn = utc_connection()
    conn.register("nums", frame)
    via_sql = conn.sql(to_sql(spec, "nums")).pl()
    assert_frame_equal(via_polars, via_sql)
    assert via_sql.dtypes[1] == pl.Decimal(38, 0)
    assert via_polars.rows() == [("a", 2 * top), ("b", None)]


@pytest.mark.parametrize(
    "filter_",
    [
        Filter(col="x", op="eq", value=0.1),
        Filter(col="x", op="le", value=0.1),
        Filter(col="x", op="gt", value=0.1),
        Filter(col="x", op="in", value=[0.1]),
        Filter(col="x", op="between", value=[0.1, 0.2]),
    ],
    ids=lambda f: f.model_dump_json(),
)
def test_a_float32_column_compares_as_float64_on_every_target(filter_: Filter) -> None:
    # The viewer reads Float32 as Float64, where a stored 0.1 is not 0.1.
    spec = QuerySpec(dataset="t", filters=[filter_], select=["n"], sort=[Sort(col="n")])
    frame = pl.DataFrame({"n": [1, 2, 3], "x": pl.Series([0.05, 0.1, 0.2], dtype=pl.Float32)})
    wide = to_polars(spec, frame.cast({"x": pl.Float64})).collect()["n"].to_list()
    results = _column_on_every_target(spec, frame, "n")
    assert results == dict.fromkeys(results, wide)


@pytest.mark.parametrize("op", ["eq", "le", "gt"])
def test_a_fraction_against_a_decimal_column_compares_as_float64_on_every_target(
    op: str,
) -> None:
    # Both rows read as the Float64 0.3, which the viewer and polars compare.
    spec = QuerySpec.model_validate(
        {"dataset": "t", "filters": [{"col": "x", "op": op, "value": 0.3}], "select": ["n"]}
    )
    exact = [Decimal("0.3"), Decimal("0.30000000000000000001")]
    frame = pl.DataFrame({"n": [1, 2], "x": pl.Series(exact, dtype=pl.Decimal(38, 20))})
    wide = to_polars(spec, frame.cast({"x": pl.Float64})).collect()["n"].to_list()
    results = _column_on_every_target(spec, frame, "n")
    assert results == dict.fromkeys(results, wide)


@pytest.mark.parametrize(("filter_", "selected"), ZONED_FILTERS, ids=ZONED_IDS)
def test_iso_strings_against_a_zoned_column_agree(filter_: Filter, selected: list[int]) -> None:
    spec = QuerySpec(dataset="t", filters=[filter_], select=["n"], sort=[Sort(col="n")])
    frame = new_york_rows()
    conn = utc_connection()
    conn.register("frame", frame)
    # A table: DuckDB pushes an IN filter into a registered frame's Arrow scan through pytz,
    # which quarry does not install.
    conn.execute("CREATE TABLE t AS FROM frame")
    assert to_polars(spec, frame).collect()["n"].to_list() == selected
    assert conn.sql(to_sql(spec, "t")).pl()["n"].to_list() == selected


@pytest.mark.parametrize("unit", NAIVE_UNITS)
@pytest.mark.parametrize(("filter_", "selected"), NAIVE_OFFSET_FILTERS, ids=NAIVE_OFFSET_IDS)
def test_offset_strings_against_a_naive_column_agree(
    filter_: Filter, selected: dict[TimeUnit, list[int]], unit: TimeUnit
) -> None:
    spec = QuerySpec(dataset="t", filters=[filter_], select=["n"], sort=[Sort(col="n")])
    frame = naive_rows(unit)
    conn = utc_connection()
    conn.register("t", frame)
    assert conn.sql(to_sql(spec, "t")).pl()["n"].to_list() == selected[unit]
    assert to_polars(spec, frame).collect()["n"].to_list() == selected[unit]
