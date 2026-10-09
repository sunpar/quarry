import base64
import io
import signal
import threading
import time
from collections.abc import Callable, Iterator
from decimal import Decimal
from pathlib import Path

import duckdb
import polars as pl
import pytest
from polars.exceptions import ColumnNotFoundError

from quarry.kernel import datasets
from quarry.kernel import executor as executor_module
from quarry.kernel.datasets import Dataset, DatasetMeta
from quarry.kernel.executor import Executor, _identity_check, _TailWriter
from quarry.query import Agg, Backing, Filter, Json, Pivot, QueryError, QuerySpec, Sort
from quarry.query.sql_target import relation_view
from tests.kernel.fixtures import BUSY_LOOP, HEAVY

PIVOT_ROWS = (
    "SELECT * FROM (VALUES ('a', 'x', 1), ('a', 'y', 2), ('b', 'x', 3), ('b', 'y', 40)) t(k, c, v)"
)
BAD_PLAN = "lf = pl.DataFrame({'a': [1]}).lazy().filter(pl.col('nope') > 1)"
RELATION_SQL = "SELECT * FROM (VALUES (1, 'x'), (2, 'y')) t(n, s)"
RELATION_STEP = f"rel = _conn.sql({RELATION_SQL!r})"
# Specs whose answer depends on row order, and that answer over PIVOT_ROWS in its order.
ORDERED_SPECS: list[tuple[QuerySpec, str, list[dict[str, Json]]]] = [
    (
        QuerySpec(
            dataset="t", group_by=["k"], aggs=[Agg(col="v", fn="first")], sort=[Sort(col="k")]
        ),
        "first",
        [{"k": "a", "v_first": 1}, {"k": "b", "v_first": 3}],
    ),
    (
        QuerySpec(
            dataset="t",
            group_by=["k"],
            aggs=[Agg(col="v", fn="sum"), Agg(col="v", fn="last")],
            sort=[Sort(col="k")],
        ),
        "last",
        # An integer sum is a Decimal(38, 0), which JSON carries as an exact string.
        [{"k": "a", "v_sum": "3", "v_last": 2}, {"k": "b", "v_sum": "43", "v_last": 40}],
    ),
    (
        QuerySpec(
            dataset="t",
            pivot=Pivot(index=["k"], columns="c", values="v", agg="first"),
            sort=[Sort(col="k")],
        ),
        "first",
        [{"k": "a", "x": 1, "y": 2}, {"k": "b", "x": 3, "y": 40}],
    ),
]
ORDERED_IDS = ["first", "last", "pivot_first"]
SNAPSHOT_SOURCES = [
    ("polars", "src = pl.DataFrame({'a': [1, 2], 's': ['x', None]})"),
    ("polars_lazy", "src = pl.DataFrame({'a': [1, 2], 's': ['x', None]}).lazy()"),
    ("duckdb", "src = _conn.sql(\"SELECT * FROM (VALUES (1, 'x'), (2, NULL)) t(a, s)\")"),
]


def make(conn: duckdb.DuckDBPyConnection | None = None) -> Executor:
    conn = duckdb.connect() if conn is None else conn
    return Executor({"pl": pl, "duckdb": duckdb, "_conn": conn}, conn=conn, row_cap=3)


@pytest.fixture
def interruptible() -> Iterator[Callable[[int], Executor]]:
    """Makes an executor on a private connection running `threads` threads, under the
    kernel's SIGINT handler as `serve` installs it."""
    previous = signal.getsignal(signal.SIGINT)

    def install(threads: int) -> Executor:
        conn = duckdb.connect()
        conn.execute(f"SET threads = {threads}")
        ex = make(conn)
        signal.signal(signal.SIGINT, ex.on_sigint)
        return ex

    yield install
    signal.signal(signal.SIGINT, previous)


def interrupt_soon(ex: Executor) -> threading.Thread:
    """Signal the main thread, as the kernel's reader does, 0.2 s into `ex`'s running step."""
    main = threading.main_thread().ident
    assert main is not None and threading.current_thread() is threading.main_thread()

    def send() -> None:
        deadline = time.monotonic() + 10
        while not ex.running and time.monotonic() < deadline:
            time.sleep(0.005)
        time.sleep(0.2)
        signal.pthread_kill(main, signal.SIGINT)

    thread = threading.Thread(target=send)
    thread.start()
    return thread


