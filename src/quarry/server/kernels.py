"""One kernel per session, with restart-and-replay."""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel

from quarry.kernel.client import KernelClient, KernelDead
from quarry.server.models import KernelStatus, Step


class SessionBusy(Exception):
    pass


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
        # Sessions whose kernel was started under existing steps and has not replayed them.
        self._replay_needed: set[str] = set()
        self._replaying: set[str] = set()
        self._closed = False
        self._lock = threading.Lock()

    def get(self, session_id: str, *, has_steps: bool = False) -> KernelClient:
        """The session's kernel, started on first use; KernelDead once it died, until restart;
        SessionBusy while a restart replays into it, since a half-replayed namespace is not the
        session's. A kernel started for a session that already has steps is `replay_needed`."""
        with self._lock:
            if session_id in self._replaying:
                raise SessionBusy(session_id)
            client = self._clients.get(session_id)
            if client is None:
                return self._spawn(session_id, has_steps=has_steps)
            if not client.is_alive():
                raise KernelDead("kernel died; restart the session to replay its steps")
            return client

    def _spawn(self, session_id: str, *, has_steps: bool) -> KernelClient:
        """Start the session's kernel; the caller holds the lock."""
        # A step thread can reach here after shutdown closed every kernel.
        if self._closed:
            raise KernelDead("the server is shutting down")
        client = KernelClient.spawn(self._root, threads=self._threads)
        self._clients[session_id] = client
        if has_steps:
            self._replay_needed.add(session_id)
        return client

    def status(self, session_id: str, *, has_steps: bool = False) -> KernelStatus:
        client = self._clients.get(session_id)
        replay_needed = session_id in self._replay_needed
        if client is None:
            # Not started yet: a session with steps will need a replay once it is.
            return KernelStatus(status="starting", replay_needed=has_steps)
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
        A session stays `replay_needed` until a replay runs through.
        """
        # The closed client stays until a new kernel starts: a failed start leaves the session
        # dead, never a fresh empty kernel that skipped the replay.
        self.kill(session_id)
        with self._lock:
            client = self._spawn(session_id, has_steps=bool(steps))
            self._replaying.add(session_id)
        try:
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
                    # An interrupted rerun left the run's effects unbuilt, whatever it saved.
                    if result.status == "interrupted" or (
                        run.status == "ok" and result.status != "ok"
                    ):
                        message = result.error.traceback if result.error else result.status
                        return ReplayReport(
                            replayed=replayed, failed_step=step.index, error=message
                        )
            self._replay_needed.discard(session_id)
            return ReplayReport(replayed=len(steps), failed_step=None, error=None)
        finally:
            with self._lock:
                self._replaying.discard(session_id)

    def close_all(self) -> None:
        with self._lock:
            self._closed = True
            for client in self._clients.values():
                client.close()
            self._clients.clear()
