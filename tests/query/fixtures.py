"""Fixture frame and specs shared by every compile-target test."""

from datetime import date

import polars as pl

from quarry.query import Agg, Filter, Pivot, QuerySpec, Sort


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
        }
    )


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
]