@pytest.fixture
def described(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """The names the executor describes, in order, appended to as it does."""
    names: list[str] = []
    real = datasets.describe

    def counting(name: str, obj: Dataset, *, count_rows: bool) -> DatasetMeta:
        names.append(name)
        return real(name, obj, count_rows=count_rows)

    monkeypatch.setattr(executor_module, "describe_dataset", counting)
    return names


def quarry_views(conn: duckdb.DuckDBPyConnection, dataset: str) -> list[tuple[str]]:
    """The views queries on `dataset` registered (`_quarry_<dataset>_<hex>`) still on `conn`."""
    sql = "SELECT view_name FROM duckdb_views() WHERE starts_with(view_name, ?)"
    return conn.execute(sql, [f"{relation_view(dataset)}_"]).fetchall()


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


def test_execute_tails_are_exactly_the_last_tail_bytes_characters() -> None:
    ex = Executor({}, conn=duckdb.connect(), row_cap=3, tail_bytes=100)
    result = ex.execute(
        "import sys\nfor i in range(5000):\n    print(i)\n    print(-i, file=sys.stderr)\n"
    )
    assert result.stdout_tail == "".join(f"{i}\n" for i in range(5000))[-100:]
    assert result.stderr_tail == "".join(f"{-i}\n" for i in range(5000))[-100:]


def test_tail_writer_holds_at_most_twice_its_limit_while_written() -> None:
    writer = _TailWriter(100)
    written = ""
    for chunk in [*(f"{i}," * (i % 7) for i in range(5000)), "", "y" * 1000, "z"]:
        writer.write(chunk)
        written += chunk
        assert sum(map(len, writer._chunks)) <= 200
        assert writer.getvalue() == written[-100:]


def test_execute_with_tail_bytes_zero_keeps_nothing() -> None:
    ex = Executor({}, conn=duckdb.connect(), row_cap=3, tail_bytes=0)
    result = ex.execute("import sys\nprint('out')\nprint('err', file=sys.stderr)\n")
    assert (result.status, result.stdout_tail, result.stderr_tail) == ("ok", "", "")


def test_except_alias_shadowing_a_dataset_is_not_a_read() -> None:
    ex = make()
    ex.execute("e = pl.DataFrame({'a': [1]})")
    result = ex.execute("try:\n    1 / 0\nexcept Exception as e:\n    print(e)\n")
    assert (result.status, result.stdout_tail) == ("ok", "division by zero\n")
    assert result.reads == []
    # Python deletes the alias when the handler ends, which unbinds the dataset; like a `del`,
    # that is not a write.
    assert (result.writes, result.datasets) == ([], [])
    assert ex.list_datasets() == []


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


def test_stopped_executor_interrupts_a_step_before_it_runs() -> None:
    namespace: dict[str, object] = {}
    ex = Executor(namespace, conn=duckdb.connect(), row_cap=3)
    ex.stop()
    result = ex.execute("print('ran')\nx = 1")
    assert (result.status, result.error, result.stdout_tail) == ("interrupted", None, "")
    assert "x" not in namespace


def test_executor_stopped_during_a_step_leaves_its_writes_undescribed() -> None:
    namespace: dict[str, object] = {"pl": pl}
    ex = Executor(namespace, conn=duckdb.connect(), row_cap=3)
    namespace["stop"] = ex.stop
    result = ex.execute("stop()\ndf = pl.DataFrame({'a': [1]})")
    assert (result.status, result.error, result.writes) == ("interrupted", None, ["df"])
    assert [(m.name, m.error, m.schema_) for m in result.datasets] == [("df", "interrupted", [])]
    assert ex.running is False


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


def test_helper_rebound_to_a_value_is_not_read_later() -> None:
    ex = make()
    ex.execute("def scale(x):\n    return x * 2\n")
    ex.execute("df = pl.DataFrame({'a': [1]})")
    ex.execute("scale = 3")
    assert ex.execute("ds = df.select(pl.lit(scale))").reads == ["df"]


def test_deleted_helper_is_forgotten() -> None:
    ex = make()
    ex.execute("def scale(x):\n    return x * 2\n")
    ex.execute("df = pl.DataFrame({'a': [1]})")
    assert ex.execute("del scale").status == "ok"
    # Rebound in the step that reads it, so only the `del` can have forgotten the helper.
    assert ex.execute("scale = 3\nds = df.select(pl.lit(scale))").reads == ["df"]


def test_live_helper_stays_a_read_in_later_steps() -> None:
    ex = make()
    ex.execute("def scale(x):\n    return x * 2\n")
    ex.execute("df = pl.DataFrame({'a': [1]})")
    ex.execute("other = 1")
    assert ex.execute("ds = df.select(pl.lit(scale(2)))").reads == ["df", "scale"]
    assert ex.execute("again = scale(3)").reads == ["scale"]


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


def test_failed_step_does_not_define_a_helper_that_already_existed() -> None:
    # In the namespace without a step defining it, as the kernel's loaders are.
    ex = Executor({"helper": lambda: 1}, conn=duckdb.connect(), row_cap=3)
    failed = ex.execute("raise RuntimeError\ndef helper():\n    return 2\n")
    assert failed.status == "error"
    assert failed.defines == []
    assert "helper" not in ex._defined


def test_redefining_a_helper_is_a_define() -> None:
    ex = make()
    ex.execute("def helper():\n    return 1\n")
    result = ex.execute("def helper():\n    return 2\n")
    assert result.defines == ["helper"]


def test_def_that_never_runs_does_not_define_an_existing_name() -> None:
    ex = make()
    ex.execute("def f():\n    return 1\n")
    result = ex.execute("if False:\n    def f():\n        return 2\n")
    assert result.status == "ok"
    assert result.defines == []


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
    assert meta.error.startswith("ColumnNotFoundError: ")


def test_list_datasets_reports_an_undescribable_dataset_with_its_error() -> None:
    ex = make()
    ex.execute("good = pl.DataFrame({'a': [1]})")
    ex.execute(BAD_PLAN)
    good, bad = ex.list_datasets()
    assert (good.name, good.error, good.rows) == ("good", None, 1)
    assert bad.name == "lf"
    assert bad.error is not None
    assert bad.error.startswith("ColumnNotFoundError: ")
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


def test_object_whose_class_attribute_raises_does_not_break_later_steps() -> None:
    ex = make()
    proxy = "class Proxy:\n    @property\n    def __class__(self):\n        raise RuntimeError\n"
    assert ex.execute(proxy + "p = Proxy()").status == "ok"
    assert ex.execute("x = 1").status == "ok"
    assert ex.execute("del p").status == "ok"


def test_underscore_names_are_datasets_with_lineage() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1, 2]})")
    first = ex.execute("_tmp = df.filter(pl.col('a') > 1)")
    assert first.writes == ["_tmp"]
    second = ex.execute("out = _tmp.head(1)")
    assert second.reads == ["_tmp"]
    assert ex.describe("_tmp").rows == 1
    assert [m.name for m in ex.list_datasets()] == ["_tmp", "df", "out"]


