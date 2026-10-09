"""Session, step, and view records as persisted on disk."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from quarry.agent.tools import CodeRun, PendingView
from quarry.agent.types import Message
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import ExecError
from quarry.query.spec import Json

StepKind = Literal["prompt", "manual", "load", "recall"]
StepStatus = Literal["running", "ok", "error", "interrupted"]


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def new_id() -> str:
    return secrets.token_hex(6)


class Snapshot(BaseModel):
    ts: str
    state: dict[str, Json]
    queries: list[dict[str, Json]]


class View(BaseModel):
    component_id: str
    content_hash: str
    source: str
    initial_state: dict[str, Json] = Field(default_factory=dict)
    datasets: list[str] = Field(default_factory=list)
    snapshots: list[Snapshot] = Field(default_factory=list)

    @classmethod
    def from_pending(cls, pending: PendingView) -> View:
        digest = hashlib.sha256(pending.source.encode("utf-8")).hexdigest()
        return cls(
            component_id=pending.component_id,
            content_hash=digest,
            source=pending.source,
            initial_state=pending.initial_state,
            datasets=pending.datasets,
        )


class Step(BaseModel):
    id: str
    index: int
    kind: StepKind
    prompt: str | None
    code: str
    # Each execution in order; restart replays these, not `code`.
    runs: list[CodeRun] = Field(default_factory=list)
    status: StepStatus
    error: ExecError | None
    note: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    defines: list[str] = Field(default_factory=list)
    datasets: list[DatasetMeta] = Field(default_factory=list)
    view: View | None = None
    transcript: list[Message] | None = None
    created_at: str
    duration_ms: int = 0


class ProviderInfo(BaseModel):
    name: str
    model: str


class KernelStatus(BaseModel):
    status: Literal["starting", "idle", "running", "dead"]
    pid: int | None = None
    replay_needed: bool = False


class SessionMeta(BaseModel):
    id: str
    title: str
    created_at: str
    provider: ProviderInfo


class Session(BaseModel):
    meta: SessionMeta
    steps: list[Step]
