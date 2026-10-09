"""Kernel subprocess entry: python -m quarry.kernel --socket PATH --root ROOT --temp-dir DIR."""

from __future__ import annotations

import argparse
import json
import os
import queue
import resource
import signal
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import NoReturn, cast

import duckdb
from pydantic import ValidationError

from quarry.config import ENV_MSSQL_DSN, load_config
from quarry.data.namespace import build_namespace
from quarry.kernel.executor import Executor
from quarry.kernel.protocol import (
    InterruptResult,
    Request,
    Response,
    RpcError,
    decode_request,
    encode,
    read_lines,
)
from quarry.kernel.service import KernelService

# Writes one response; False once the peer is gone.
Send = Callable[[Response], bool]


def main() -> None:
    parser = argparse.ArgumentParser(prog="python -m quarry.kernel")
    parser.add_argument("--socket", required=True)
    parser.add_argument("--root", required=True)
    parser.add_argument("--temp-dir", required=True)
    args = parser.parse_args()
    config = load_config(Path(args.root))
    # `sql` takes the DSN from the config. Step code, and every process it starts, can print
    # the environment into a persisted result, and the DSN can carry a password.
    os.environ.pop(ENV_MSSQL_DSN, None)
    if config.data.kernel_memory_mb > 0:
        apply_memory_cap(config.data.kernel_memory_mb)
    namespace = build_namespace(config, Path(args.temp_dir))
    kernel_conn = cast(duckdb.DuckDBPyConnection, namespace["_conn"])
    executor = Executor(namespace, conn=kernel_conn, row_cap=config.data.row_cap)
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(args.socket)
    serve(conn, executor)
    _exit_now()


def apply_memory_cap(megabytes: int) -> None:
    """Cap the data segment at `megabytes`; where the OS refuses (macOS does), run uncapped.

    Not the address space: `RLIMIT_AS` also counts mmapped files, thread stacks and malloc
    arenas, so a cap near the working set broke polars and DuckDB in confusing ways.
    """
    limit = megabytes * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_DATA, (limit, limit))
    except (ValueError, OSError) as exc:
        _warn(f"memory cap of {megabytes} MB not applied: {exc}")


def _exit_now() -> NoReturn:
    """End the process, even while a step runs or a thread a step started is still alive."""
    try:
        for stream in (sys.stdout, sys.stderr, sys.__stdout__, sys.__stderr__):
            if stream is not None:
                stream.flush()
    finally:  # a stream that cannot flush must not keep the process alive
        os._exit(0)


def serve(
    conn: socket.socket, executor: Executor, *, on_disconnect: Callable[[], None] = _exit_now
) -> None:
    """Answer requests on `conn` until a `shutdown`, then close it.

    Call on the main thread. Every request that touches the namespace runs here, in arrival
    order, so none races a running step, and `execute` is the one place an interrupt may land.
    A reader thread frames requests and answers `interrupt` and `shutdown` itself, even
    mid-step. When the client closes the socket nobody is left to receive a result, so the
    reader calls `on_disconnect` at once, even mid-step; by default it ends the process.
    """
    service = KernelService(executor)
    signal.signal(signal.SIGINT, executor.on_sigint)
    executing_thread = threading.get_ident()
    send = _sender(conn)
    requests: queue.Queue[Request | None] = queue.Queue()
    stopping = threading.Event()

    def interrupt_step() -> bool:
        """Signal the running step, if there is one; whether there was."""
        if not executor.running:
            return False
        signal.pthread_kill(executing_thread, signal.SIGINT)
        return True

    def answer(request: Request) -> None:
        match request.method:
            case "interrupt":
                delivered = InterruptResult(delivered=interrupt_step())
                send(Response(id=request.id, result=delivered.model_dump()))
            case "shutdown":
                send(service.handle(request))  # answered before the main thread can exit
                stopping.set()
                interrupt_step()
                requests.put(None)
            case _:
                requests.put(request)

    def reader() -> None:
        try:
            for line in read_lines(conn):
                request = _decode(line, send)
                if request is not None:
                    answer(request)
            on_disconnect()
        finally:
            # A reader that died still ends the main loop, so the client sees the socket close.
            requests.put(None)

    threading.Thread(target=reader, daemon=True).start()
    while (request := requests.get()) is not None:
        response = _refused(request) if stopping.is_set() else service.handle(request)
        if not send(response):
            break
    conn.close()


def _refused(request: Request) -> Response:
    error = RpcError(type="KernelShutdown", message="the kernel is shutting down")
    return Response(id=request.id, error=error)


def _sender(conn: socket.socket) -> Send:
    lock = threading.Lock()  # the reader and main threads both write; lines must not interleave

    def send(response: Response) -> bool:
        data = encode(response)
        with lock:
            try:
                conn.sendall(data)
            except OSError:
                return False
        return True

    return send


def _decode(line: bytes, send: Send) -> Request | None:
    """`line` as a request; if it is not one, answer it with an error when it has an id."""
    try:
        return decode_request(line)
    except ValidationError as exc:
        request_id = _request_id(line)
        if request_id is None:
            _warn(f"skipped an undecodable request: {exc.errors()[0]['msg']}")
        else:
            error = RpcError(type=type(exc).__name__, message=str(exc))
            send(Response(id=request_id, error=error))
        return None


def _request_id(line: bytes) -> int | None:
    """The integer `id` of a line that is not a valid request, when it has one."""
    try:
        message = json.loads(line)
    except (ValueError, RecursionError):  # not JSON, not UTF-8, or nested too deep
        return None
    request_id = message.get("id") if isinstance(message, dict) else None
    if isinstance(request_id, bool) or not isinstance(request_id, int):  # `true` is no id
        return None
    return request_id


def _warn(message: str) -> None:
    # The real stderr: while a step runs, sys.stderr is the step's own captured output.
    print(f"quarry kernel: {message}", file=sys.__stderr__)


if __name__ == "__main__":
    main()
