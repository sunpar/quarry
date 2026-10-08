import base64
import io
from pathlib import Path

import duckdb
import polars as pl
import pytest
from polars.exceptions import ColumnNotFoundError

from quarry.kernel.executor import Executor, _identity_check
from quarry.query import Filter, Pivot, QueryError, QuerySpec

PIVOT_ROWS = (
    "SELECT * FROM (VALUES ('a', 'x', 1), ('a', 'y', 2), ('b', 'x', 3), ('b', 'y', 40)) t(k, c, v)"
)
BAD_PLAN = "lf = pl.DataFrame({'a': [1]}).lazy().filter(pl.col('nope') > 1)"


def make() -> Executor:
    conn = duckdb.connect()
    return Executor({"pl": pl, "duckdb": duckdb, "_conn": conn}, row_cap=3)


def test_execute_registers_dataset_and_reports_lineage() -> None:
    ex = make()
    result = ex.execute("returns = pl.DataFrame({'ticker': ['A', 'B'], 'ret': [0.1, 0.2]})")
    assert result.status == "ok"
    assert result.writes == ["returns"]
    assert result.reads == []
    assert result.datasets[0].name == "returns"
    assert result.datasets[0].rows == 2
    second = ex.execute("top = returns.filter(pl.col('ret') > 0.15)")
    assert second.reads == ["returns"]
    assert second.writes == ["top"]


def test_execute_captures_stdout_tail() -> None:
    ex = make()
    result = ex.execute("print('x' * 10000)")
    assert result.status == "ok"
    assert len(result.stdout_tail) == 4096
    assert result.stdout_tail.endswith("x\n")


def test_execute_error_is_structured() -> None:
    ex = make()
    result = ex.execute("1 / 0")
    assert result.status == "error"
    assert result.error is not None
    assert result.error.type == "ZeroDivisionError"
    assert "ZeroDivisionError" in result.error.traceback


def test_execute_syntax_error_is_structured() -> None:
    result = make().execute("def (:")
    assert result.status == "error"
    assert result.error is not None
    assert result.error.type == "SyntaxError"


def test_execute_code_too_deep_to_parse_is_structured() -> None:
    # ast.parse gives up on this with MemoryError (3.11) or RecursionError, not SyntaxError.
    result = make().execute("x = " + "-" * 200_000 + "1")
    assert result.status == "error"
    assert result.error is not None
    assert result.reads == []


def test_execute_keyboard_interrupt_is_interrupted_status() -> None:
    result = make().execute("raise KeyboardInterrupt")
    assert result.status == "interrupted"


def test_execute_system_exit_is_structured_error() -> None:
    result = make().execute("raise SystemExit(3)")
    assert result.status == "error"
    assert result.error is not None
    assert result.error.type == "SystemExit"


def test_rebinding_to_non_dataset_removes_it() -> None:
    ex = make()
    ex.execute("returns = pl.DataFrame({'a': [1]})")
    result = ex.execute("returns = None")
    assert result.writes == []
    assert [m.name for m in ex.list_datasets()] == []


def test_helper_defined_earlier_counts_as_read() -> None:
    ex = make()
    ex.execute("def clean(df):\n    return df.head(1)\n")
    ex.execute("returns = pl.DataFrame({'a': [1, 2]})")
    result = ex.execute("small = clean(returns)")
    assert result.reads == ["clean", "returns"]


def test_helper_rebinding_a_dataset_through_global_is_a_write() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1, 2]})")
    ex.execute("def shrink():\n    global df\n    df = df.head(1)\n")
    result = ex.execute("shrink()")
    assert result.status == "ok"
    assert result.writes == ["df"]
    assert "shrink" in result.reads
    assert result.datasets[0].rows == 1


def test_rebinding_twice_in_one_step_is_a_write_despite_address_reuse() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': list(range(10))})")
    ex.execute("def shrink():\n    global df\n    df = df.head(df.height - 1)\n")
    result = ex.execute("shrink()\nshrink()")
    assert result.status == "ok"
    assert result.writes == ["df"]
    assert result.datasets[0].rows == 8


