import resource
import signal
import socket
from collections.abc import Iterator

import duckdb
import polars as pl
import pytest

from quarry.kernel.__main__ import apply_memory_cap, serve
from quarry.kernel.executor import Executor
from quarry.kernel.protocol import Request, Response, decode_response, encode


@pytest.fixture(autouse=True)
def sigint_restored() -> Iterator[None]:
    """`serve` installs the kernel's SIGINT handler; put pytest's back afterwards."""
    previous = signal.getsignal(signal.SIGINT)
    yield
    signal.signal(signal.SIGINT, previous)


def serve_lines(*lines: bytes) -> list[Response]:
    """Feed `lines` to `serve` over a socketpair, then EOF; every response it wrote back."""
    kernel_end, client_end = socket.socketpair()
    with client_end:
        client_end.sendall(b"".join(lines))
        client_end.shutdown(socket.SHUT_WR)
        serve(kernel_end, Executor({"pl": pl, "duckdb": duckdb}, row_cap=10))
        received = b"".join(iter(lambda: client_end.recv(65536), b""))
    return [decode_response(line) for line in received.splitlines()]


def test_serve_skips_a_garbage_line_and_answers_the_next(
    capsys: pytest.CaptureFixture[str],
) -> None:
    execute = Request(id=7, method="execute", params={"code": "x = 1"})
    responses = serve_lines(b"not json\n", encode(execute))
    assert [r.id for r in responses] == [7]
    assert isinstance(responses[0].result, dict)
    assert responses[0].result["status"] == "ok"
    assert "undecodable request" in capsys.readouterr().err


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


def test_memory_cap_limits_address_space(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[tuple[int, tuple[int, int]]] = []

    def record(which: int, limits: tuple[int, int]) -> None:
        calls.append((which, limits))

    monkeypatch.setattr(resource, "setrlimit", record)
    apply_memory_cap(512)
    limit = 512 * 1024 * 1024
    assert calls == [(resource.RLIMIT_AS, (limit, limit))]


def test_memory_cap_the_os_refuses_is_reported_not_fatal(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def refuse(which: int, limits: tuple[int, int]) -> None:
        raise ValueError("current limit exceeds maximum limit")  # what macOS says

    monkeypatch.setattr(resource, "setrlimit", refuse)
    apply_memory_cap(512)
    assert "memory cap of 512 MB not applied" in capsys.readouterr().err
