from collections.abc import Iterable, Sequence

import pyarrow as pa
import pytest

from quarry.data.mssql import make_sql


def fake_reader(query: str, dsn: str, params: Sequence[object] | None) -> Iterable[pa.RecordBatch]:
    assert dsn == "dsn-x"
    assert "FROM prices" in query
    yield pa.RecordBatch.from_pydict({"ticker": ["A"], "px": [1.5]})
    yield pa.RecordBatch.from_pydict({"ticker": ["B"], "px": [2.5]})


def test_sql_concatenates_batches_into_polars() -> None:
    sql = make_sql("dsn-x", reader=fake_reader)
    df = sql("SELECT * FROM prices")
    assert df["ticker"].to_list() == ["A", "B"]
    assert df["px"].to_list() == [1.5, 2.5]


def test_sql_with_no_rows_returns_empty_frame_with_schema() -> None:
    def empty(query: str, dsn: str, params: Sequence[object] | None) -> Iterable[pa.RecordBatch]:
        return iter(())

    df = make_sql("dsn-x", reader=empty)("SELECT 1")
    assert df.height == 0


def test_sql_without_dsn_raises() -> None:
    with pytest.raises(RuntimeError, match="DSN"):
        make_sql("", reader=fake_reader)("SELECT 1")
