"""Session operations: one running step per session, executed on a background thread."""

from __future__ import annotations

import builtins
import logging
import threading
import time
import traceback
from collections.abc import Callable, Sequence
from typing import Final

from pydantic import BaseModel

from quarry.agent.anthropic_provider import AnthropicProvider
from quarry.agent.context import SystemContext, build_summary, build_system, enabled_libraries
from quarry.agent.loop import run_agent_step, step_lineage
from quarry.agent.openai_provider import OpenAIProvider
from quarry.agent.tools import CodeRun, ToolExecutor
from quarry.agent.transpile import Transpiler
from quarry.agent.types import Provider
from quarry.components.library import ComponentLibrary
from quarry.config import QuarryConfig
from quarry.data.loaders import describe_failures, describe_loaders, load_loaders
from quarry.data.parquet import scan_layout
from quarry.kernel.client import KernelClient, KernelDead
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import ExecError, ExecResult, QueryResult
from quarry.query.spec import Json, QuerySpec
from quarry.server.kernels import KernelManager, ReplayReport
from quarry.server.models import (
    KernelStatus,
    ProviderInfo,
    Session,
    SessionMeta,
    Snapshot,
    Step,
    StepKind,
    View,
    new_id,
    now_iso,
)
from quarry.server.store import SessionStore

log = logging.getLogger(__name__)

MAX_SNAPSHOTS: Final = 500

ProviderFactory = Callable[[QuarryConfig], Provider]


def provider_from_config(config: QuarryConfig) -> Provider:
    if config.provider.name == "openai":
        return OpenAIProvider.from_config(config)
    return AnthropicProvider.from_config(config)


class SessionBusy(Exception):
    pass


class RepairRequest(BaseModel):
    step_id: str
    error: str


class StepRequest(BaseModel):
    prompt: str
    repair: RepairRequest | None = None