def test_identity_check_falls_back_to_id_without_weakref_support() -> None:
    held = (1, 2)
    same = _identity_check(held)
    assert same(held)
    assert not same((1, 2, 3))


def test_failed_step_does_not_report_its_unrun_store_as_write() -> None:
    ex = make()
    ex.execute("returns = pl.DataFrame({'a': [1, 2]})")
    result = ex.execute("x = 1 / 0\nreturns = returns.head(1)")
    assert result.status == "error"
    assert result.writes == []
    assert ex.describe("returns").rows == 2


def test_deleting_a_dataset_is_not_a_write() -> None:
    ex = make()
    ex.execute("returns = pl.DataFrame({'a': [1]})")
    result = ex.execute("del returns")
    assert result.status == "ok"
    assert result.writes == []
    assert [m.name for m in ex.list_datasets()] == []


def test_failed_step_does_not_define_helpers_it_never_reached() -> None:
    ex = make()
    failed = ex.execute("x = 1 / 0\ndef helper():\n    return 1\n")
    assert failed.defines == []
    later = ex.execute("helper()")
    assert later.reads == []


def test_describe_failure_after_exec_is_structured_error() -> None:
    ex = make()
    result = ex.execute(BAD_PLAN)
    assert result.status == "error"
    assert result.writes == ["lf"]
    assert result.error is not None
    assert result.error.type == "ColumnNotFoundError"
    assert result.error.message.startswith("lf: ")
    assert "ColumnNotFoundError" in result.error.traceback
    (meta,) = result.datasets
    assert meta.name == "lf"
    assert meta.backing == "polars_lazy"
    assert (meta.schema_, meta.rows, meta.preview) == ([], None, [])
    assert meta.error is not None
    assert meta.error.startswith("lf: ColumnNotFoundError: ")


def test_list_datasets_reports_an_undescribable_dataset_with_its_error() -> None:
    ex = make()
    ex.execute("good = pl.DataFrame({'a': [1]})")
    ex.execute(BAD_PLAN)
    good, bad = ex.list_datasets()
    assert (good.name, good.error, good.rows) == ("good", None, 1)
    assert bad.name == "lf"
    assert bad.error is not None
    assert bad.error.startswith("lf: ColumnNotFoundError: ")
    with pytest.raises(ColumnNotFoundError):
        ex.describe("lf")


def test_unprintable_exception_is_structured_error() -> None:
    code = "class E(Exception):\n    def __str__(self):\n        return self.msg\nraise E()"
    result = make().execute(code)
    assert result.status == "error"
    assert result.error is not None
    assert result.error.type == "E"
    assert result.error.message == "<unprintable E>"


def test_non_string_namespace_key_does_not_break_later_steps() -> None:
    ex = make()
    assert ex.execute("globals()[1] = 1").status == "ok"
    result = ex.execute("x = pl.DataFrame({'a': [1]})")
    assert result.status == "ok"
    assert result.writes == ["x"]


def test_running_is_true_only_while_user_code_runs() -> None:
    namespace: dict[str, object] = {"pl": pl}
    ex = Executor(namespace, row_cap=3)
    namespace["_ex"] = ex
    assert ex.running is False
    result = ex.execute("seen = _ex.running")
    assert result.status == "ok"
    assert namespace["seen"] is True
    assert ex.running is False


def test_describe_and_unknown_name() -> None:
    ex = make()
    ex.execute("lf = pl.DataFrame({'a': [1, 2, 3]}).lazy()")
    assert ex.describe("lf").rows == 3
    with pytest.raises(KeyError):
        ex.describe("nope")


def test_query_polars_with_row_cap() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [5, 4, 3, 2, 1]})")
    out = ex.query(QuerySpec(dataset="df", sort=[{"col": "a"}]))
    assert out.rows == [{"a": 1}, {"a": 2}, {"a": 3}]
    assert out.truncated is True
    assert out.row_count == 3


