"""Every fixture spec must produce the same result on both execution targets."""

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quarry.query import Filter, QuerySpec, Sort
from quarry.query.polars_target import to_polars
from quarry.query.sql_target import to_sql
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
    trades,
    utc_connection,
)


def normalize(df: pl.DataFrame) -> pl.DataFrame:
    df = df.select(sorted(df.columns))
    numeric = [c for c, t in df.schema.items() if t.is_numeric()]
    df = df.with_columns([pl.col(c).cast(pl.Float64) for c in numeric])
    return df.sort(df.columns)


@pytest.mark.parametrize("spec", SPECS, ids=[s.model_dump_json() for s in SPECS])
def test_targets_agree(spec: QuerySpec) -> None:
    frame = trades()
    via_polars = to_polars(spec, frame).collect()
    conn = utc_connection()
    conn.register("trades", frame)
    via_sql = conn.sql(to_sql(spec, "trades")).pl()
    assert_frame_equal(normalize(via_polars), normalize(via_sql), check_dtypes=False, rel_tol=1e-9)


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
    # DuckDB sums every integer type as HUGEINT, which .pl() reads as Decimal(38, 0). No
    # normalize: a Float64 cast would round 2 * (2**64 - 1) and hide the dtypes.
    top = INT_MAX[dtype]
    frame = overflowing(top, dtype)
    via_polars = to_polars(spec, frame).collect()
    conn = utc_connection()
    conn.register("nums", frame)
    via_sql = conn.sql(to_sql(spec, "nums")).pl()
    assert_frame_equal(via_polars, via_sql)
    assert via_sql.dtypes[1] == pl.Decimal(38, 0)
    assert via_polars.rows() == [("a", 2 * top), ("b", None)]


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
