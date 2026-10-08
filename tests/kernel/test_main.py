import resource
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from pathlib import Path

import duckdb
import polars as pl
import pytest

from quarry.kernel.__main__ import apply_memory_cap, serve
from quarry.kernel.executor import Executor
from quarry.kernel.protocol import Request, Response, decode_response, encode, read_lines

BUSY_LOOP = "import time\nwhile True:\n    time.sleep(0.01)\n"

KernelProcess = tuple[subprocess.Popen[bytes], socket.socket]


@pytest.fixture(autouse=True)
def sigint_restored() -> Iterator[None]:
    """`serve` installs the kernel's SIGINT handler; put pytest's back afterwards."""
    previous = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, previous)


@pytest.fixture
def kernel_process(tmp_path: Path) -> Iterator[KernelProcess]:
    """`python -m quarry.kernel` started as the client starts it, driven over its raw socket."""
    with tempfile.TemporaryDirectory(prefix="quarry-test-") as socket_dir:
        path = str(Path(socket_dir) / "kernel.sock")
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
            listener.bind(path)
            listener.listen(1)
            listener.settimeout(30)
            command = [sys.executable, "-m", "quarry.kernel", "--socket", path]
            process = subprocess.Popen([*command, "--root", str(tmp_path)])
            try:
                conn, _ = listener.accept()
                conn.settimeout(10)  # a missing response fails the test instead of hanging it
                with conn:
                    yield process, conn
            finally:
                process.kill()
                process.wait()


def serve_lines(*lines: bytes) -> list[Response]:
    """Feed `lines` to `serve` over a socketpair, then EOF; every response it wrote back.

    On EOF the real kernel exits at once; here `serve` drains its queue and returns instead.
    """
    kernel_end, client_end = socket.socketpair()
    with client_end:
        client_end.sendall(b"".join(lines))
        client_end.shutdown(socket.SHUT_WR)
        executor = Executor({"pl": pl, "duckdb": duckdb}, row_cap=10)
        serve(kernel_end, executor, on_disconnect=lambda: None)
        received = b"".join(iter(lambda: client_end.recv(65536), b""))
    return [decode_response(line) for line in received.splitlines()]


def outcome(response: Response) -> str:
    """An execute response's status, or its error type."""
    if response.error is not None:
        return response.error.type
    assert isinstance(response.result, dict)
    return str(response.result["status"])


def test_serve_skips_a_garbage_line_and_answers_the_next(
    capfd: pytest.CaptureFixture[str],
) -> None:
    execute = Request(id=7, method="execute", params={"code": "x = 1"})
    responses = serve_lines(b"not json\n", encode(execute))
    assert [r.id for r in responses] == [7]
    assert outcome(responses[0]) == "ok"
    assert "undecodable request" in capfd.readouterr().err


def test_serve_answers_a_malformed_request_with_its_id() -> None:
    responses = serve_lines(b'{"id": 5, "method": 3}\n')
    assert [r.id for r in responses] == [5]
    assert responses[0].error is not None
    assert responses[0].error.type == "ValidationError"


def test_serve_answers_requests_after_a_malformed_one() -> None:
    listing = Request(id=2, method="list_datasets", params={})
    responses = serve_lines(b'{"id": 1, "params": []}\n', b"\xff\n", encode(listing))
    assert [r.id for r in responses] == [1, 2]
    assert responses[1] == Response(id=2, result=[])


def test_serve_refuses_queued_requests_once_shutting_down() -> None:
    running = Request(id=1, method="execute", params={"code": "import time\ntime.sleep(0.3)"})
    queued = Request(id=2, method="execute", params={"code": "x = 1"})
    shutdown = Request(id=3, method="shutdown", params={})
    responses = {r.id: r for r in serve_lines(encode(running), encode(queued), encode(shutdown))}
    assert responses[3] == Response(id=3)
    assert outcome(responses[2]) == "KernelShutdown"
    # The shutdown interrupts the step if it had started, and refuses it if it had not.
    assert outcome(responses[1]) in {"interrupted", "KernelShutdown"}


def test_shutdown_ends_a_kernel_mid_step(kernel_process: KernelProcess) -> None:
    process, conn = kernel_process
    responses = read_lines(conn)
    conn.sendall(encode(Request(id=1, method="execute", params={"code": BUSY_LOOP})))
    time.sleep(0.5)
    conn.sendall(encode(Request(id=2, method="shutdown", params={})))
    answered = {r.id: r for r in (decode_response(next(responses)) for _ in range(2))}
    assert answered[2] == Response(id=2)
    assert outcome(answered[1]) in {"interrupted", "KernelShutdown"}
    assert process.wait(timeout=5) == 0


def test_shutdown_ends_a_kernel_whose_step_left_a_thread_running(
    kernel_process: KernelProcess,
) -> None:
    process, conn = kernel_process
    responses = read_lines(conn)
    step = "import threading, time\nthreading.Thread(target=time.sleep, args=(3600,)).start()\n"
    conn.sendall(encode(Request(id=1, method="execute", params={"code": step})))
    assert outcome(decode_response(next(responses))) == "ok"
    conn.sendall(encode(Request(id=2, method="shutdown", params={})))
    assert decode_response(next(responses)) == Response(id=2)
    assert process.wait(timeout=5) == 0


def test_kernel_exits_when_its_server_goes_away_mid_step(kernel_process: KernelProcess) -> None:
    process, conn = kernel_process
    conn.sendall(encode(Request(id=1, method="execute", params={"code": BUSY_LOOP})))
    time.sleep(0.5)
    conn.close()
    assert process.wait(timeout=5) == 0


def test_memory_cap_limits_address_space(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []

    def record(which: int, limits: tuple[int, int]) -> None:
        calls.append((which, limits))

    monkeypatch.setattr(resource, "setrlimit", record)
    apply_memory_cap(512)
    limit = 512 * 1024 * 1024
    assert calls == [(resource.RLIMIT_AS, (limit, limit))]


def test_memory_cap_the_os_refuses_is_reported_not_fatal(
    monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    def refuse(which: int, limits: tuple[int, int]) -> None:
        raise ValueError("current limit exceeds maximum limit")  # what macOS says

    monkeypatch.setattr(resource, "setrlimit", refuse)
    apply_memory_cap(512)
    assert "memory cap of 512 MB not applied" in capfd.readouterr().err
