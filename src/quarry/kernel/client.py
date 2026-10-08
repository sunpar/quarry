"""Spawn and drive a kernel subprocess over a Unix socket."""

from __future__ import annotations

import contextlib
import itertools
import os
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import Future
from pathlib import Path
from typing import Final

from pydantic import TypeAdapter, ValidationError

from quarry.config import ENV_API_KEY
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import ExecResult, QueryResult
from quarry.kernel.protocol import (
    InterruptResult,
    Request,
    Response,
    decode_response,
    encode,
    read_lines,
)
from quarry.query.spec import Json, QuerySpec

# How often a waiting caller checks that the kernel process still exists. The socket closing is
# the usual sign of death, but a child the kernel forked can hold the socket open after it dies.
_LIVENESS_POLL_SECONDS: Final = 0.5
# How often spawn checks, while waiting for the kernel to connect, that it has not exited.
_ACCEPT_POLL_SECONDS: Final = 0.1
_DATASET_LIST: Final = TypeAdapter(list[DatasetMeta])


class KernelDead(Exception):
    """The kernel process exited or its socket broke."""


class RpcFailure(Exception):
    """The kernel answered with an error response."""

    def __init__(self, type_: str, message: str) -> None:
        super().__init__(f"{type_}: {message}")
        self.type = type_
        self.message = message


