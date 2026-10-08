"""Fixture frame, specs and DuckDB connection shared by every compile-target test."""

from datetime import UTC, date, datetime
from typing import Literal

import duckdb
import polars as pl

from quarry.query import Agg, Filter, Pivot, QuerySpec, Sort


def utc_connection() -> duckdb.DuckDBPyConnection:
    """A connection in UTC, as the kernel's runs, so `ts_utc` reads back as it went in."""
    conn = duckdb.connect()
    conn.execute("SET TimeZone = 'UTC'")
    return conn


def trades() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date": [
                date(2024, 1, 2),
                date(2024, 1, 2),
                date(2024, 1, 3),
                date(2024, 1, 3),
                date(2024, 1, 4),
            ],
            "ticker": ["AAPL", "MSFT", "AAPL", "MSFT", "AAPL"],
            "sector": ["tech", "tech", "tech", "tech", "tech"],
            "ret": [0.01, -0.02, 0.03, 0.00, None],
            "volume": [100, 200, 300, 400, 500],
            "note col": ["a", "b", "c", "d", "e"],
            'q"uote': [1, 2, 3, 4, 5],
            "ts": [
                datetime(2024, 1, 2, 9, 30),
                datetime(2024, 1, 2, 16, 0),
                datetime(2024, 1, 3, 9, 30),
                datetime(2024, 1, 3, 16, 0),
                datetime(2024, 1, 4, 9, 30),
            ],
            "ts_utc": [
                datetime(2024, 1, 2, 14, 30, tzinfo=UTC),
                datetime(2024, 1, 2, 21, 0, tzinfo=UTC),
                datetime(2024, 1, 3, 14, 30, tzinfo=UTC),
                datetime(2024, 1, 3, 21, 0, tzinfo=UTC),
                datetime(2024, 1, 4, 14, 30, tzinfo=UTC),
            ],
        }
    )


# No first/last: to_sql rejects them, as a relation has no row order to pick by.
SPECS: list[QuerySpec] = [
    QuerySpec(dataset="trades"),
    QuerySpec(dataset="trades", select=["ticker", "ret"]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="eq", value="AAPL")]),
    QuerySpec(dataset="trades", filters=[Filter(col="volume", op="between", value=[200, 400])]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="in", value=["AAPL", "IBM"])]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="not_in", value=["AAPL"])]),
    QuerySpec(dataset="trades", filters=[Filter(col="ret", op="is_null")]),
    QuerySpec(dataset="trades", filters=[Filter(col="ret", op="not_null")]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="contains", value="AP")]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="starts_with", value="MS")]),
    QuerySpec(dataset="trades", filters=[Filter(col="date", op="ge", value="2024-01-03")]),
    QuerySpec(
        dataset="trades",
        filters=[Filter(col="volume", op="gt", value=250), Filter(col="ret", op="ne", value=0.0)],
    ),
    QuerySpec(
        dataset="trades",
        group_by=["ticker"],
        aggs=[
            Agg(col="ret", fn="sum"),
            Agg(col="ret", fn="mean"),
            Agg(col="ret", fn="min"),
            Agg(col="ret", fn="max"),
            Agg(col="ret", fn="count"),
            Agg(col="volume", fn="median"),
            Agg(col="volume", fn="std", alias="vol_sd"),
        ],
        sort=[Sort(col="ticker")],
    ),
    QuerySpec(
        dataset="trades",
        pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="sum"),
        sort=[Sort(col="date")],
    ),
    QuerySpec(dataset="trades", sort=[Sort(col="volume", desc=True)], limit=2),
    QuerySpec(dataset="trades", sort=[Sort(col="volume")], limit=2, offset=1),
    QuerySpec(
        dataset="trades", select=["note col", 'q"uote'], sort=[Sort(col='q"uote', desc=True)]
    ),
    QuerySpec(dataset="trades", sort=[Sort(col="ret")], limit=2),
    QuerySpec(dataset="trades", sort=[Sort(col="ret", desc=True)], limit=2),
    QuerySpec(
        dataset="trades",
        filters=[Filter(col="ret", op="is_null")],
        group_by=["ticker"],
        aggs=[Agg(col="ret", fn="sum"), Agg(col="ret", fn="count"), Agg(col="ret", fn="std")],
    ),
    QuerySpec(
        dataset="trades",
        pivot=Pivot(index=["date"], columns="ticker", values="ret", agg="count"),
        sort=[Sort(col="date")],
    ),
    QuerySpec(
        dataset="trades",
        pivot=Pivot(index=["ticker"], columns="sector", values="volume", agg="std"),
        sort=[Sort(col="ticker")],
    ),
    QuerySpec(dataset="trades", filters=[Filter(col="ret", op="in", value=[0])]),
    QuerySpec(dataset="trades", filters=[Filter(col="ret", op="not_in", value=[0])]),
    QuerySpec(dataset="trades", filters=[Filter(col="volume", op="in", value=[100.0, 300])]),
    QuerySpec(dataset="trades", filters=[Filter(col="ts", op="ge", value="2024-01-03T09:30:00")]),
    QuerySpec(
        dataset="trades",
        filters=[Filter(col="ts_utc", op="lt", value="2024-01-03T14:30:00+00:00")],
    ),
    QuerySpec(
        dataset="trades",
        filters=[
            Filter(
                col="ts_utc",
                op="between",
                value=["2024-01-02T21:00:00+00:00", "2024-01-03T21:00:00+00:00"],
            )
        ],
    ),
    QuerySpec(dataset="trades", sort=[Sort(col="ts", desc=True)], limit=2),
    QuerySpec(
        dataset="trades", select=["ts_utc", "ticker"], sort=[Sort(col="ts_utc", desc=True)], limit=3
    ),
    QuerySpec(
        dataset="trades",
        group_by=["ticker"],
        aggs=[
            Agg(col="ts", fn="min"),
            Agg(col="ts", fn="max"),
            Agg(col="ts_utc", fn="min"),
            Agg(col="ts_utc", fn="max"),
        ],
        sort=[Sort(col="ticker")],
    ),
]