def test_running_is_true_only_while_user_code_runs() -> None:
    namespace: dict[str, object] = {"pl": pl}
    ex = Executor(namespace, conn=duckdb.connect(), row_cap=3)
    namespace["_ex"] = ex
    assert ex.running is False
    result = ex.execute("seen = _ex.running")
    assert result.status == "ok"
    assert namespace["seen"] is True
    assert ex.running is False


@pytest.mark.parametrize(
    ("code", "printed"),
    [
        (
            "try:\n"
            f"    _conn.sql({HEAVY!r}).fetchall()\n"
            "except BaseException as exc:\n"
            "    print(type(exc).__name__)\n"
            "    raise\n",
            "RuntimeError\n",  # DuckDB's "Query interrupted"
        ),
        (
            "import time\n"
            "try:\n"
            "    for _ in range(1000):\n"
            "        time.sleep(0.01)\n"
            "except KeyboardInterrupt:\n"
            "    print('caught')\n",
            "caught\n",
        ),
    ],
    ids=["duckdb_raises_its_own_error", "step_catches_it_and_finishes"],
)
def test_interrupted_step_is_interrupted_whatever_follows(
    interruptible: Callable[[int], Executor], code: str, printed: str
) -> None:
    ex = interruptible(1)
    sender = interrupt_soon(ex)
    result = ex.execute(code)
    sender.join()
    assert result.stdout_tail == printed
    assert (result.status, result.error) == ("interrupted", None)