class KernelClient:
    def __init__(
        self,
        process: subprocess.Popen[bytes],
        conn: socket.socket,
        tmpdir: tempfile.TemporaryDirectory[str],
    ) -> None:
        self._process = process
        self._conn = conn
        self._tmpdir = tmpdir
        self._ids = itertools.count(1)
        self._pending: dict[int, Future[Response]] = {}
        self._lock = threading.Lock()  # guards _pending and _dead
        self._send_lock = threading.Lock()  # concurrent calls must not interleave their lines
        self._dead = False
        threading.Thread(target=self._read_responses, daemon=True).start()

    @classmethod
    def spawn(cls, root: Path, *, startup_timeout: float = 30.0) -> KernelClient:
        """Start a kernel for `root`; KernelDead if it exits or does not connect in time."""
        tmpdir = tempfile.TemporaryDirectory(prefix="quarry-kernel-")
        socket_path = Path(tmpdir.name) / "kernel.sock"
        # No provider API keys: step code can print its environment into a persisted result.
        env = {k: v for k, v in os.environ.items() if k not in ENV_API_KEY.values()}
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(socket_path))
                listener.listen(1)
                # stdout and stderr are inherited: C-level output from user code goes to those
                # fds, and a pipe nobody drains would block the kernel once it fills. A new
                # session keeps a terminal Ctrl-C aimed at the server away from kernel steps.
                process = subprocess.Popen(
                    [
                        sys.executable,
                        "-m",
                        "quarry.kernel",
                        "--socket",
                        str(socket_path),
                        "--root",
                        str(root),
                        "--temp-dir",
                        tmpdir.name,
                    ],
                    stdin=subprocess.DEVNULL,
                    env=env,
                    start_new_session=True,
                )
                conn = _accept(listener, process, startup_timeout)
        except BaseException:
            tmpdir.cleanup()
            raise
        return cls(process, conn, tmpdir)

    def execute(self, code: str) -> ExecResult:
        return ExecResult.model_validate(self._call("execute", {"code": code}))

    def interrupt(self) -> bool:
        """Interrupt the running step; False when none was running, so nothing was."""
        return InterruptResult.model_validate(self._call("interrupt", {})).delivered

    def describe(self, name: str) -> DatasetMeta:
        return DatasetMeta.model_validate(self._call("describe", {"name": name}))

    def list_datasets(self) -> list[DatasetMeta]:
        return _DATASET_LIST.validate_python(self._call("list_datasets", {}))

    def query(self, spec: QuerySpec) -> QueryResult:
        return QueryResult.model_validate(
            self._call("query", {"spec": spec.model_dump(mode="json")})
        )

    def snapshot(self, name: str, path: Path) -> DatasetMeta:
        return DatasetMeta.model_validate(self._call("snapshot", {"name": name, "path": str(path)}))

    def shutdown(self) -> None:
        """Stop the kernel, interrupting a running step; later calls raise KernelDead."""
        with contextlib.suppress(KernelDead):  # already gone is as good as shut down
            self._call("shutdown", {})
        with self._lock:
            self._dead = True  # calls already in flight still get their answers

    def is_alive(self) -> bool:
        return not self._dead and self._process.poll() is None

    def close(self) -> None:
        """Kill the kernel and what its steps started, and release its socket and directory."""
        _kill_group(self._process)
        self._process.wait(timeout=5)
        with contextlib.suppress(OSError):  # the peer may already be gone
            # Wakes the reader thread even if a child the kernel forked holds the socket open.
            self._conn.shutdown(socket.SHUT_RDWR)
        self._conn.close()
        self._tmpdir.cleanup()

    def _call(self, method: str, params: dict[str, Json]) -> Json:
        request = Request(id=next(self._ids), method=method, params=params)
        future: Future[Response] = Future()
        with self._lock:
            # Checked under the lock: a call registered after _mark_dead would wait forever.
            if self._dead or self._process.poll() is not None:
                raise KernelDead("kernel is not running")
            self._pending[request.id] = future
        try:
            with self._send_lock:
                self._conn.sendall(encode(request))
        except OSError as exc:
            self._mark_dead("kernel socket closed")
            raise KernelDead("kernel socket closed") from exc
        response = self._wait(future)
        if response.error is not None:
            raise RpcFailure(response.error.type, response.error.message)
        return response.result

    def _wait(self, future: Future[Response]) -> Response:
        """`future`'s response, or KernelDead once the kernel process has exited."""
        while True:
            try:
                return future.result(timeout=_LIVENESS_POLL_SECONDS)
            except TimeoutError:
                code = self._process.poll()
                if code is not None:
                    self._mark_dead(f"kernel exited with code {code}")

    def _read_responses(self) -> None:
        reason = "kernel closed its socket"
        try:
            for line in read_lines(self._conn):
                response = decode_response(line)
                with self._lock:
                    future = self._pending.pop(response.id, None)
                if future is not None:
                    future.set_result(response)
        except ValidationError as exc:  # a kernel that writes garbage is broken
            reason = f"kernel sent an undecodable response: {exc.errors()[0]['msg']}"
        finally:
            self._mark_dead(reason)

    def _mark_dead(self, reason: str) -> None:
        with self._lock:
            self._dead = True
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            future.set_exception(KernelDead(reason))


def _accept(
    listener: socket.socket, process: subprocess.Popen[bytes], timeout: float
) -> socket.socket:
    """The kernel's connection; KernelDead as soon as it exits, or once `timeout` passes."""
    listener.settimeout(_ACCEPT_POLL_SECONDS)
    deadline = time.monotonic() + timeout
    while (code := process.poll()) is None:
        try:
            conn, _ = listener.accept()
        except TimeoutError:
            if time.monotonic() < deadline:
                continue
            _kill_group(process)
            process.wait()
            raise KernelDead(f"kernel did not connect within {timeout} seconds") from None
        conn.settimeout(None)
        return conn
    raise KernelDead(f"kernel exited with code {code} before connecting")


def _kill_group(process: subprocess.Popen[bytes]) -> None:
    """SIGKILL the kernel and every process its steps started: the group the kernel leads.

    Callers kill before they reap where they can: once the kernel is reaped and its group is
    empty, another process can take its pid, which is the group's id.
    """
    # ProcessLookupError: the group is empty. macOS raises PermissionError instead when only
    # zombies are left in it, as when the kernel exited and nothing has reaped it yet.
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGKILL)
