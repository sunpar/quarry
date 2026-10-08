from datetime import date

import polars as pl
import pytest

from quarry.query import Agg, AggFn, Filter, Json, Pivot, QueryError, QuerySpec, Sort
from quarry.query.polars_target import CoercedLiteral, coerce_literal, to_polars
from tests.query.fixtures import SPECS, trades

VOLUME_BY_TICKER = Pivot(index=["date"], columns="ticker", values="volume", agg="sum")


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


def test_pivot_columns_are_sorted() -> None:
    frame = pl.DataFrame(
        {"date": [date(2024, 1, 2)] * 2, "ticker": ["ZZZ", "MSFT"], "volume": [1, 2]}
    )
    pivot = Pivot(index=["date"], columns="ticker", values="volume", agg="sum")
    out = to_polars(QuerySpec(dataset="t", pivot=pivot), frame).collect()
    assert out.columns == ["date", "MSFT", "ZZZ"]


def test_pivot_unknown_select_raises_query_error() -> None:
    spec = QuerySpec(dataset="trades", pivot=VOLUME_BY_TICKER, select=["nope"])
    with pytest.raises(QueryError) as info:
        to_polars(spec, trades())
    assert info.value.column == "nope"


def test_pivot_unknown_sort_raises_query_error() -> None:
    spec = QuerySpec(dataset="trades", pivot=VOLUME_BY_TICKER, sort=[Sort(col="nope")])
    with pytest.raises(QueryError) as info:
        to_polars(spec, trades())
    assert info.value.column == "nope"


@pytest.mark.parametrize(
    ("value", "dtype", "expected"),
    [
        (0, pl.Float64(), CoercedLiteral(0.0, compare_as_float=False)),
        ([1, 2.5], pl.Float32(), CoercedLiteral([1.0, 2.5], compare_as_float=False)),
        (100.0, pl.Int64(), CoercedLiteral(100, compare_as_float=False)),
        ([100, 200.5], pl.Int64(), CoercedLiteral([100.0, 200.5], compare_as_float=True)),
        ("2024-01-03", pl.Date(), CoercedLiteral(date(2024, 1, 3), compare_as_float=False)),
        (True, pl.Float64(), CoercedLiteral(True, compare_as_float=False)),
        ("AAPL", pl.String(), CoercedLiteral("AAPL", compare_as_float=False)),
    ],
)
def test_coerce_literal(value: Json, dtype: pl.DataType, expected: CoercedLiteral) -> None:
    # Compare reprs: 0 == 0.0 in Python, so plain equality would hide a missed coercion.
    assert repr(coerce_literal(value, dtype)) == repr(expected)


@pytest.mark.parametrize(
    ("flt", "height"),
    [
        (Filter(col="ret", op="in", value=[0]), 1),
        (Filter(col="ret", op="eq", value=0), 1),
        (Filter(col="volume", op="in", value=[100.0]), 1),
        (Filter(col="volume", op="in", value=[100, 200.5]), 1),
        (Filter(col="volume", op="eq", value=100.5), 0),
        (Filter(col="volume", op="gt", value=399.5), 2),
        (Filter(col="volume", op="between", value=[100.0, 250.5]), 2),
    ],
    ids=lambda flt: flt.model_dump_json() if isinstance(flt, Filter) else str(flt),
)
def test_numeric_literal_matches_column_dtype(flt: Filter, height: int) -> None:
    out = to_polars(QuerySpec(dataset="trades", filters=[flt]), trades()).collect()
    assert out.height == height


def test_not_in_excludes_null_like_sql() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="ret", op="not_in", value=[0])])
    out = to_polars(spec, trades()).collect()
    assert out["ret"].to_list() == [0.01, -0.02, 0.03]


@pytest.mark.parametrize("spec", SPECS, ids=[s.model_dump_json() for s in SPECS])
def test_every_fixture_spec_compiles(spec: QuerySpec) -> None:
    to_polars(spec, trades()).collect()
