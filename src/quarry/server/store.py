"""Sessions on disk: one directory per session, one JSON file per completed step."""

from __future__ import annotations

from pathlib import Path

from quarry.server.models import ProviderInfo, Session, SessionMeta, Step, new_id, now_iso


class SessionStore:
    def __init__(self, root: Path) -> None:
        self._dir = root / "sessions"

    def create(self, *, title: str, provider: ProviderInfo) -> SessionMeta:
        meta = SessionMeta(id=new_id(), title=title, created_at=now_iso(), provider=provider)
        path = self._dir / meta.id
        (path / "steps").mkdir(parents=True)
        (path / "session.json").write_text(meta.model_dump_json(indent=2))
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
        target.write_text(step.model_dump_json(by_alias=True, indent=2))

    def next_index(self, session_id: str) -> int:
        return len(list((self._dir / session_id / "steps").glob("*.json")))

    def _session_dir(self, session_id: str) -> Path:
        path = self._dir / session_id
        if not (path / "session.json").exists():
            raise KeyError(session_id)
        return path