def test_interrupt_stops_the_connection_workers(
    interruptible: Callable[[int], Executor],
) -> None:
    ex = interruptible(4)  # workers to run HEAVY's branches on
    sender = interrupt_soon(ex)
    result = ex.execute(f"_conn.sql({HEAVY!r}).pl()")
    sender.join()
    started = time.monotonic()
    assert ex.execute("print(_conn.sql('SELECT 1').fetchall())").stdout_tail == "[(1,)]\n"
    waited = time.monotonic() - started
    assert (result.status, result.error) == ("interrupted", None)
    # Far below what the workers' tasks have left, which only grows on a slower machine.
    assert waited < 1.0


def test_interrupt_with_no_query_running_leaves_the_next_query_working(
    interruptible: Callable[[int], Executor],
) -> None:
    ex = interruptible(4)
    sender = interrupt_soon(ex)
    result = ex.execute(BUSY_LOOP)
    sender.join()
    assert result.status == "interrupted"
    assert ex.execute("print(_conn.sql('SELECT 42').fetchall())").stdout_tail == "[(42,)]\n"


def test_interrupt_while_describing_writes_leaves_them_undescribed(
    interruptible: Callable[[int], Executor],
) -> None:
    ex = interruptible(1)
    sender = interrupt_soon(ex)
    result = ex.execute(f"heavy = _conn.sql({HEAVY!r})\nlight = pl.DataFrame({{'a': [1]}})")
    sender.join()
    assert (result.status, result.error) == ("interrupted", None)
    assert result.writes == ["heavy", "light"]
    metas = [(m.name, m.backing, m.error, m.schema_, m.rows) for m in result.datasets]
    assert metas == [
        ("heavy", "duckdb", "interrupted", [], None),
        ("light", "polars", "interrupted", [], None),
    ]
    assert ex.running is False
    assert ex.execute("x = 1").status == "ok"


def test_list_datasets_reuses_the_metadata_execute_computed(described: list[str]) -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1, 2]})")
    assert described == ["df"]
    first, second = ex.list_datasets(), ex.list_datasets()
    assert described == ["df"]
    assert [m.preview for m in first] == [[{"a": 1}, {"a": 2}]] == [m.preview for m in second]


def test_list_datasets_describes_a_dataset_once(described: list[str]) -> None:
    namespace: dict[str, object] = {"b": pl.DataFrame({"a": [1]}), "a": pl.DataFrame({"a": [2]})}
    ex = Executor(namespace, conn=duckdb.connect(), row_cap=3)
    assert [m.name for m in ex.list_datasets()] == ["a", "b"]
    assert [m.name for m in ex.list_datasets()] == ["a", "b"]
    assert described == ["a", "b"]


def test_step_that_rebinds_a_dataset_refreshes_its_metadata(described: list[str]) -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    ex.execute("df = pl.DataFrame({'a': [1, 2]})")
    (meta,) = ex.list_datasets()
    assert (meta.rows, meta.preview) == (2, [{"a": 1}, {"a": 2}])
    assert described == ["df", "df"]


@pytest.mark.parametrize("ending", ["", "\nraise ValueError", "\nraise KeyboardInterrupt"])
def test_step_that_changes_a_dataset_in_place_refreshes_it_whatever_its_status(
    ending: str, described: list[str]
) -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    ex.list_datasets()
    ex.execute(f"df.extend(pl.DataFrame({{'a': [2]}})){ending}")
    assert described == ["df"]  # nothing was rebound, so nothing was described
    (meta,) = ex.list_datasets()
    assert (meta.rows, meta.preview) == (2, [{"a": 1}, {"a": 2}])
    ex.list_datasets()
    assert described == ["df", "df"]


