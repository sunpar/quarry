"""Session operations: one running step per session, executed on a background thread."""

from __future__ import annotations

import builtins
import threading
import time
import traceback
from collections.abc import Callable

from pydantic import BaseModel

from quarry.agent.anthropic_provider import AnthropicProvider
from quarry.agent.context import SystemContext, build_summary, build_system, enabled_libraries
from quarry.agent.loop import run_agent_step, step_lineage
from quarry.agent.openai_provider import OpenAIProvider
from quarry.agent.tools import ToolExecutor
from quarry.agent.transpile import Transpiler
from quarry.agent.types import Provider
from quarry.components.library import ComponentLibrary
from quarry.config import QuarryConfig
from quarry.data.loaders import describe_loaders, load_loaders
from quarry.data.parquet import scan_layout
from quarry.kernel.client import KernelClient, KernelDead
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import ExecError, ExecResult, QueryResult
from quarry.query.spec import QuerySpec
from quarry.server.kernels import KernelManager, ReplayReport
from quarry.server.models import (
    KernelStatus,
    ProviderInfo,
    Session,
    SessionMeta,
    Step,
    StepKind,
    View,
    new_id,
    now_iso,
)
from quarry.server.store import SessionStore

ProviderFactory = Callable[[QuarryConfig], Provider]


def provider_from_config(config: QuarryConfig) -> Provider:
    if config.provider.name == "openai":
        return OpenAIProvider.from_config(config)
    return AnthropicProvider.from_config(config)


class SessionBusy(Exception):
    pass


class StepRequest(BaseModel):
    prompt: str


class ManualStepRequest(BaseModel):
    code: str


class CreateSessionRequest(BaseModel):
    title: str = "Untitled"


class SessionStatus(BaseModel):
    session_id: str
    running_step: str | None
    kernel: KernelStatus
    last_error: str | None


