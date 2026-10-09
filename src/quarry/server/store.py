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
        # Several researchers share a machine: only the owner reads prompts and code. The root is
        # not managed here (`quarry serve` creates it private); `parents=True` only keeps a store
        # on a missing root working. Each level the store makes gets 0o700, one mkdir apiece,
        # because `parents=True` applies the mode to the last level alone.
        self._dir.mkdir(parents=True, mode=_PRIVATE_DIR, exist_ok=True)
        path.mkdir(mode=_PRIVATE_DIR)
        (path / "steps").mkdir(mode=_PRIVATE_DIR)
        _write_atomic(path / "session.json", meta.model_dump_json(indent=2))
        return meta

    def list(self) -> list[SessionMeta]:
        if not self._dir.is_dir():
            return []
        metas = [
            SessionMeta.model_validate_json((p / "session.json").read_text())
            for p in self._dir.iterdir()
            if (p / "session.json").exists()
        ]
        return sorted(metas, key=lambda m: m.created_at, reverse=True)

    def get(self, session_id: str) -> Session:
        path = self._session_dir(session_id)
        meta = SessionMeta.model_validate_json((path / "session.json").read_text())
        step_files = sorted((path / "steps").glob("*.json"))
        steps = [Step.model_validate_json(p.read_text()) for p in step_files]
        return Session(meta=meta, steps=steps)

    def append_step(self, session_id: str, step: Step) -> None:
        if step.status == "running":
            raise ValueError("a running step cannot be persisted")
        target = self._session_dir(session_id) / "steps" / f"{step.index:04d}.json"
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
    with os.fdopen(os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, _PRIVATE_FILE), "w") as f:
        f.write(text)
        f.flush()
        os.fsync(f.fileno())
    temp.replace(path)
    # The rename is durable only once the directory entry is.
    directory = os.open(path.parent, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)
