"""Sessions on disk: one directory per session, one JSON file per completed step."""

from __future__ import annotations

from pathlib import Path

from quarry.projects.files import PRIVATE_DIR, sync_dir, write_atomic
from quarry.server.models import ProviderInfo, Session, SessionMeta, Step, new_id, now_iso


class SessionStore:
    def __init__(self, root: Path) -> None:
        self._dir = root / "sessions"

    def create(self, *, title: str, provider: ProviderInfo) -> SessionMeta:
        meta = SessionMeta(id=new_id(), title=title, created_at=now_iso(), provider=provider)
        path = self._dir / meta.id
        # Several researchers share a machine: only the owner reads prompts and code. The root
        # is `quarry serve`'s to create private; each level below it gets 0o700.
        self._dir.mkdir(mode=PRIVATE_DIR, exist_ok=True)
        path.mkdir(mode=PRIVATE_DIR)
        (path / "steps").mkdir(mode=PRIVATE_DIR)
        write_atomic(path / "session.json", meta.model_dump_json(indent=2))
        # The session directory and `sessions/` are durable once their own entries are.
        sync_dir(self._dir)
        sync_dir(self._dir.parent)
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
        write_atomic(target, step.model_dump_json(by_alias=True, indent=2))

    def update_step(self, session_id: str, step: Step) -> None:
        if step.status == "running":
            raise ValueError("a running step cannot be persisted")
        target = self._session_dir(session_id) / "steps" / f"{step.index:04d}.json"
        if not target.exists():
            raise KeyError(step.id)
        write_atomic(target, step.model_dump_json(by_alias=True, indent=2))

    def next_index(self, session_id: str) -> int:
        return len(list((self._dir / session_id / "steps").glob("*.json")))

    def _session_dir(self, session_id: str) -> Path:
        path = self._dir / session_id
        if not (path / "session.json").exists():
            raise KeyError(session_id)
        return path
