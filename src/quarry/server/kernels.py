"""One kernel per session, with restart-and-replay."""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel

from quarry.kernel.client import KernelClient, KernelDead
from quarry.server.models import KernelStatus, Step


class ReplayReport(BaseModel):
    replayed: int
    failed_step: int | None
    error: str | None


class KernelManager:
    def __init__(self, root: Path, threads: int = 0) -> None:
        self._root = root
        self._threads = threads
        self._clients: dict[str, KernelClient] = {}
        self._running: set[str] = set()
        self._closed = False
        self._lock = threading.Lock()

    def get(self, session_id: str) -> KernelClient:
        """The session's kernel, started on first use; KernelDead once it died, until restart."""
        with self._lock:
            # A step thread can reach here after shutdown closed every kernel.
            if self._closed:
                raise KernelDead("the server is shutting down")
            client = self._clients.get(session_id)
            if client is None:
                client = KernelClient.spawn(self._root, threads=self._threads)
                self._clients[session_id] = client
            elif not client.is_alive():
                raise KernelDead("kernel died; restart the session to replay its steps")
            return client

    def status(self, session_id: str) -> KernelStatus:
        client = self._clients.get(session_id)
        if client is None:
            return KernelStatus(status="starting")
        if not client.is_alive():
            return KernelStatus(status="dead", pid=client.pid)
        running = session_id in self._running
        return KernelStatus(status="running" if running else "idle", pid=client.pid)

    def mark_running(self, session_id: str, running: bool) -> None:
        if running:
            self._running.add(session_id)
        else:
            self._running.discard(session_id)

    def kill(self, session_id: str) -> None:
        """Kill the session's kernel and what it runs. Like a kernel that died, it stays dead
        until restart, so `get` never starts a fresh one in its place."""
        with self._lock:
            client = self._clients.get(session_id)
            if client is not None:
                client.close()

    def restart(self, session_id: str, steps: list[Step]) -> ReplayReport:
        """Replace the kernel and re-run each step's runs, in the order given (the store's,
        by index).

        A run that failed the first time may fail again, so its partial effects come back; an
        interrupted run is skipped. Replay stops at the first run that was ok and now is not,
        or that kills the kernel. `replayed` counts whole steps, not indices, which can gap.
        """
        with self._lock:
            old = self._clients.pop(session_id, None)
            if old is not None:
                old.close()
        client = self.get(session_id)
        for replayed, step in enumerate(steps):
            for run in step.runs:
                if run.status == "interrupted":
                    continue
                try:
                    result = client.execute(run.code)
                except KernelDead as exc:
                    return ReplayReport(
                        replayed=replayed, failed_step=step.index, error=f"kernel died: {exc}"
                    )
                if run.status == "ok" and result.status != "ok":
                    message = result.error.traceback if result.error else result.status
                    return ReplayReport(replayed=replayed, failed_step=step.index, error=message)
        return ReplayReport(replayed=len(steps), failed_step=None, error=None)

    def close_all(self) -> None:
        with self._lock:
            self._closed = True
            for client in self._clients.values():
                client.close()
            self._clients.clear()
