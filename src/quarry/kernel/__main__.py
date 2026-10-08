"""Kernel subprocess entry: python -m quarry.kernel --socket PATH --root ROOT."""

from __future__ import annotations

import argparse
import json
import queue
import resource
import signal
import socket
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from types import FrameType

import duckdb
import polars as pl
from pydantic import ValidationError

from quarry.config import load_config
from quarry.kernel.executor import Executor
from quarry.kernel.protocol import (
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
    args = parser.parse_args()
    config = load_config(Path(args.root))
    if config.data.kernel_memory_mb > 0:
        apply_memory_cap(config.data.kernel_memory_mb)
    namespace: dict[str, object] = {"pl": pl, "duckdb": duckdb}
    executor = Executor(namespace, row_cap=config.data.row_cap)
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(args.socket)
    serve(conn, executor)


def apply_memory_cap(megabytes: int) -> None:
    """Cap the address space at `megabytes`; where the OS refuses (macOS does), run uncapped."""
    limit = megabytes * 1024 * 1024
    try:
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ValueError, OSError) as exc:
        print(f"quarry kernel: memory cap of {megabytes} MB not applied: {exc}", file=sys.stderr)


def serve(conn: socket.socket, executor: Executor) -> None:
    """Answer requests on `conn` until it closes or a `shutdown` arrives, then close it.

    Call on the main thread: it runs every `execute`, the one place an interrupt may land.
    A reader thread answers every other request at once, even while a step runs.
    """
    service = KernelService(executor)
    signal.signal(signal.SIGINT, _interrupt_handler(executor))
    executing_thread = threading.get_ident()
    send = _sender(conn)
    executes: queue.Queue[Request | None] = queue.Queue()

    def answer(request: Request) -> bool:
        """Answer `request`, or queue it for the main thread; False when reading should stop."""
        match request.method:
            case "execute":
                executes.put(request)
                return True
            case "interrupt":
                signal.pthread_kill(executing_thread, signal.SIGINT)
                return send(Response(id=request.id))
            case "shutdown":
                send(service.handle(request))
                return False
            case _:
                return send(service.handle(request))

    def reader() -> None:
        try:
            for line in read_lines(conn):
                request = _decode(line, send)
                if request is not None and not answer(request):
                    return
        finally:
            # EOF, shutdown, or a reader that died: the main thread finishes the queue and exits,
            # and the client sees the socket close instead of waiting forever.
            executes.put(None)

    threading.Thread(target=reader, daemon=True).start()
    while (request := executes.get()) is not None:
        if not send(service.handle(request)):
            break
    conn.close()


def _interrupt_handler(executor: Executor) -> Callable[[int, FrameType | None], None]:
    def on_sigint(signum: int, frame: FrameType | None) -> None:
        # Outside user code (idle, describing a step's writes, writing a response) a
        # KeyboardInterrupt would escape and end the kernel, so the signal is dropped there.
        if executor.running:
            raise KeyboardInterrupt

    return on_sigint


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
            reason = exc.errors()[0]["msg"]
            print(f"quarry kernel: skipped an undecodable request: {reason}", file=sys.stderr)
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


if __name__ == "__main__":
    main()
