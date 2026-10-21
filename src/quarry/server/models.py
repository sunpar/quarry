"""Session, step, and view records as persisted on disk."""

from __future__ import annotations

import hashlib
import secrets
from collections.abc import Mapping
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


def to_code_input(
    state: Mapping[str, Json], queries: list[dict[str, Json]]
) -> tuple[list[dict[str, Json]], list[str]]:
    """What "To code" and an export render for a view, and what that leaves out. A `spec` in its
    state wins over its queries, which for the pivot are an arrow load and a one-row probe, and
    `dropped` lists what the spec cannot say."""
    spec, dropped = state.get("spec"), state.get("dropped")
    rendered = (
        [spec] if isinstance(spec, dict) and isinstance(spec.get("dataset"), str) else queries
    )
    if isinstance(dropped, list) and all(isinstance(d, str) for d in dropped):
        return rendered, [str(d) for d in dropped]
    return rendered, []


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

    def shown(self, back: int) -> tuple[dict[str, Json], list[dict[str, Json]]]:
        """The state and queries of the snapshot `back` before the latest: 0 is what the view shows
        now, its initial state before it has reported one, and more is one the researcher picked
        in the history. Counted back because the oldest drop off past the cap while the host's
        cached list keeps them until a refetch. ValueError when there is no such snapshot."""
        if back == 0 and not self.snapshots:
            return self.initial_state, []
        if not 0 <= back < len(self.snapshots):
            raise ValueError(f"no snapshot {back} back")
        picked = self.snapshots[-1 - back]
        return picked.state, picked.queries

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


class ProviderInfo(BaseModel):
    name: str
    model: str


class Step(BaseModel):
    id: str
    index: int
    kind: StepKind
    prompt: str | None
    # The model a prompt step called; config can change between a session's steps.
    provider: ProviderInfo | None = None
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