def test_step_that_changes_a_dataset_through_a_helper_refreshes_it() -> None:
    ex = make()
    ex.execute(
        "df = pl.DataFrame({'a': [1]})\ndef grow():\n    df.extend(pl.DataFrame({'a': [2]}))"
    )
    ex.list_datasets()
    ex.execute("grow()")  # reads the helper, not df
    assert [m.rows for m in ex.list_datasets()] == [2]


def test_any_step_refreshes_the_datasets_it_did_not_write(described: list[str]) -> None:
    ex = make()
    ex.execute("a = pl.DataFrame({'a': [1]})")
    ex.execute("b = pl.DataFrame({'b': [1]})")
    ex.execute("x = 1")
    assert [m.name for m in ex.list_datasets()] == ["a", "b"]
    assert described == ["a", "b", "a", "b"]
    ex.execute("c = pl.DataFrame({'c': [1]})")  # c is current; a and b are not
    assert [m.name for m in ex.list_datasets()] == ["a", "b", "c"]
    assert described == ["a", "b", "a", "b", "c", "a", "b"]


def test_interrupted_write_is_described_by_the_next_list(described: list[str]) -> None:
    namespace: dict[str, object] = {"pl": pl}
    ex = Executor(namespace, conn=duckdb.connect(), row_cap=3)
    namespace["stop"] = ex.stop
    result = ex.execute("stop()\ndf = pl.DataFrame({'a': [1]})")
    assert [m.error for m in result.datasets] == ["interrupted"]
    assert described == []
    (meta,) = ex.list_datasets()
    assert (meta.error, meta.rows) == (None, 1)
    assert described == ["df"]


def test_undescribable_dataset_is_described_on_every_list(described: list[str]) -> None:
    ex = make()
    ex.execute(BAD_PLAN)
    ex.list_datasets()
    ex.list_datasets()
    assert described == ["lf", "lf", "lf"]


def test_deleted_dataset_leaves_the_list() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})\nkept = pl.DataFrame({'a': [2]})")
    assert [m.name for m in ex.list_datasets()] == ["df", "kept"]
    ex.execute("del df")
    assert [m.name for m in ex.list_datasets()] == ["kept"]


def test_describe_counts_rows_and_leaves_the_listed_metadata_alone(described: list[str]) -> None:
    ex = make()
    ex.execute("lf = pl.DataFrame({'a': [1, 2, 3]}).lazy()")
    assert [m.rows for m in ex.list_datasets()] == [None]
    assert ex.describe("lf").rows == 3
    assert [m.rows for m in ex.list_datasets()] == [None]
    assert described == ["lf", "lf"]


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
    ex.execute(RELATION_STEP)
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
    # The pivot runs in polars, whose integer sums are Decimal(38, 0) like DuckDB's.
    assert out.rows == [{"k": "a", "x": "1", "y": "2"}, {"k": "b", "x": "3", "y": None}]
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


@pytest.mark.parametrize(
    ("spec", "fn"), [(spec, fn) for spec, fn, _ in ORDERED_SPECS], ids=ORDERED_IDS
)
def test_query_rejects_first_and_last_on_a_relation(spec: QuerySpec, fn: str) -> None:
    ex = make()
    ex.execute(f't = _conn.sql("{PIVOT_ROWS}")')
    with pytest.raises(
        QueryError, match=rf"^'{fn}' needs a row order.*'min' or 'max'.*\.pl\(\)"
    ) as info:
        ex.query(spec)
    assert (info.value.dataset, info.value.column) == ("t", None)


@pytest.mark.parametrize("convert", [".pl()", ".pl().lazy()"])
@pytest.mark.parametrize(
    ("spec", "rows"), [(spec, rows) for spec, _, rows in ORDERED_SPECS], ids=ORDERED_IDS
)
def test_query_runs_first_and_last_on_polars(
    spec: QuerySpec, rows: list[dict[str, Json]], convert: str
) -> None:
    ex = make()
    ex.execute(f't = _conn.sql("{PIVOT_ROWS}"){convert}')
    assert ex.query(spec).rows == rows


