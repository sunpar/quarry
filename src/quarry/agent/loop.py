"""One prompt step: call the provider, dispatch tools, repeat until it stops."""

from __future__ import annotations

import json
import threading
from typing import Final, Literal

from pydantic import BaseModel

from quarry.agent.tools import TOOL_DEFS, CodeRun, PendingView, ToolExecutor
from quarry.agent.types import Message, Provider, ProviderError, ToolCall, ToolResult
from quarry.kernel.client import KernelDead
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import ExecResult

MAX_ITERATIONS: Final = 12
_INTERRUPTED: Final = "interrupted by researcher"

StepStatus = Literal["ok", "error", "interrupted"]


class StepOutcome(BaseModel):
    status: StepStatus
    note: str
    transcript: list[Message]
    error_message: str | None
    view: PendingView | None
    # The run_python blocks that succeeded, for reading; restart replays `runs`.
    code: str
    runs: list[CodeRun]
    iterations: int | None
    model: str | None = None


class StepHalted(Exception):
    def __init__(self, status: StepStatus, message: str) -> None:
        super().__init__(message)
        self.status = status
        self.message = message


class StepExecution:
    """Serialize Quarry tool execution and construct its authoritative outcome."""

    def __init__(
        self,
        *,
        tools: ToolExecutor,
        cancel: threading.Event,
        max_tool_calls: int | None = None,
    ) -> None:
        self._tools = tools
        self._cancel = cancel
        self._max_tool_calls = max_tool_calls
        self._tool_calls = 0
        self._python_failures = 0
        self._lock = threading.Lock()
        self._state_lock = threading.Lock()
        self.halt: tuple[StepStatus, str] | None = None

    def stop(self, status: StepStatus, message: str) -> None:
        """Close dispatch at the terminal trigger without waiting for an executing tool."""
        with self._state_lock:
            if self._cancel.is_set():
                status, message = "interrupted", _INTERRUPTED
            if (
                self.halt is None
                or status == "interrupted"
                or (self.halt[0] == "ok" and status == "error")
            ):
                self.halt = (status, message)

    def dispatch(self, call: ToolCall) -> ToolResult:
        with self._lock:
            if self._cancel.is_set():
                self.stop("interrupted", _INTERRUPTED)
            if self.halt is not None:
                raise StepHalted(*self.halt)
            if self._max_tool_calls is not None and self._tool_calls >= self._max_tool_calls:
                error = f"tool dispatch cap reached ({self._max_tool_calls})"
                self.stop("error", error)
                raise StepHalted("error", error)
            self._tool_calls += 1
            try:
                result = self._tools.run(call)
            except KernelDead as exc:
                error = "kernel died during execution"
                self.stop("error", error)
                raise StepHalted("error", error) from exc
            if self._cancel.is_set() or any(r.status == "interrupted" for _, r in self._tools.runs):
                self.stop("interrupted", _INTERRUPTED)
            elif call.name == "run_python":
                self._python_failures = self._python_failures + 1 if result.is_error else 0
                if self._python_failures >= 2:
                    self.stop("error", _tool_error(result))
            return result

    def finish(
        self,
        *,
        status: StepStatus,
        transcript: list[Message],
        note: str = "",
        error: str | None = None,
        iterations: int | None = None,
        model: str | None = None,
    ) -> StepOutcome:
        self.stop(status, error or "step finished")
        # Close queued dispatches before awaiting callbacks that can still append runs.
        with self._lock:
            if self._cancel.is_set():
                self.stop("interrupted", _INTERRUPTED)
            if self.halt is not None:
                status = self.halt[0]
                error = self.halt[1] if status != "ok" else None
            return StepOutcome(
                status=status,
                note=note,
                transcript=transcript,
                error_message=error,
                view=self._tools.view,
                code="\n\n".join(code for code, r in self._tools.runs if r.status == "ok"),
                runs=[CodeRun(code=code, status=r.status) for code, r in self._tools.runs],
                iterations=iterations,
                model=model,
            )


class Lineage(BaseModel):
    reads: list[str]
    writes: list[str]
    defines: list[str]
    datasets: list[DatasetMeta]


def step_lineage(results: list[ExecResult]) -> Lineage:
    bound_so_far: set[str] = set()
    reads: set[str] = set()
    writes: set[str] = set()
    defines: set[str] = set()
    latest: dict[str, DatasetMeta] = {}
    for r in results:
        reads |= {n for n in r.reads if n not in bound_so_far}
        writes |= set(r.writes)
        defines |= set(r.defines)
        latest.update({m.name: m for m in r.datasets})
        bound_so_far |= {*r.writes, *r.defines}
    return Lineage(
        reads=sorted(reads),
        writes=sorted(writes),
        defines=sorted(defines),
        datasets=[latest[n] for n in sorted(writes) if n in latest],
    )


def run_agent_step(
    *,
    prompt: str,
    system: str,
    summary: str,
    provider: Provider,
    tools: ToolExecutor,
    cancel: threading.Event,
    max_iterations: int = MAX_ITERATIONS,
) -> StepOutcome:
    """Run one prompt step. Once `cancel` is set it ends as interrupted, before its next provider
    or tool call: no kernel interrupt reaches a step that waits on the model."""
    transcript: list[Message] = [Message(role="user", text=f"{summary}\n\n# Request\n{prompt}")]
    execution = StepExecution(tools=tools, cancel=cancel)
    iterations = 0

    def finish(status: StepStatus, note: str = "", error: str | None = None) -> StepOutcome:
        return execution.finish(
            status=status,
            note=note,
            transcript=transcript,
            error=error,
            iterations=iterations,
        )

    while not cancel.is_set():
        if iterations >= max_iterations:
            return finish("error", error=f"iteration cap reached ({max_iterations})")
        iterations += 1
        try:
            turn = provider.complete(system=system, messages=transcript, tools=TOOL_DEFS)
        except ProviderError as exc:
            return finish("error", error=str(exc))
        transcript.append(turn.as_message())
        if turn.stop == "refusal":
            return finish("error", error=turn.refusal_reason or "request declined")
        if turn.stop == "max_tokens":
            return finish("error", error="response truncated at max_tokens")
        if not turn.tool_calls:
            return finish("ok", note=turn.text)

        results: list[ToolResult] = []
        for call in turn.tool_calls:
            try:
                result = execution.dispatch(call)
            except StepHalted as exc:
                if exc.status == "error":
                    return finish(exc.status, error=exc.message)
                break
            results.append(result)
            if execution.halt is not None:
                break
        # After a halt this holds results for only part of the turn's calls. That is fine:
        # transcripts are shown, never sent to a provider again.
        transcript.append(Message(role="user", tool_results=results))
        if execution.halt is not None:
            return finish(execution.halt[0], error=execution.halt[1])
    return finish("interrupted", error=_INTERRUPTED)


def _tool_error(result: ToolResult) -> str:
    try:
        body = json.loads(result.content)
    except json.JSONDecodeError:
        return result.content
    error = body.get("error")
    if isinstance(error, dict):
        return str(error.get("traceback") or error.get("message") or result.content)
    return str(error or result.content)
