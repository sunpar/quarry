import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest

from quarry.kernel.client import KernelClient, KernelDead, RpcFailure
from quarry.query import QuerySpec


@pytest.fixture
def kernel(tmp_path: Path) -> Iterator[KernelClient]:
    client = KernelClient.spawn(tmp_path)
    yield client
    client.close()


@pytest.fixture
def stand_in() -> Iterator[tuple[KernelClient, socket.socket]]:
    """A client whose "kernel" sleeps for a second and whose socket peer the test drives."""
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(1)"])
    client_end, peer = socket.socketpair()
    client = KernelClient(process, client_end, tempfile.TemporaryDirectory())
    yield client, peer
    client.close()
    peer.close()


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


def test_interrupt_busy_loop(kernel: KernelClient) -> None:
    holder: dict[str, object] = {}

    def run() -> None:
        holder["result"] = kernel.execute("import time\nwhile True:\n    time.sleep(0.01)\n")

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.5)
    kernel.interrupt()
    thread.join(timeout=10)
    assert not thread.is_alive()
    result = holder["result"]
    assert getattr(result, "status", None) == "interrupted"
    assert kernel.execute("x = 1").status == "ok"


def test_requests_are_answered_while_a_step_runs(kernel: KernelClient) -> None:
    kernel.execute("df = pl.DataFrame({'a': [1]})")
    busy = threading.Thread(
        target=kernel.execute, args=("import time\nwhile True:\n    time.sleep(0.01)\n",)
    )
    busy.start()
    time.sleep(0.2)
    assert kernel.describe("df").rows == 1
    assert [m.name for m in kernel.list_datasets()] == ["df"]
    kernel.interrupt()
    busy.join(timeout=10)
    assert not busy.is_alive()


def test_interrupt_while_idle_is_ignored(kernel: KernelClient) -> None:
    kernel.interrupt()
    assert kernel.execute("x = 1").status == "ok"
    assert kernel.is_alive()


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


def test_undecodable_response_marks_kernel_dead(
    stand_in: tuple[KernelClient, socket.socket],
) -> None:
    client, peer = stand_in

    def answer_with_garbage() -> None:
        peer.recv(65536)
        peer.sendall(b"not a response\n")

    threading.Thread(target=answer_with_garbage).start()
    with pytest.raises(KernelDead, match="undecodable response"):
        client.list_datasets()
    assert not client.is_alive()


def test_call_fails_when_kernel_exits_with_its_socket_still_open(
    stand_in: tuple[KernelClient, socket.socket],
) -> None:
    client, _ = stand_in  # the peer stays open, as when a forked child inherited the socket
    started = time.monotonic()
    with pytest.raises(KernelDead, match="exited"):
        client.list_datasets()
    assert time.monotonic() - started < 5