class StepNotFound(Exception):
    pass


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
        libraries: list[str] | None = None,
    ) -> None:
        self._config = config
        self._store = store
        self._kernels = kernels
        self._provider_factory = provider_factory
        self._library = library
        self._transpiler = transpiler
        self._libraries = libraries if libraries is not None else enabled_libraries(config)
        # A session in here has a running step, which its event cancels.
        self._running: dict[str, Step] = {}
        self._cancels: dict[str, threading.Event] = {}
        # A session in here is restarting: stopping its running step, then replaying.
        self._restarts: set[str] = set()
        self._last_error: dict[str, str] = {}
        self._lock = threading.Lock()
        # Notified each time a step frees its session, which a restart waits for.
        self._released = threading.Condition(self._lock)
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

    def start_prompt(
        self, session_id: str, prompt: str, repair: RepairRequest | None = None
    ) -> Step:
        text = prompt if repair is None else self._repair_prompt(session_id, repair, prompt)
        step, cancel = self._begin(session_id, kind="prompt", prompt=prompt, code="")
        self._start(session_id, self._run_prompt, (session_id, step, text, cancel))
        return step

    def _repair_prompt(self, session_id: str, repair: RepairRequest, prompt: str) -> str:
        step = self._find_step(session_id, repair.step_id)
        if step.view is None:
            raise StepNotFound(repair.step_id)
        return (
            f"The view from step {step.index + 1} failed to mount in the browser with:\n"
            f"{repair.error}\n\nIts source:\n```tsx\n{step.view.source}\n```\n\n{prompt}"
        )

    def record_snapshot(
        self,
        session_id: str,
        step_id: str,
        state: dict[str, Json],
        queries: builtins.list[dict[str, Json]],
    ) -> int:
        with self._lock:
            running = self._running.get(session_id)
            if running is not None and running.id == step_id:
                raise SessionBusy(session_id)
            step = self._find_step(session_id, step_id)
            if step.view is None:
                raise StepNotFound(step_id)
            snapshots = [*step.view.snapshots, Snapshot(ts=now_iso(), state=state, queries=queries)]
            view = step.view.model_copy(update={"snapshots": snapshots[-MAX_SNAPSHOTS:]})
            self._store.update_step(session_id, step.model_copy(update={"view": view}))
            return len(view.snapshots)

    def _find_step(self, session_id: str, step_id: str) -> Step:
        for step in self._store.get(session_id).steps:
            if step.id == step_id:
                return step
        raise StepNotFound(step_id)

    def start_manual(self, session_id: str, code: str) -> Step:
        step, cancel = self._begin(session_id, kind="manual", prompt=None, code=code)
        self._start(session_id, self._run_manual, (session_id, step, cancel))
        return step

    def status(self, session_id: str) -> SessionStatus:
        running = self._running.get(session_id)
        return SessionStatus(
            session_id=session_id,
            running_step=running.id if running else None,
            kernel=self._kernels.status(session_id, has_steps=self._has_steps(session_id)),
            last_error=self._last_error.get(session_id),
        )

    def interrupt(self, session_id: str) -> bool:
        """Cancel a running prompt step, which may be waiting on the model where no kernel
        interrupt reaches, then interrupt the kernel; False when there was nothing to stop.
        The cancel comes first, so it holds even when a dead kernel raises KernelDead."""
        with self._lock:
            running = self._running.get(session_id)
            cancelled = running is not None and running.kind == "prompt"
            if cancelled:
                self._cancels[session_id].set()
        return self._kernel(session_id).interrupt() or cancelled

    def query(self, session_id: str, spec: QuerySpec) -> QueryResult:
        return self._kernel(session_id).query(spec)

    def datasets(self, session_id: str) -> builtins.list[DatasetMeta]:
        return self._kernel(session_id).list_datasets()

    def restart(self, session_id: str) -> ReplayReport:
        """Replace the kernel and replay the session's steps. Killing the old kernel stops code
        no interrupt reaches, and a running step is cancelled too; it saves itself as interrupted
        before the replay. A step waiting on the model stops once the model answers."""
        with self._lock:
            if session_id in self._restarts:
                raise SessionBusy(session_id)
            self._restarts.add(session_id)
            cancel = self._cancels.get(session_id)
            if cancel is not None:
                cancel.set()
        try:
            self._kernels.kill(session_id)
            with self._lock:
                self._released.wait_for(lambda: session_id not in self._running)
                self._kernels.mark_running(session_id, True)
            return self._kernels.restart(session_id, self._store.get(session_id).steps)
        finally:
            with self._lock:
                self._kernels.mark_running(session_id, False)
                self._restarts.discard(session_id)

    def _kernel(self, session_id: str) -> KernelClient:
        return self._kernels.get(session_id, has_steps=self._has_steps(session_id))

    def _has_steps(self, session_id: str) -> bool:
        return self._store.next_index(session_id) > 0

    def shutdown(self) -> None:
        self._kernels.close_all()

    def _begin(
        self, session_id: str, *, kind: StepKind, prompt: str | None, code: str
    ) -> tuple[Step, threading.Event]:
        with self._lock:
            if session_id in self._running or session_id in self._restarts:
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
            cancel = threading.Event()
            self._running[session_id] = step
            self._cancels[session_id] = cancel
            self._kernels.mark_running(session_id, True)
            return step, cancel

    def _start(
        self, session_id: str, target: Callable[..., None], args: tuple[object, ...]
    ) -> None:
        try:
            threading.Thread(target=target, args=args, daemon=True).start()
        except Exception as exc:
            with self._lock:
                self._release(session_id, f"failed to start step: {exc}")
            raise

    def _run_prompt(
        self, session_id: str, step: Step, prompt: str, cancel: threading.Event
    ) -> None:
        started = time.monotonic()
        tools: ToolExecutor | None = None
        try:
            provider = self._provider_factory(self._config)
            kernel = self._kernel(session_id)
            tools = ToolExecutor(kernel=kernel, library=self._library, transpiler=self._transpiler)
            summary = build_summary(self._store.get(session_id).steps, _safe_datasets(kernel))
            outcome = run_agent_step(
                prompt=prompt,
                system=self._system,
                summary=summary,
                provider=provider,
                tools=tools,
                cancel=cancel,
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
                    "runs": outcome.runs,
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
            done = _died(step, exc, cancel, started)
        # The step thread's boundary: anything else would leave the session busy for good.
        except Exception as exc:
            # The blocks that ran stay with the step, so restart replays them.
            ran = tools.runs if tools is not None else []
            runs = [CodeRun(code=code, status=result.status) for code, result in ran]
            done = _failed(step, _crash(exc), started, runs)
        self._finish(session_id, done)

    def _run_manual(self, session_id: str, step: Step, cancel: threading.Event) -> None:
        started = time.monotonic()
        try:
            kernel = self._kernel(session_id)
            # A restart cancels, then kills the kernel: one it found none to kill may be new.
            if cancel.is_set():
                done = _stopped(step, started)
            else:
                done = _apply_exec(step, kernel.execute(step.code), started)
        except KernelDead as exc:
            done = _died(step, exc, cancel, started)
        # The step thread's boundary: anything else would leave the session busy for good.
        except Exception as exc:
            done = _failed(step, _crash(exc), started)
        self._finish(session_id, done)

    def _finish(self, session_id: str, step: Step) -> None:
        with self._lock:
            # A restart cancels its running step and kills the kernel, so the step ends
            # interrupted, whichever of the two stopped it.
            if step.status == "interrupted" and session_id in self._restarts:
                stopped = ExecError(type="Restart", message="stopped by a restart", traceback="")
                step = step.model_copy(update={"error": stopped})
            error = step.error.message if step.error is not None else None
            try:
                self._store.append_step(session_id, step)
            except Exception as exc:
                error = f"failed to save step: {exc}"
                raise
            finally:
                self._release(session_id, error)

    def _release(self, session_id: str, error: str | None) -> None:
        """Free the session for its next step; the caller holds the lock."""
        self._kernels.mark_running(session_id, False)
        if error is not None:
            self._last_error[session_id] = error
        else:
            self._last_error.pop(session_id, None)
        self._cancels.pop(session_id, None)
        self._released.notify_all()  # waiters wake once the caller lets go of the lock
        # Last: status() reads _running without the lock and treats None as fully finished.
        self._running.pop(session_id, None)

    def _system_context(self) -> SystemContext:
        registry = load_loaders(self._config.root / "loaders.toml")
        failures = describe_failures(registry)
        if failures:
            log.warning("loaders that failed to load:\n%s", failures)
        root = self._config.data.parquet_root
        return SystemContext(
            loaders=describe_loaders(registry),
            loader_failures=failures,
            layout=scan_layout(root) if root is not None else [],
            enabled_libraries=self._libraries,
        )


def _apply_exec(step: Step, result: ExecResult, started: float) -> Step:
    return step.model_copy(
        update={
            "status": result.status,
            "runs": [CodeRun(code=step.code, status=result.status)],
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


def _failed(step: Step, error: ExecError, started: float, runs: Sequence[CodeRun] = ()) -> Step:
    return step.model_copy(
        update={
            "status": "error",
            "error": error,
            "runs": list(runs),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    )


def _stopped(step: Step, started: float) -> Step:
    return step.model_copy(
        update={"status": "interrupted", "duration_ms": int((time.monotonic() - started) * 1000)}
    )


def _died(step: Step, exc: KernelDead, cancel: threading.Event, started: float) -> Step:
    """The step whose kernel died. Once cancelled it was stopped instead: a restart cancels the
    step before it kills the kernel."""
    if cancel.is_set():
        return _stopped(step, started)
    error = ExecError(type="KernelDead", message=f"kernel died: {exc}", traceback="")
    return _failed(step, error, started)


def _crash(exc: Exception) -> ExecError:
    trace = "".join(traceback.format_exception(exc))
    return ExecError(type=type(exc).__name__, message=str(exc), traceback=trace)


def _safe_datasets(kernel: KernelClient) -> list[DatasetMeta]:
    try:
        return kernel.list_datasets()
    except KernelDead:
        return []
