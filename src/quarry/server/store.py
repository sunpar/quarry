"""Sessions on disk: one directory per session, one JSON file per completed step."""

from __future__ import annotations

import os
from pathlib import Path

from quarry.server.models import ProviderInfo, Session, SessionMeta, Step, new_id, now_iso

_PRIVATE_DIR = 0o700
_PRIVATE_FILE = 0o600


class SessionStore:
    def __init__(self, root: Path) -> None:
        self._dir = root / "sessions"

    def create(self, *, title: str, provider: ProviderInfo) -> SessionMeta:
        meta = SessionMeta(id=new_id(), title=title, created_at=now_iso(), provider=provider)
        path = self._dir / meta.id
        # Several researchers share a machine: only the owner reads prompts and code. The root
        # is `quarry serve`'s to create private; each level below it gets 0o700.
        self._dir.mkdir(mode=_PRIVATE_DIR, exist_ok=True)
        path.mkdir(mode=_PRIVATE_DIR)
        (path / "steps").mkdir(mode=_PRIVATE_DIR)
        _write_atomic(path / "session.json", meta.model_dump_json(indent=2))
        # The session directory and `sessions/` are durable once their own entries are.
        _sync_dir(self._dir)
        _sync_dir(self._dir.parent)
        return meta

    def list(self) -> list[SessionMeta]:
        if not self._dir.is_dir():
            return []
        metas = [
            SessionMeta.model_validate_json((p / "session.json").read_bytes())
            for p in self._dir.iterdir()
            if (p / "session.json").exists()
        ]
        return sorted(metas, key=lambda m: m.created_at, reverse=True)

    def get(self, session_id: str) -> Session:
        path = self._session_dir(session_id)
        meta = SessionMeta.model_validate_json((path / "session.json").read_bytes())
        # By index, not file name: `10000.json` sorts before `1001.json`.
        steps = sorted(
            (Step.model_validate_json(p.read_bytes()) for p in (path / "steps").glob("*.json")),
            key=lambda s: s.index,
        )
        return Session(meta=meta, steps=steps)

    def append_step(self, session_id: str, step: Step) -> None:
        if step.status == "running":
            raise ValueError("a running step cannot be persisted")
        target = self._session_dir(session_id) / "steps" / f"{step.index:04d}.json"
        _write_atomic(target, step.model_dump_json(by_alias=True, indent=2))

    def update_step(self, session_id: str, step: Step) -> None:
        if step.status == "running":
            raise ValueError("a running step cannot be persisted")
        target = self._session_dir(session_id) / "steps" / f"{step.index:04d}.json"
        if not target.exists():
            raise KeyError(step.id)
        _write_atomic(target, step.model_dump_json(by_alias=True, indent=2))

    def next_index(self, session_id: str) -> int:
        return len(list((self._dir / session_id / "steps").glob("*.json")))

    def _session_dir(self, session_id: str) -> Path:
        path = self._dir / session_id
        if not (path / "session.json").exists():
            raise KeyError(session_id)
        return path


def _write_atomic(path: Path, text: str) -> None:
    # A crash leaves at most a stray temp file, which the steps/*.json glob never matches.
    temp = path.with_name(f".{path.name}.tmp")
    # Created private, never chmodded after, so it is not readable by others even briefly.
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PRIVATE_FILE)
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)
    # The rename is durable only once the directory entry is.
    _sync_dir(path.parent)


def _sync_dir(path: Path) -> None:
    directory = os.open(path, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