@pytest.mark.parametrize(
    ("height", "limit", "rows", "truncated"),
    [(3, None, 3, False), (4, None, 3, True), (5, 2, 2, False), (5, 3, 3, False), (5, 4, 3, True)],
)
def test_query_truncated_only_when_rows_beyond_cap_exist(
    height: int, limit: int | None, rows: int, truncated: bool
) -> None:
    ex = make()
    ex.execute(f"df = pl.DataFrame({{'a': list(range({height}))}})")
    out = ex.query(QuerySpec(dataset="df", limit=limit))
    assert out.row_count == rows
    assert out.rows is not None
    assert len(out.rows) == rows
    assert out.truncated is truncated


def test_query_duckdb_relation() -> None:
    ex = make()
    ex.execute("rel = _conn.sql(\"SELECT * FROM (VALUES (1, 'x'), (2, 'y')) t(n, s)\")")
    out = ex.query(QuerySpec(dataset="rel", filters=[Filter(col="n", op="eq", value=2)]))
    assert out.rows == [{"n": 2, "s": "y"}]


def test_query_duckdb_relation_truncates_at_row_cap() -> None:
    ex = make()
    ex.execute('rel = _conn.sql("SELECT range AS n FROM range(10)")')
    out = ex.query(QuerySpec(dataset="rel", sort=[{"col": "n", "desc": True}]))
    assert out.rows == [{"n": 9}, {"n": 8}, {"n": 7}]
    assert out.truncated is True


def test_query_duckdb_relation_pivot() -> None:
    ex = make()
    ex.execute(f'rel = _conn.sql("{PIVOT_ROWS}")')
    spec = QuerySpec(
        dataset="rel",
        filters=[Filter(col="v", op="lt", value=10)],
        pivot=Pivot(index=["k"], columns="c", values="v", agg="sum"),
        sort=[{"col": "k"}],
    )
    out = ex.query(spec)
    assert out.rows == [{"k": "a", "x": 1, "y": 2}, {"k": "b", "x": 3, "y": None}]
    assert [c.name for c in out.schema_] == ["k", "x", "y"]


def test_query_duckdb_relation_pivot_unknown_select_raises_query_error() -> None:
    ex = make()
    ex.execute(f'rel = _conn.sql("{PIVOT_ROWS}")')
    spec = QuerySpec(
        dataset="rel",
        pivot=Pivot(index=["k"], columns="c", values="v", agg="sum"),
        select=["zz"],
    )
    with pytest.raises(QueryError):
        ex.query(spec)


def test_relation_with_interval_column_queries_and_snapshots(tmp_path: Path) -> None:
    ex = make()
    ex.execute("rel = _conn.sql(\"SELECT TIMESTAMP '2024-01-02' - TIMESTAMP '2024-01-01' AS gap\")")
    out = ex.query(QuerySpec(dataset="rel"))
    assert out.rows == [{"gap": "1 day"}]
    meta = ex.snapshot("rel", tmp_path / "rel.parquet")
    assert meta.rows == 1
    assert pl.read_parquet(tmp_path / "rel.parquet")["gap"].to_list() == ["1 day"]


def test_query_arrow_format() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    out = ex.query(QuerySpec(dataset="df", format="arrow"))
    assert out.rows is None
    assert out.arrow_base64 is not None
    decoded = pl.read_ipc(io.BytesIO(base64.b64decode(out.arrow_base64)))
    assert decoded["a"].to_list() == [1]


def test_query_unknown_column_raises_query_error() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    with pytest.raises(QueryError):
        ex.query(QuerySpec(dataset="df", filters=[Filter(col="zz", op="eq", value=1)]))


def test_query_result_serializes_schema_under_its_alias() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    dumped = ex.query(QuerySpec(dataset="df")).model_dump(by_alias=True, mode="json")
    assert dumped["schema"] == [{"name": "a", "dtype": "Int64"}]


def test_snapshot_writes_parquet(tmp_path: Path) -> None:
    ex = make()
    ex.execute("lf = pl.DataFrame({'a': [1, 2]}).lazy()")
    meta = ex.snapshot("lf", tmp_path / "lf.parquet")
    assert meta.rows == 2
    assert pl.read_parquet(tmp_path / "lf.parquet")["a"].to_list() == [1, 2]