def overflowing(
    top: int = 2**62, dtype: pl.DataType | type[pl.DataType] = pl.Int64
) -> pl.DataFrame:
    """Group "a" sums `top` twice, past Int64 at the default; group "b" sums only a null."""
    return pl.DataFrame(
        {"k": ["a", "a", "b"], "c": ["x", "x", "x"], "n": pl.Series([top, top, None], dtype=dtype)}
    )


def new_york_rows() -> pl.DataFrame:
    """UTC 00:00, 03:00 and 06:00 on 2024-01-01, held in a New York Datetime column."""
    utc = [datetime(2024, 1, 1, hour, tzinfo=UTC) for hour in (0, 3, 6)]
    return pl.DataFrame({"n": [1, 2, 3], "ts": utc}).with_columns(
        pl.col("ts").dt.convert_time_zone("America/New_York")
    )


# Over `new_york_rows()`, with the `n` each selects. DuckDB, in its UTC session, reads a naive
# string as UTC; the polars target must agree.
ZONED_FILTERS: list[tuple[Filter, list[int]]] = [
    (Filter(col="ts", op="ge", value="2024-01-01T02:00:00"), [2, 3]),
    (Filter(col="ts", op="ge", value="2023-12-31T21:00:00-05:00"), [2, 3]),
    (Filter(col="ts", op="between", value=["2024-01-01T02:00:00", "2024-01-01T04:00:00"]), [2]),
    (Filter(col="ts", op="in", value=["2024-01-01T03:00:00", "2024-01-01T06:00:00Z"]), [2, 3]),
]
ZONED_IDS = ["naive", "offset", "naive_between", "in"]

TimeUnit = Literal["us", "ms", "ns"]
NAIVE_UNITS: list[TimeUnit] = ["us", "ms", "ns"]


def naive_rows(unit: TimeUnit) -> pl.DataFrame:
    """07:00, 07:30 and 09:30 on 2024-01-03 in a naive Datetime column of `unit`."""
    ts = [datetime(2024, 1, 3, 7), datetime(2024, 1, 3, 7, 30), datetime(2024, 1, 3, 9, 30)]
    return pl.DataFrame({"n": [1, 2, 3], "ts": pl.Series(ts, dtype=pl.Datetime(unit))})


# 09:30+02:00 is 07:30 UTC. Over `naive_rows(unit)`, the `n` each filter selects per unit: DuckDB
# 1.5.6 casts the string to TIMESTAMP_NS in UTC (07:30), but to TIMESTAMP (polars "us") and
# TIMESTAMP_MS by dropping the offset (09:30). The polars target must agree.
_OFFSET = "2024-01-03T09:30:00+02:00"
_AS_UTC, _AS_WALL_CLOCK = [2, 3], [3]
NAIVE_OFFSET_FILTERS: list[tuple[Filter, dict[TimeUnit, list[int]]]] = [
    (
        Filter(col="ts", op="ge", value=_OFFSET),
        {"us": _AS_WALL_CLOCK, "ms": _AS_WALL_CLOCK, "ns": _AS_UTC},
    ),
    (
        Filter(col="ts", op="between", value=[_OFFSET, "2024-01-04"]),
        {"us": _AS_WALL_CLOCK, "ms": _AS_WALL_CLOCK, "ns": _AS_UTC},
    ),
    (Filter(col="ts", op="in", value=[_OFFSET]), {"us": [3], "ms": [3], "ns": [2]}),
]
NAIVE_OFFSET_IDS = ["ge", "between", "in"]


def past_decimal_38(dtype: pl.DataType) -> pl.DataFrame:
    """Group "a" holds 10**38, one past Decimal(38, 0); group "b" sums only a null."""
    return pl.DataFrame(
        {"k": ["a", "b"], "c": ["x", "x"], "n": pl.Series([10**38, None], dtype=dtype)}
    )


# Over `overflowing()`: each gives the rows [("a", 2 * top), ("b", None)].
INT_SUM_SPECS: list[QuerySpec] = [
    QuerySpec(dataset="nums", group_by=["k"], aggs=[Agg(col="n", fn="sum")], sort=[Sort(col="k")]),
    QuerySpec(
        dataset="nums",
        pivot=Pivot(index=["k"], columns="c", values="n", agg="sum"),
        sort=[Sort(col="k")],
    ),
]
INT_SUM_IDS = ["group_by", "pivot"]
