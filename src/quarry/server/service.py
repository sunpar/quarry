"""Session operations: one running step per session, executed on a background thread."""

from __future__ import annotations

import builtins
import logging
import threading
import time
from collections.abc import Callable
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
from quarry.kernel.executor import TAIL_BYTES, ExecError, ExecResult, QueryResult
from quarry.query.spec import QuerySpec
from quarry.server.kernels import KernelManager, ReplayReport, SessionBusy
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

log = logging.getLogger(__name__)
# Past this wait, a step still running at shutdown is lost, as in a crash.
SHUTDOWN_WAIT_SECONDS: Final = 10.0

ProviderFactory = Callable[[QuarryConfig], Provider]


def provider_from_config(config: QuarryConfig) -> Provider:
    if config.provider.name == "openai":
        return OpenAIProvider.from_config(config)
    return AnthropicProvider.from_config(config)


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
        # A session in here has a running step, which its event cancels.
        self._running: dict[str, Step] = {}
        self._cancels: dict[str, threading.Event] = {}
        # A session in here is restarting: stopping its running step, then replaying.
        self._restarts: set[str] = set()
        self._last_error: dict[str, str] = {}
        self._lock = threading.Lock()
        # Notified each time a step frees its session, which a restart waits for.
        self._released = threading.Condition(self._lock)

    def create(self, title: str) -> SessionMeta:
        return self._store.create(title=title, provider=self._provider_info())

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
        step, cancel = self._begin(session_id, kind="prompt", prompt=prompt, code="")
        self._start(session_id, self._run_prompt, (session_id, step, prompt, cancel))
        return step

    def start_manual(self, session_id: str, code: str) -> Step:
        step, cancel = self._begin(session_id, kind="manual", prompt=None, code=code)
        self._start(session_id, self._run_manual, (session_id, step, cancel))
        return step

    def status(self, session_id: str) -> SessionStatus:
        running = self._running.get(session_id)
        return SessionStatus(
            session_id=session_id,
            running_step=running.id if running else None,
            kernel=self._kernels.status(session_id),
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
        listed = self._kernel(session_id).list_datasets()
        # Later steps overwrite earlier ones, so each name keeps its latest writer.
        origins = {n: step.id for step in self._store.get(session_id).steps for n in step.writes}
        return [d.model_copy(update={"origin_step": origins.get(d.name)}) for d in listed]

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
        """The kernel a request reaches; SessionBusy mid-restart, as `get` is during the replay."""
        with self._lock:
            if session_id in self._restarts:
                raise SessionBusy(session_id)
        return self._kernels.get(session_id)

    def shutdown(self) -> None:
        """Stop every running step and close the kernels, then give the steps time to save."""
        with self._lock:
            for cancel in self._cancels.values():
                cancel.set()
        self._kernels.close_all()
        with self._lock:
            self._released.wait_for(lambda: not self._running, SHUTDOWN_WAIT_SECONDS)

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
                provider=self._provider_info() if kind == "prompt" else None,
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

    def _provider_info(self) -> ProviderInfo:
        return ProviderInfo(name=self._config.provider.name, model=self._config.provider.model)

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
        ran: list[tuple[str, ExecResult]] = []
        try:
            provider = self._provider_factory(self._config)
            kernel = self._kernels.get(session_id)
            tools = ToolExecutor(kernel=kernel, library=self._library, transpiler=self._transpiler)
            ran = tools.runs
            summary = build_summary(self._store.get(session_id).steps, _safe_datasets(kernel))
            outcome = run_agent_step(
                prompt=prompt,
                system=build_system(self._system_context()),
                summary=summary,
                provider=provider,
                tools=tools,
                cancel=cancel,
            )
            error = (
                ExecError(type="StepError", message=outcome.error_message, traceback="")
                if outcome.error_message
                else None
            )
            done = _ended(
                _recorded(step, ran),
                started,
                status=outcome.status,
                note=outcome.note,
                code=outcome.code,
                error=error,
                transcript=outcome.transcript,
                view=View.from_pending(outcome.view) if outcome.view else None,
            )
        except KernelDead as exc:
            done = _died(step, exc, cancel, started)
        # The step thread's boundary: anything else would leave the session busy for good. It
        # takes NOT_FAILURES and polars panics too, since nothing above this thread can.
        except BaseException as exc:
            # What ran stays with the step: restart replays it, and its writes name this step.
            done = _recorded(_failed(step, ExecError.from_exception(exc), started), ran)
        self._finish(session_id, done)

    def _run_manual(self, session_id: str, step: Step, cancel: threading.Event) -> None:
        started = time.monotonic()
        try:
            kernel = self._kernels.get(session_id)
            # A restart cancels, then kills the kernel: one it found none to kill may be new.
            if cancel.is_set():
                done = _stopped(step, started)
            else:
                done = _apply_exec(step, kernel.execute(step.code), started)
        except KernelDead as exc:
            done = _died(step, exc, cancel, started)
        except BaseException as exc:  # the boundary, as in _run_prompt
            done = _failed(step, ExecError.from_exception(exc), started)
        self._finish(session_id, done)

    def _finish(self, session_id: str, step: Step) -> None:
        # The kernel describes datasets without knowing steps; this step wrote the ones it lists.
        listed = [d.model_copy(update={"origin_step": step.id}) for d in step.datasets]
        step = step.model_copy(update={"datasets": listed})
        with self._lock:
            # A restart cancels its running step and kills the kernel, so the step ends
            # interrupted, whichever of the two stopped it.
            if step.status == "interrupted" and session_id in self._restarts:
                stopped = ExecError(type="Restart", message="stopped by a restart", traceback="")
                step = step.model_copy(update={"error": stopped})
            error = step.error.message if step.error is not None else None
            try:
                self._store.append_step(session_id, step)
            except BaseException as exc:
                error = f"failed to save step: {exc}"
                # The files lack what the kernel ran: dead until a restart replays the files.
                self._kernels.kill(session_id)
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
            enabled_libraries=enabled_libraries(self._config),
        )


