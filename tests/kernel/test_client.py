import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import polars as pl
import pytest

from quarry.config import ENV_API_KEY
from quarry.kernel.client import KernelClient, KernelDead, RpcFailure
from quarry.kernel.executor import ExecResult
from quarry.query import QuerySpec
from tests.kernel.fixtures import BUSY_LOOP, HEAVY

# Streams 3M rows from the default DuckDB connection; a query on that connection mid-stream
# used to end the stream early without an error.
STREAM_STEP = (
    "import time\n"
    "res = duckdb.sql('select range as a from range(3000000)')\n"
    "streamed = 0\n"
    "while batch := res.fetchmany(1000):\n"
    "    streamed += len(batch)\n"
    "    time.sleep(0.0005)\n"
    "print(streamed)\n"
)

StandIn = Callable[[float], tuple[KernelClient, socket.socket]]


@pytest.fixture
def kernel(tmp_path: Path) -> Iterator[KernelClient]:
    client = KernelClient.spawn(tmp_path)
    yield client
    client.close()


@pytest.fixture
def stand_in() -> Iterator[StandIn]:
    """Makes clients whose "kernel" sleeps `lifetime` seconds and whose socket peer the test
    drives."""
    made: list[tuple[KernelClient, socket.socket]] = []

    def make(lifetime: float) -> tuple[KernelClient, socket.socket]:
        process = subprocess.Popen([sys.executable, "-c", f"import time; time.sleep({lifetime})"])
        client_end, peer = socket.socketpair()
        made.append((KernelClient(process, client_end, tempfile.TemporaryDirectory()), peer))
        return made[-1]

    yield make
    for client, peer in made:
        client.close()
        peer.close()


def run_in_thread(kernel: KernelClient, code: str) -> tuple[threading.Thread, list[ExecResult]]:
    """Execute `code` on a thread; the list receives its result."""
    results: list[ExecResult] = []
    thread = threading.Thread(target=lambda: results.append(kernel.execute(code)))
    thread.start()
    return thread, results


def interrupt_running_step(kernel: KernelClient) -> None:
    """Interrupt until the signal reaches the step: one sent before it starts is dropped."""
    deadline = time.monotonic() + 10
    while not kernel.interrupt():
        assert time.monotonic() < deadline, "the step never started"
        time.sleep(0.05)


def test_execute_round_trip(kernel: KernelClient) -> None:
    result = kernel.execute("df = pl.DataFrame({'a': [1, 2, 3]})")
    assert result.status == "ok"
    assert result.writes == ["df"]
    assert kernel.describe("df").rows == 3
    assert [m.name for m in kernel.list_datasets()] == ["df"]


def test_query_round_trip(kernel: KernelClient) -> None:
    kernel.execute("df = pl.DataFrame({'a': [3, 1, 2]})")
    out = kernel.query(QuerySpec(dataset="df", sort=[{"col": "a"}], limit=2))
    assert out.rows == [{"a": 1}, {"a": 2}]


def test_snapshot_round_trip(kernel: KernelClient, tmp_path: Path) -> None:
    kernel.execute("df = pl.DataFrame({'a': [1]})")
    kernel.snapshot("df", tmp_path / "out.parquet")
    assert pl.read_parquet(tmp_path / "out.parquet")["a"].to_list() == [1]


def test_error_response_raises_rpc_failure(kernel: KernelClient) -> None:
    with pytest.raises(RpcFailure) as info:
        kernel.describe("missing")
    assert info.value.type == "KeyError"


@pytest.mark.parametrize(
    "step", [BUSY_LOOP, f"n = duckdb.sql({HEAVY!r}).fetchall()"], ids=["busy_loop", "duckdb"]
)
def test_interrupt_running_step(kernel: KernelClient, step: str) -> None:
    thread, results = run_in_thread(kernel, step)
    # Well into the step: an interrupt sent as a query starts reaches Python, not DuckDB.
    time.sleep(0.5)
    interrupt_running_step(kernel)
    thread.join(timeout=10)
    assert not thread.is_alive()
    assert (results[0].status, results[0].error) == ("interrupted", None)
    assert kernel.execute("x = 1").status == "ok"


def test_kernel_spills_into_the_client_temp_directory(kernel: KernelClient) -> None:
    step = "print(duckdb.sql(\"SELECT current_setting('temp_directory')\").fetchone()[0])"
    spill = Path(kernel.execute(step).stdout_tail.strip())
    temp_dir = Path(kernel._tmpdir.name)
    assert spill.parent == temp_dir
    assert stat.S_IMODE(temp_dir.stat().st_mode) == 0o700


