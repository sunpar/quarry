import duckdb
import pytest

from quarry.query import Agg, Filter, Pivot, QueryError, QuerySpec, Sort
from quarry.query.sql_target import quote_ident, quote_literal, to_sql
from tests.query.fixtures import trades

VOLUME_BY_TICKER = Pivot(index=["date"], columns="ticker", values="volume", agg="sum")


def run(sql: str) -> duckdb.DuckDBPyRelation:
    conn = duckdb.connect()
    conn.register("trades", trades())
    return conn.sql(sql)


def test_quote_ident_escapes_double_quotes() -> None:
    assert quote_ident('q"uote') == '"q""uote"'
    assert quote_ident("note col") == '"note col"'


def test_quote_literal() -> None:
    assert quote_literal("it's") == "'it''s'"
    assert quote_literal(3) == "3"
    assert quote_literal(2.5) == "2.5"
    assert quote_literal(True) == "TRUE"
    assert quote_literal(None) == "NULL"


@pytest.mark.parametrize("value", [float("inf"), float("-inf"), float("nan")])
def test_quote_literal_non_finite_float_is_a_double_not_an_identifier(value: float) -> None:
    rendered = quote_literal(value)
    assert rendered == f"'{value!r}'::DOUBLE"
    assert duckdb.sql(f"SELECT {rendered} AS v").fetchone() is not None


def test_passthrough() -> None:
    sql = to_sql(QuerySpec(dataset="trades"), "trades")
    assert run(sql).pl().height == 5


def test_filter_and_select_with_odd_names() -> None:
    spec = QuerySpec(
        dataset="trades",
        select=["note col", 'q"uote'],
        filters=[Filter(col='q"uote', op="gt", value=3)],
        sort=[Sort(col='q"uote', desc=True)],
    )
    out = run(to_sql(spec, "trades")).pl()
    assert out.columns == ["note col", 'q"uote']
    assert out['q"uote'].to_list() == [5, 4]


def test_string_literal_against_date_column() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="date", op="ge", value="2024-01-03")])
    assert run(to_sql(spec, "trades")).pl().height == 3


def test_group_by_aliases() -> None:
    spec = QuerySpec(
        dataset="trades",
        group_by=["ticker"],
        aggs=[Agg(col="ret", fn="mean"), Agg(col="volume", fn="sum", alias="vol")],
        sort=[Sort(col="ticker")],
    )
    out = run(to_sql(spec, "trades")).pl()
    assert out.columns == ["ticker", "ret_mean", "vol"]


def test_pivot() -> None:
    spec = QuerySpec(
        dataset="trades",
        pivot={"index": ["date"], "columns": "ticker", "values": "volume", "agg": "sum"},
        sort=[Sort(col="date")],
    )
    out = run(to_sql(spec, "trades")).pl()
    assert sorted(out.columns) == ["AAPL", "MSFT", "date"]
    assert out["AAPL"].to_list() == [100, 300, 500]


@pytest.mark.parametrize("desc", [False, True], ids=["asc", "desc"])
def test_sort_puts_nulls_first(desc: bool) -> None:
    spec = QuerySpec(dataset="trades", sort=[Sort(col="ret", desc=desc)])
    out = run(to_sql(spec, "trades")).pl()
    assert out["ret"][0] is None


def test_unknown_column_raises_when_columns_given() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="nope", op="eq", value=1)])
    with pytest.raises(QueryError):
        to_sql(spec, "trades", columns=trades().columns)


def test_sort_on_column_dropped_by_group_by_raises_when_columns_given() -> None:
    spec = QuerySpec(
        dataset="trades",
        group_by=["ticker"],
        aggs=[Agg(col="ret", fn="mean")],
        sort=[Sort(col="volume")],
    )
    with pytest.raises(QueryError) as info:
        to_sql(spec, "trades", columns=trades().columns)
    assert info.value.column == "volume"


def test_pivot_output_columns_are_not_checked_before_running() -> None:
    spec = QuerySpec(dataset="trades", pivot=VOLUME_BY_TICKER, sort=[Sort(col="AAPL")])
    out = run(to_sql(spec, "trades", columns=trades().columns)).pl()
    assert out["AAPL"].to_list() == [100, 300, 500]