def test_query_drops_its_view_of_a_relation() -> None:
    conn = duckdb.connect()
    ex = make(conn)
    ex.execute(RELATION_STEP)
    assert ex.query(QuerySpec(dataset="rel", filters=[Filter(col="n", op="eq", value=2)])).rows
    assert quarry_views(conn, "rel") == []


def test_query_drops_its_view_of_a_relation_from_another_connection() -> None:
    other = duckdb.connect()
    ex = Executor({"rel": other.sql(RELATION_SQL)}, conn=duckdb.connect(), row_cap=3)
    assert ex.query(QuerySpec(dataset="rel")).rows
    assert quarry_views(other, "rel") == []


@pytest.mark.parametrize("kind", ["TEMP VIEW", "TEMP TABLE"])
def test_query_keeps_the_researchers_object_named_like_its_view(kind: str) -> None:
    conn = duckdb.connect()
    ex = make(conn)
    name = relation_view("rel")
    ex.execute(f"_conn.execute('CREATE {kind} {name} AS SELECT 42 AS answer')\n{RELATION_STEP}")
    definition = (
        "SELECT sql FROM duckdb_views() WHERE view_name = $name"
        " UNION ALL SELECT sql FROM duckdb_tables() WHERE table_name = $name"
    )
    before = conn.execute(definition, {"name": name}).fetchall()
    assert ex.query(QuerySpec(dataset="rel")).rows == [{"n": 1, "s": "x"}, {"n": 2, "s": "y"}]
    assert conn.execute(definition, {"name": name}).fetchall() == before
    assert conn.execute(f"SELECT answer FROM {name}").fetchall() == [(42,)]


def test_failing_query_drops_its_view_of_a_relation() -> None:
    conn = duckdb.connect()
    ex = make(conn)
    ex.execute(RELATION_STEP)
    with pytest.raises(duckdb.ConversionException):
        ex.query(QuerySpec(dataset="rel", filters=[Filter(col="n", op="eq", value="two")]))
    assert quarry_views(conn, "rel") == []


def test_relation_with_repeated_names_queries_under_the_names_describe_gives(
    tmp_path: Path,
) -> None:
    ex = make()
    ex.execute("rel = _conn.sql('SELECT 1 AS a, 2 AS a UNION ALL SELECT 3, 4')")
    assert [c.name for c in ex.describe("rel").schema_] == ["a", "a_1"]
    second = QuerySpec(dataset="rel", select=["a_1"], sort=[Sort(col="a_1")])
    assert ex.query(second).rows == [{"a_1": 2}, {"a_1": 4}]
    filtered = QuerySpec(dataset="rel", filters=[Filter(col="a_1", op="gt", value=3)])
    assert ex.query(filtered).rows == [{"a": 3, "a_1": 4}]
    meta = ex.snapshot("rel", tmp_path / "rel.parquet")
    assert [c.name for c in meta.schema_] == ["a", "a_1"]


def test_relation_with_interval_column_queries_and_snapshots(tmp_path: Path) -> None:
    ex = make()
    ex.execute("rel = _conn.sql(\"SELECT TIMESTAMP '2024-01-02' - TIMESTAMP '2024-01-01' AS gap\")")
    out = ex.query(QuerySpec(dataset="rel"))
    assert out.rows == [{"gap": "1 day"}]
    meta = ex.snapshot("rel", tmp_path / "rel.parquet")
    assert meta.rows == 1
    assert pl.read_parquet(tmp_path / "rel.parquet")["gap"].to_list() == ["1 day"]


def test_relation_query_filters_an_interval_column_as_the_text_describe_gives() -> None:
    ex = make()
    sql = "SELECT * FROM (VALUES (INTERVAL 1 DAY, 1), (INTERVAL 2 HOUR, 2)) t(gap, k)"
    ex.execute(f"rel = _conn.sql({sql!r})")
    assert [c.dtype for c in ex.describe("rel").schema_] == ["String", "Int32"]
    spec = QuerySpec(dataset="rel", filters=[Filter(col="gap", op="contains", value="day")])
    assert ex.query(spec).rows == [{"gap": "1 day", "k": 1}]