def test_kernel_environment_lacks_provider_api_keys(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    keys = set(ENV_API_KEY.values())
    for name in keys:
        monkeypatch.setenv(name, "secret")
    monkeypatch.setenv("QUARRY_TEST_PASSED_ON", "kept")
    step = (
        f"import os\nprint(sorted(os.environ.keys() & {keys!r}), "
        "os.environ['QUARRY_TEST_PASSED_ON'])"
    )
    client = KernelClient.spawn(tmp_path)
    try:
        result = client.execute(step)
    finally:
        client.close()
    assert result.stdout_tail == "[] kept\n"


def test_interrupt_while_idle_is_ignored(kernel: KernelClient) -> None:
    assert kernel.interrupt() is False
    assert kernel.execute("x = 1").status == "ok"
    assert kernel.is_alive()


def test_namespace_requests_wait_for_the_running_step(kernel: KernelClient) -> None:
    kernel.execute("df = pl.DataFrame({'a': [1]})")
    step = "import time\ntime.sleep(1)\ndf = pl.DataFrame({'a': [1, 2]})\nnew = df\n"
    thread, results = run_in_thread(kernel, step)
    time.sleep(0.2)
    started = time.monotonic()
    names = [m.name for m in kernel.list_datasets()]
    waited = time.monotonic() - started
    rows = kernel.query(QuerySpec(dataset="df")).rows
    thread.join(timeout=10)
    assert results[0].status == "ok"
    assert names == ["df", "new"]
    assert rows == [{"a": 1}, {"a": 2}]
    assert waited > 0.5


def test_concurrent_query_does_not_cut_a_streaming_step_short(kernel: KernelClient) -> None:
    kernel.execute("small = duckdb.sql('select 1 as a')")
    thread, results = run_in_thread(kernel, STREAM_STEP)
    time.sleep(0.2)
    rows = [kernel.query(QuerySpec(dataset="small")).rows for _ in range(5)]
    thread.join(timeout=30)
    assert results[0].status == "ok"
    assert results[0].stdout_tail == "3000000\n"
    assert rows == [[{"a": 1}]] * 5


def test_kernel_crash_is_detected(kernel: KernelClient) -> None:
    with pytest.raises(KernelDead):
        kernel.execute("import os\nos._exit(3)\n")
    assert not kernel.is_alive()
    with pytest.raises(KernelDead):
        kernel.execute("x = 1")


def test_shutdown(kernel: KernelClient) -> None:
    kernel.shutdown()
    deadline = time.monotonic() + 5
    while kernel.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not kernel.is_alive()


def test_calls_after_shutdown_raise_kernel_dead(kernel: KernelClient) -> None:
    kernel.shutdown()
    started = time.monotonic()
    with pytest.raises(KernelDead):
        kernel.execute("x = 1")
    assert time.monotonic() - started < 0.5


def test_kernel_runs_in_its_own_session(kernel: KernelClient) -> None:
    # A terminal Ctrl-C reaches the server's process group, never a kernel in a new session.
    result = kernel.execute("import os\nprint(os.getsid(0) == os.getpid())")
    assert result.stdout_tail == "True\n"


def test_printing_a_lone_surrogate_keeps_the_kernel(kernel: KernelClient) -> None:
    result = kernel.execute("print('\\udcff')")
    assert result.status == "ok"
    assert result.stdout_tail == "?\n"
    assert kernel.is_alive()


def test_spawn_reports_a_kernel_that_exits_before_connecting(tmp_path: Path) -> None:
    (tmp_path / "config.toml").write_text('[data]\nrow_cap = "lots"\n')
    started = time.monotonic()
    with pytest.raises(KernelDead, match="exited with code 1"):
        KernelClient.spawn(tmp_path)
    assert time.monotonic() - started < 10


def test_undecodable_response_marks_kernel_dead(stand_in: StandIn) -> None:
    client, peer = stand_in(60)  # outlives the test, so only the garbage can end the call

    def answer_with_garbage() -> None:
        peer.recv(65536)
        peer.sendall(b"not a response\n")

    threading.Thread(target=answer_with_garbage).start()
    with pytest.raises(KernelDead, match="undecodable response"):
        client.list_datasets()
    assert not client.is_alive()


def test_call_fails_when_kernel_exits_with_its_socket_still_open(stand_in: StandIn) -> None:
    client, _ = stand_in(1)  # the peer stays open, as when a forked child inherited the socket
    started = time.monotonic()
    with pytest.raises(KernelDead, match="exited"):
        client.list_datasets()
    assert time.monotonic() - started < 5
