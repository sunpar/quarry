import sys
from collections.abc import Iterable, Sequence
from pathlib import Path

import polars as pl
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


def test_sql_with_no_batches_returns_empty_frame() -> None:
    def empty(query: str, dsn: str, params: Sequence[object] | None) -> Iterable[pa.RecordBatch]:
        return iter(())

    df = make_sql("dsn-x", reader=empty)("SELECT 1")
    assert df.height == 0


def test_sql_with_no_rows_keeps_the_schema() -> None:
    schema = pa.schema([("ticker", pa.string()), ("px", pa.float64())])

    def no_rows(query: str, dsn: str, params: Sequence[object] | None) -> Iterable[pa.RecordBatch]:
        reader: Iterable[pa.RecordBatch] = pa.RecordBatchReader.from_batches(schema, [])
        return reader

    df = make_sql("dsn-x", reader=no_rows)("SELECT ticker, px FROM prices WHERE 1 = 0")
    assert df.height == 0
    assert df.schema == pl.Schema({"ticker": pl.String, "px": pl.Float64})


def test_sql_without_dsn_raises() -> None:
    with pytest.raises(RuntimeError, match="DSN"):
        make_sql("", reader=fake_reader)("SELECT 1")


def test_sql_without_the_mssql_extra_says_to_install_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(sys.modules, "arrow_odbc", None)
    with pytest.raises(
        ModuleNotFoundError, match=r"mssql extra: uv pip install 'quarry\[mssql\]'"
    ) as raised:
        make_sql("dsn-x")("SELECT 1")
    assert isinstance(raised.value.__cause__, ModuleNotFoundError)


def test_sql_reraises_another_missing_module_unchanged(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "arrow_odbc.py").write_text("import quarry_test_no_such_dependency\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.delitem(sys.modules, "arrow_odbc", raising=False)
    with pytest.raises(ModuleNotFoundError) as raised:
        make_sql("dsn-x")("SELECT 1")
    assert raised.value.name == "quarry_test_no_such_dependency"
    assert "mssql" not in str(raised.value)