def test_query_arrow_format() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    out = ex.query(QuerySpec(dataset="df", format="arrow"))
    assert out.rows is None
    assert out.arrow_base64 is not None
    decoded = pl.read_ipc(io.BytesIO(base64.b64decode(out.arrow_base64)))
    assert decoded["a"].to_list() == [1]


def test_query_json_rows_null_non_finite_floats_and_arrow_keeps_them() -> None:
    ex = make()
    ex.execute(
        "f = pl.DataFrame({'x': [float('inf'), float('-inf'), float('nan')]}).with_columns("
        "x32=pl.col('x').cast(pl.Float32), xs=pl.concat_list('x'), st=pl.struct('x'))"
    )
    rows = ex.query(QuerySpec(dataset="f")).rows
    assert rows == [{"x": None, "x32": None, "xs": [None], "st": {"x": None}}] * 3
    arrow = ex.query(QuerySpec(dataset="f", format="arrow")).arrow_base64
    assert arrow is not None
    decoded = pl.read_ipc(io.BytesIO(base64.b64decode(arrow)))
    assert repr(decoded.rows()) == repr(
        [(v, v, [v], {"x": v}) for v in (float("inf"), float("-inf"), float("nan"))]
    )


def test_query_duckdb_bigint_sum_is_an_exact_decimal_string() -> None:
    ex = make()
    ex.execute('rel = _conn.sql("SELECT range + 9007199254740992 AS n, 1 AS k FROM range(2)")')
    out = ex.query(QuerySpec(dataset="rel", group_by=["k"], aggs=[Agg(col="n", fn="sum")]))
    assert [c.dtype for c in out.schema_] == ["Int32", "Decimal(precision=38, scale=0)"]
    assert out.rows == [{"k": 1, "n_sum": "18014398509481985"}]


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


@pytest.mark.parametrize(("backing", "step"), SNAPSHOT_SOURCES)
def test_snapshot_round_trips_each_backing(backing: Backing, step: str, tmp_path: Path) -> None:
    ex = make()
    ex.execute(step)
    path = tmp_path / "snapshots" / "prices[2024].parquet"  # one file, though it reads as a glob
    meta = ex.snapshot("src", path)
    rows = [{"a": 1, "s": "x"}, {"a": 2, "s": None}]
    assert pl.read_parquet(path, glob=False).sort("a").to_dicts() == rows
    assert (meta.name, meta.backing, meta.rows) == ("src", backing, 2)
    assert [c.name for c in meta.schema_] == ["a", "s"]
    assert list(path.parent.iterdir()) == [path]


def test_relation_snapshot_keeps_the_types_describe_reports(tmp_path: Path) -> None:
    ex = make()
    ex.execute(
        "rel = _conn.sql(\"SELECT sum(x) AS big, uuid '12345678-1234-5678-1234-567812345678' AS u"
        ' FROM (VALUES (9007199254740993::BIGINT), (0::BIGINT)) t(x)")'
    )
    meta = ex.snapshot("rel", tmp_path / "rel.parquet")
    back = pl.read_parquet(tmp_path / "rel.parquet")
    assert back.schema == {"big": pl.Decimal(38, 0), "u": pl.String}
    assert back.row(0) == (Decimal("9007199254740993"), "12345678-1234-5678-1234-567812345678")
    assert meta.schema_ == ex.describe("rel").schema_


def test_failed_snapshot_leaves_no_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    def write_then_fail(self: pl.DataFrame, file: str | Path) -> None:
        Path(file).write_bytes(b"PAR1")  # the partial file a full disk leaves behind
        raise OSError("No space left on device")

    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    monkeypatch.setattr(pl.DataFrame, "write_parquet", write_then_fail)
    with pytest.raises(OSError, match="No space left"):
        ex.snapshot("df", tmp_path / "df.parquet")
    assert list(tmp_path.iterdir()) == []