class SessionService:
    def __init__(
        self,
        *,
        config: QuarryConfig,
        store: SessionStore,
        kernels: KernelManager,
        provider_factory: ProviderFactory,
        library: ComponentLibrary,
        transpiler: Transpiler,
    ) -> None:
        self._config = config
        self._store = store
        self._kernels = kernels
        self._provider_factory = provider_factory
        self._library = library
        self._transpiler = transpiler
        # A session in here is busy: its running step, or None while a restart replays.
        self._running: dict[str, Step | None] = {}
        self._last_error: dict[str, str] = {}
        self._lock = threading.Lock()
        self._system = build_system(self._system_context())

    def create(self, title: str) -> SessionMeta:
        info = ProviderInfo(name=self._config.provider.name, model=self._config.provider.model)
        return self._store.create(title=title, provider=info)

    def list(self) -> list[SessionMeta]:
        return self._store.list()

    def get(self, session_id: str) -> Session:
        # Under the lock: _finish persists a step and drops it from _running in one move.
        with self._lock:
            session = self._store.get(session_id)
            running = self._running.get(session_id)
        if running is not None:
            session.steps.append(running)
        return session

    def start_prompt(self, session_id: str, prompt: str) -> Step:
        step = self._begin(session_id, kind="prompt", prompt=prompt, code="")
        threading.Thread(
            target=self._run_prompt, args=(session_id, step, prompt), daemon=True
        ).start()
        return step

    def start_manual(self, session_id: str, code: str) -> Step:
        step = self._begin(session_id, kind="manual", prompt=None, code=code)
        threading.Thread(target=self._run_manual, args=(session_id, step), daemon=True).start()
        return step

    def status(self, session_id: str) -> SessionStatus:
        self._store.get(session_id)
        running = self._running.get(session_id)
        return SessionStatus(
            session_id=session_id,
            running_step=running.id if running else None,
            kernel=self._kernels.status(session_id),
            last_error=self._last_error.get(session_id),
        )

    def interrupt(self, session_id: str) -> None:
        self._kernels.get(session_id).interrupt()

    def query(self, session_id: str, spec: QuerySpec) -> QueryResult:
        self._store.get(session_id)
        return self._kernels.get(session_id).query(spec)

    def datasets(self, session_id: str) -> builtins.list[DatasetMeta]:
        self._store.get(session_id)
        return self._kernels.get(session_id).list_datasets()

    def restart(self, session_id: str) -> ReplayReport:
        with self._lock:
            if session_id in self._running:
                raise SessionBusy(session_id)
            self._running[session_id] = None
            self._kernels.mark_running(session_id, True)
        try:
            steps = [s for s in self._store.get(session_id).steps if s.status == "ok" and s.code]
            return self._kernels.restart(session_id, steps)
        finally:
            with self._lock:
                self._running.pop(session_id, None)
                self._kernels.mark_running(session_id, False)

    def shutdown(self) -> None:
        self._kernels.close_all()

    def _begin(self, session_id: str, *, kind: StepKind, prompt: str | None, code: str) -> Step:
        with self._lock:
            if session_id in self._running:
                raise SessionBusy(session_id)
            step = Step(
                id=new_id(),
                index=self._store.next_index(session_id),
                kind=kind,
                prompt=prompt,
                code=code,
                status="running",
                error=None,
                created_at=now_iso(),
            )
            self._running[session_id] = step
            self._kernels.mark_running(session_id, True)
            return step

    def _run_prompt(self, session_id: str, step: Step, prompt: str) -> None:
        started = time.monotonic()
        try:
            provider = self._provider_factory(self._config)
            kernel = self._kernels.get(session_id)
            tools = ToolExecutor(kernel=kernel, library=self._library, transpiler=self._transpiler)
            summary = build_summary(self._store.get(session_id).steps, _safe_datasets(kernel))
            outcome = run_agent_step(
                prompt=prompt, system=self._system, summary=summary, provider=provider, tools=tools
            )
            lineage = step_lineage(outcome.exec_results)
            error = (
                ExecError(type="StepError", message=outcome.error_message, traceback="")
                if outcome.error_message
                else None
            )
            done = step.model_copy(
                update={
                    "status": outcome.status,
                    "note": outcome.note,
                    "code": outcome.code,
                    "error": error,
                    "transcript": outcome.transcript,
                    "view": View.from_pending(outcome.view) if outcome.view else None,
                    "reads": lineage.reads,
                    "writes": lineage.writes,
                    "defines": lineage.defines,
                    "datasets": lineage.datasets,
                    "duration_ms": int((time.monotonic() - started) * 1000),
                }
            )
        except KernelDead as exc:
            done = _failed(step, _death(exc), started)
        # The step thread's boundary: anything else would leave the session busy for good.
        except Exception as exc:
            done = _failed(step, _crash(exc), started)
        self._finish(session_id, done)

    def _run_manual(self, session_id: str, step: Step) -> None:
        started = time.monotonic()
        try:
            result = self._kernels.get(session_id).execute(step.code)
            done = _apply_exec(step, result, started)
        except KernelDead as exc:
            done = _failed(step, _death(exc), started)
        # The step thread's boundary: anything else would leave the session busy for good.
        except Exception as exc:
            done = _failed(step, _crash(exc), started)
        self._finish(session_id, done)

    def _finish(self, session_id: str, step: Step) -> None:
        with self._lock:
            self._store.append_step(session_id, step)
            self._running.pop(session_id, None)
            self._kernels.mark_running(session_id, False)
            if step.error is not None:
                self._last_error[session_id] = step.error.message
            else:
                self._last_error.pop(session_id, None)

    def _system_context(self) -> SystemContext:
        registry = load_loaders(self._config.root / "loaders.toml")
        root = self._config.data.parquet_root
        return SystemContext(
            loaders=describe_loaders(registry),
            layout=scan_layout(root) if root is not None else [],
            enabled_libraries=enabled_libraries(self._config),
        )


def _apply_exec(step: Step, result: ExecResult, started: float) -> Step:
    return step.model_copy(
        update={
            "status": result.status,
            "error": result.error,
            "stdout_tail": result.stdout_tail,
            "stderr_tail": result.stderr_tail,
            "reads": result.reads,
            "writes": result.writes,
            "defines": result.defines,
            "datasets": result.datasets,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    )


def _failed(step: Step, error: ExecError, started: float) -> Step:
    return step.model_copy(
        update={
            "status": "error",
            "error": error,
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    )


def _death(exc: KernelDead) -> ExecError:
    return ExecError(type="KernelDead", message=f"kernel died: {exc}", traceback="")


def _crash(exc: Exception) -> ExecError:
    trace = "".join(traceback.format_exception(exc))
    return ExecError(type=type(exc).__name__, message=str(exc), traceback=trace)


def _safe_datasets(kernel: KernelClient) -> list[DatasetMeta]:
    try:
        return kernel.list_datasets()
    except KernelDead:
        return []
