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
    def __init__(self, root: Path) -> None:
        self._root = root
        self._clients: dict[str, KernelClient] = {}
        self._running: set[str] = set()
        # Sessions whose kernel was respawned under existing steps and has not replayed them.
        self._replay_needed: set[str] = set()
        self._lock = threading.Lock()

    def get(self, session_id: str, *, has_steps: bool = False) -> KernelClient:
        with self._lock:
            client = self._clients.get(session_id)
            if client is None or not client.is_alive():
                if client is not None:
                    client.close()
                client = KernelClient.spawn(self._root)
                self._clients[session_id] = client
                if has_steps:
                    self._replay_needed.add(session_id)
            return client

    def status(self, session_id: str) -> KernelStatus:
        client = self._clients.get(session_id)
        replay_needed = session_id in self._replay_needed
        if client is None:
            return KernelStatus(status="starting", replay_needed=replay_needed)
        if not client.is_alive():
            return KernelStatus(status="dead", pid=client.pid, replay_needed=replay_needed)
        running = session_id in self._running
        return KernelStatus(
            status="running" if running else "idle", pid=client.pid, replay_needed=replay_needed
        )

    def mark_running(self, session_id: str, running: bool) -> None:
        if running:
            self._running.add(session_id)
        else:
            self._running.discard(session_id)

    def restart(self, session_id: str, steps: list[Step]) -> ReplayReport:
        """Replace the kernel and re-run `steps` in index order, stopping at the first failure.

        `replayed` counts the steps that ran ok; indices may have gaps, so it is not an index.
        A step that kills the kernel fails the replay like any other failing step.
        """
        with self._lock:
            old = self._clients.pop(session_id, None)
            if old is not None:
                old.close()
        client = self.get(session_id)
        self._replay_needed.discard(session_id)
        for replayed, step in enumerate(sorted(steps, key=lambda s: s.index)):
            try:
                result = client.execute(step.code)
            except KernelDead as exc:
                return ReplayReport(
                    replayed=replayed, failed_step=step.index, error=f"kernel died: {exc}"
                )
            if result.status != "ok":
                message = result.error.traceback if result.error else result.status
                return ReplayReport(replayed=replayed, failed_step=step.index, error=message)
        return ReplayReport(replayed=len(steps), failed_step=None, error=None)

    def close_all(self) -> None:
        with self._lock:
            for client in self._clients.values():
                client.close()
            self._clients.clear()
