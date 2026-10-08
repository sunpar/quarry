from datetime import date

import polars as pl
import pytest

from quarry.query import Agg, AggFn, Filter, Pivot, QueryError, QuerySpec, Sort
from quarry.query.polars_target import to_polars
from tests.query.fixtures import SPECS, trades


def test_passthrough_returns_lazyframe() -> None:
    out = to_polars(QuerySpec(dataset="trades"), trades())
    assert isinstance(out, pl.LazyFrame)
    assert out.collect().height == 5


def test_filter_eq() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="eq", value="AAPL")])
    assert to_polars(spec, trades()).collect().height == 3


def test_string_literal_against_date_column() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="date", op="ge", value="2024-01-03")])
    out = to_polars(spec, trades()).collect()
    assert out["date"].min() == date(2024, 1, 3)
    assert out.height == 3


def test_group_by_agg_names() -> None:
    spec = QuerySpec(
        dataset="trades",
        group_by=["ticker"],
        aggs=[Agg(col="ret", fn="mean"), Agg(col="volume", fn="sum", alias="vol")],
        sort=[Sort(col="ticker")],
    )
    out = to_polars(spec, trades()).collect()
    assert out.columns == ["ticker", "ret_mean", "vol"]
    assert out["vol"].to_list() == [900, 600]


def test_pivot() -> None:
    spec = QuerySpec(
        dataset="trades",
        pivot={"index": ["date"], "columns": "ticker", "values": "volume", "agg": "sum"},
        sort=[Sort(col="date")],
    )
    out = to_polars(spec, trades()).collect()
    assert out.columns == ["date", "AAPL", "MSFT"]
    assert out["AAPL"].to_list() == [100, 300, 500]


def test_sort_offset_limit_select_order() -> None:
    spec = QuerySpec(
        dataset="trades",
        select=["ticker"],
        sort=[Sort(col="volume", desc=True)],
        limit=2,
        offset=1,
    )
    out = to_polars(spec, trades()).collect()
    assert out.columns == ["ticker"]
    assert out["ticker"].to_list() == ["MSFT", "AAPL"]


def test_unknown_filter_column_raises_query_error() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="nope", op="eq", value=1)])
    with pytest.raises(QueryError) as info:
        to_polars(spec, trades())
    assert info.value.column == "nope"


def test_unknown_select_column_raises_query_error() -> None:
    with pytest.raises(QueryError):
        to_polars(QuerySpec(dataset="trades", select=["missing"]), trades())


def test_sort_on_column_dropped_by_group_by_raises_query_error() -> None:
    spec = QuerySpec(
        dataset="trades",
        group_by=["ticker"],
        aggs=[Agg(col="ret", fn="mean")],
        sort=[Sort(col="volume")],
    )
    with pytest.raises(QueryError) as info:
        to_polars(spec, trades())
    assert info.value.column == "volume"


def test_lazy_input_accepted() -> None:
    out = to_polars(QuerySpec(dataset="trades", limit=1), trades().lazy()).collect()
    assert out.height == 1


def test_sum_of_all_null_group_is_null() -> None:
    spec = QuerySpec(
        dataset="trades",
        filters=[Filter(col="ret", op="is_null")],
        group_by=["ticker"],
        aggs=[Agg(col="ret", fn="sum")],
    )
    out = to_polars(spec, trades()).collect()
    assert out.rows() == [("AAPL", None)]


def test_pivot_absent_cell_is_null_for_sum_and_zero_for_count() -> None:
    def msft_on_jan_4(values: str, agg: AggFn) -> object:
        pivot = Pivot(index=["date"], columns="ticker", values=values, agg=agg)
        spec = QuerySpec(dataset="trades", pivot=pivot)
        out = to_polars(spec, trades()).collect()
        return out.filter(pl.col("date") == date(2024, 1, 4))["MSFT"].item()

    assert msft_on_jan_4("volume", "sum") is None
    assert msft_on_jan_4("ret", "count") == 0


@pytest.mark.parametrize("spec", SPECS, ids=[s.model_dump_json() for s in SPECS])
def test_every_fixture_spec_compiles(spec: QuerySpec) -> None:
    to_polars(spec, trades()).collect()
