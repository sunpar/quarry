import errno
import json
import math
import os
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

import quarry.kernel.client as client_module
from quarry.config import ENV_API_KEY, ENV_MSSQL_DSN
from quarry.kernel.client import KernelClient, KernelDead, RpcFailure, _accept
from quarry.kernel.executor import ExecResult
from quarry.kernel.protocol import Response, encode, read_lines
from quarry.query import Filter, QuerySpec
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
# Starts a child that runs on after the step unless something kills it.
CHILD_STEP = "import subprocess\nchild = subprocess.Popen(['sleep', '60'])\nprint(child.pid)\n"

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
        # Its own session, as `spawn` starts the kernel: `close` kills the group it leads.
        process = subprocess.Popen(
            [sys.executable, "-c", f"import time; time.sleep({lifetime})"], start_new_session=True
        )
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


def exits_soon(pid: int) -> bool:
    """Whether process `pid` ends within 5 seconds. A zombie counts as ended: a killed child of
    a dead kernel waits for init to reap it, and a container's init may never do so."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True
        ps = subprocess.run(["ps", "-o", "stat=", "-p", str(pid)], capture_output=True, text=True)
        if ps.stdout.strip().startswith("Z"):
            return True
        time.sleep(0.05)
    return False


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


def test_to_code_round_trip(kernel: KernelClient) -> None:
    kernel.execute("df = pl.DataFrame({'a': [3, 1, 2]})")
    code = kernel.to_code([QuerySpec(dataset="df", sort=[{"col": "a"}])])
    assert "df_1 = (" in code and "df.lazy()" in code


def test_query_cannot_carry_a_non_finite_filter_value(kernel: KernelClient) -> None:
    # JSON has no NaN: the request would carry null, and `between` reads a null bound as no row.
    kernel.execute("df = pl.DataFrame({'a': [1.0, 2.0]})")
    with pytest.raises(ValidationError, match="finite"):
        kernel.query(
            QuerySpec(dataset="df", filters=[Filter(col="a", op="between", value=[math.nan, 5.0])])
        )


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


def test_kernel_environment_lacks_the_mssql_dsn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # The kernel reads it into its config; step code must not see the password.
    monkeypatch.setenv(ENV_MSSQL_DSN, "Driver=x;PWD=secret")
    client = KernelClient.spawn(tmp_path)
    try:
        result = client.execute(f"import os\nprint(os.environ.get({ENV_MSSQL_DSN!r}))")
    finally:
        client.close()
    assert result.stdout_tail == "None\n"


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


def test_close_kills_the_processes_a_step_started(tmp_path: Path) -> None:
    client = KernelClient.spawn(tmp_path)
    try:
        result = client.execute(CHILD_STEP)
    finally:
        client.close()
    pid = int(result.stdout_tail)
    assert exits_soon(pid), f"step child {pid} outlived close()"


def test_close_does_not_signal_a_kernel_the_client_already_reaped(
    stand_in: StandIn, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _ = stand_in(0)
    deadline = time.monotonic() + 5
    while client.is_alive():  # polls, and so reaps, the exited stand-in
        assert time.monotonic() < deadline, "the stand-in never exited"
        time.sleep(0.05)
    signalled: list[int] = []
    monkeypatch.setattr(os, "killpg", lambda pgid, sig: signalled.append(pgid))
    client.close()
    # Once reaped, the kernel's pid, its group's id, can belong to another process.
    assert signalled == []


def test_kernel_seen_exited_by_a_poll_has_its_group_killed_then(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # A "kernel" that starts a child, then exits. The test holds the socket's peer open, as a
    # child the kernel forked would, so only the client's liveness poll sees the exit.
    code = (
        "import subprocess, time\n"
        "print(subprocess.Popen(['sleep', '60']).pid, flush=True)\n"
        "time.sleep(1)\n"
    )
    client_end, peer = socket.socketpair()
    with (
        peer,
        subprocess.Popen(
            [sys.executable, "-c", code], stdout=subprocess.PIPE, start_new_session=True
        ) as process,
    ):
        client = KernelClient(process, client_end, tempfile.TemporaryDirectory())
        try:
            assert process.stdout is not None
            child = int(process.stdout.readline())
            with pytest.raises(KernelDead, match="exited with code 0"):
                client.list_datasets()
            assert exits_soon(child), f"child {child} outlived its kernel until close()"
            signalled: list[int] = []
            with monkeypatch.context() as patch:
                patch.setattr(os, "killpg", lambda pgid, sig: signalled.append(pgid))
                client.close()
            assert signalled == []
        finally:
            client.close()


def test_kernel_that_exits_before_connecting_has_its_group_killed() -> None:
    code = "import subprocess\nprint(subprocess.Popen(['sleep', '60']).pid, flush=True)\nexit(1)\n"
    with tempfile.TemporaryDirectory() as tmpdir, socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(Path(tmpdir) / "kernel.sock"))
        listener.listen(1)
        with subprocess.Popen(
            [sys.executable, "-c", code], stdout=subprocess.PIPE, start_new_session=True
        ) as process:
            assert process.stdout is not None
            pid = int(process.stdout.readline())
            with pytest.raises(KernelDead, match="exited with code 1 before connecting"):
                _accept(listener, process, 30)
    assert exits_soon(pid), f"child {pid} outlived a kernel that never connected"


def test_startup_timeout_kills_the_processes_the_kernel_started() -> None:
    # A "kernel" that starts a child and never connects.
    code = (
        "import subprocess, time\n"
        "print(subprocess.Popen(['sleep', '60']).pid, flush=True)\n"
        "time.sleep(60)\n"
    )
    with tempfile.TemporaryDirectory() as tmpdir, socket.socket(socket.AF_UNIX) as listener:
        listener.bind(str(Path(tmpdir) / "kernel.sock"))
        listener.listen(1)
        with subprocess.Popen(
            [sys.executable, "-c", code], stdout=subprocess.PIPE, start_new_session=True
        ) as process:
            assert process.stdout is not None
            pid = int(process.stdout.readline())
            with pytest.raises(KernelDead, match="did not connect"):
                _accept(listener, process, 0.3)
    assert exits_soon(pid), f"child {pid} outlived the startup timeout"


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


def test_spawn_does_not_kill_again_a_kernel_that_exited_before_connecting(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (tmp_path / "config.toml").write_text('[data]\nrow_cap = "lots"\n')
    signalled: list[int] = []
    killpg = os.killpg

    def record(pgid: int, sig: int) -> None:
        signalled.append(pgid)
        killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", record)
    with pytest.raises(KernelDead, match="before connecting"):
        KernelClient.spawn(tmp_path)
    # `_accept` killed its group when it reaped it; once reaped the pid can belong to another.
    assert len(signalled) == 1


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


def test_spawn_interrupted_after_the_kernel_started_kills_and_reaps_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[tuple[subprocess.Popen[bytes], str]] = []

    def interrupted(
        listener: socket.socket, process: subprocess.Popen[bytes], timeout: float
    ) -> socket.socket:
        started.append((process, listener.getsockname()))
        raise KeyboardInterrupt

    monkeypatch.setattr(client_module, "_accept", interrupted)
    with pytest.raises(KeyboardInterrupt):
        KernelClient.spawn(tmp_path)
    [(process, socket_path)] = started
    assert process.returncode == -signal.SIGKILL  # killed, and reaped by spawn
    assert not Path(socket_path).parent.exists()


def test_close_releases_the_socket_and_directory_when_the_kernel_will_not_exit(
    stand_in: StandIn, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    client, _ = stand_in(60)
    tmpdir = Path(client._tmpdir.name)

    def never_exits(timeout: float | None = None) -> int:
        raise subprocess.TimeoutExpired("kernel", timeout or 0)

    with monkeypatch.context() as patch:
        patch.setattr(client._process, "wait", never_exits)
        client.close()  # does not raise: a kernel SIGKILL cannot end is left to the OS
    assert f"kernel {client.pid} outlived SIGKILL" in capsys.readouterr().err
    assert client._conn.fileno() == -1
    assert not tmpdir.exists()


def test_spawn_reports_a_socket_path_too_long_to_bind(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    long_dir = tmp_path / ("d" * 150)  # past the 104 (macOS) or 108 (Linux) bytes of sun_path
    long_dir.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(long_dir))
    with pytest.raises(KernelDead, match="path too long") as info:
        KernelClient.spawn(tmp_path)
    assert isinstance(info.value.__cause__, OSError)
    assert list(long_dir.iterdir()) == []  # the temp directory is gone


def test_spawn_reports_a_kernel_that_cannot_be_started(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sys, "executable", str(tmp_path / "no-such-python"))
    # Its own temp root, short enough for the socket path, to see what `spawn` leaves in it.
    with tempfile.TemporaryDirectory(prefix="q-") as scratch:
        monkeypatch.setattr(tempfile, "tempdir", scratch)
        with pytest.raises(KernelDead, match="cannot start the kernel") as info:
            KernelClient.spawn(tmp_path)
        assert isinstance(info.value.__cause__, FileNotFoundError)
        assert list(Path(scratch).iterdir()) == []  # the temp directory is gone


def test_spawn_reports_a_temp_directory_it_cannot_make(monkeypatch: pytest.MonkeyPatch) -> None:
    def full_disk(*args: object, **kwargs: object) -> None:
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tempfile, "TemporaryDirectory", full_disk)
    with pytest.raises(KernelDead, match="cannot start the kernel") as info:
        KernelClient.spawn(Path("."))
    assert isinstance(info.value.__cause__, OSError)


def test_spawn_that_fails_building_the_client_leaves_no_kernel(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    started: list[tuple[subprocess.Popen[bytes], socket.socket, str]] = []
    real_accept = _accept

    def recording_accept(
        listener: socket.socket, process: subprocess.Popen[bytes], timeout: float
    ) -> socket.socket:
        conn = real_accept(listener, process, timeout)
        started.append((process, conn, listener.getsockname()))
        return conn

    def no_thread(*args: object, **kwargs: object) -> None:
        raise RuntimeError("can't start new thread")

    monkeypatch.setattr(client_module, "_accept", recording_accept)
    monkeypatch.setattr(KernelClient, "__init__", no_thread)
    with pytest.raises(RuntimeError, match="new thread"):
        KernelClient.spawn(tmp_path)
    [(process, conn, socket_path)] = started
    assert process.returncode == -signal.SIGKILL
    assert conn.fileno() == -1
    assert not Path(socket_path).parent.exists()


def test_close_does_not_raise_when_the_temp_directory_will_not_empty(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client = KernelClient.spawn(tmp_path)
    tmpdir = Path(client._tmpdir.name)
    rmdir = os.rmdir

    def still_written_to(path: str, **kwargs: Any) -> None:
        # What a process the kernel started in its own session, which the group kill misses,
        # causes by adding a file while the directory is removed.
        if path == str(tmpdir):
            raise OSError(errno.ENOTEMPTY, "Directory not empty")
        rmdir(path, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(os, "rmdir", still_written_to)
        client.close()
    tmpdir.rmdir()  # what the failed removal left behind


def answer_next_request_with(peer: socket.socket, result: object) -> None:
    """Reply to the next request on `peer` with a well-formed response carrying `result`."""
    request = json.loads(next(read_lines(peer)))
    peer.sendall(encode(Response(id=request["id"], result=result)))


@pytest.mark.parametrize(
    "call",
    [
        lambda c: c.execute("x = 1"),
        lambda c: c.interrupt(),
        lambda c: c.describe("df"),
        lambda c: c.list_datasets(),
        lambda c: c.query(QuerySpec(dataset="df")),
        lambda c: c.snapshot("df", Path("df.parquet")),
    ],
    ids=["execute", "interrupt", "describe", "list_datasets", "query", "snapshot"],
)
def test_result_that_does_not_validate_is_an_rpc_failure(
    stand_in: StandIn, call: Callable[[KernelClient], object]
) -> None:
    client, peer = stand_in(60)
    threading.Thread(target=answer_next_request_with, args=(peer, {"not": "a result"})).start()
    with pytest.raises(RpcFailure) as info:
        call(client)
    assert info.value.type == "InvalidResult"
    assert client.is_alive()  # the envelope was fine: only that answer was wrong