def _apply_exec(step: Step, result: ExecResult, started: float) -> Step:
    return _ended(
        step,
        started,
        status=result.status,
        runs=[CodeRun(code=step.code, status=result.status)],
        error=result.error,
        stdout_tail=result.stdout_tail,
        stderr_tail=result.stderr_tail,
        reads=result.reads,
        writes=result.writes,
        defines=result.defines,
        datasets=result.datasets,
    )


def _recorded(step: Step, ran: list[tuple[str, ExecResult]]) -> Step:
    """`step` with the runs a prompt step made, for replay, their output, and the lineage
    they fold to."""
    lineage = step_lineage([result for _, result in ran])
    return step.model_copy(
        update={
            "runs": [CodeRun(code=code, status=result.status) for code, result in ran],
            "stdout_tail": "".join(result.stdout_tail for _, result in ran)[-TAIL_BYTES:],
            "stderr_tail": "".join(result.stderr_tail for _, result in ran)[-TAIL_BYTES:],
            "reads": lineage.reads,
            "writes": lineage.writes,
            "defines": lineage.defines,
            "datasets": lineage.datasets,
        }
    )


def _ended(step: Step, started: float, **update: object) -> Step:
    """`step` as it finished: `update` applied, and its duration since `started`."""
    duration_ms = int((time.monotonic() - started) * 1000)
    return step.model_copy(update={**update, "duration_ms": duration_ms})


def _failed(step: Step, error: ExecError, started: float) -> Step:
    return _ended(step, started, status="error", error=error)


def _stopped(step: Step, started: float) -> Step:
    return _ended(step, started, status="interrupted")


def _died(step: Step, exc: KernelDead, cancel: threading.Event, started: float) -> Step:
    """The step whose kernel died. Once cancelled it was stopped instead: a restart cancels the
    step before it kills the kernel."""
    if cancel.is_set():
        return _stopped(step, started)
    error = ExecError(type="KernelDead", message=f"kernel died: {exc}", traceback="")
    return _failed(step, error, started)


def _safe_datasets(kernel: KernelClient) -> list[DatasetMeta]:
    try:
        return kernel.list_datasets()
    except KernelDead:
        return []
