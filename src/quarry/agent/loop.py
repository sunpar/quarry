"""One prompt step: call the provider, dispatch tools, repeat until it stops."""

from __future__ import annotations

import json
from typing import Final, Literal

from pydantic import BaseModel

from quarry.agent.tools import TOOL_DEFS, PendingView, ToolExecutor
from quarry.agent.types import Message, Provider, ProviderError, ToolResult
from quarry.kernel.client import KernelDead
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import ExecResult

MAX_ITERATIONS: Final = 12

StepStatus = Literal["ok", "error", "interrupted"]


class StepOutcome(BaseModel):
    status: StepStatus
    note: str
    transcript: list[Message]
    error_message: str | None
    view: PendingView | None
    # Only the run_python blocks that succeeded: replaying this on a fresh kernel must not fail.
    code: str
    iterations: int
    exec_results: list[ExecResult]


class Lineage(BaseModel):
    reads: list[str]
    writes: list[str]
    defines: list[str]
    datasets: list[DatasetMeta]


def step_lineage(results: list[ExecResult]) -> Lineage:
    written_so_far: set[str] = set()
    reads: set[str] = set()
    writes: set[str] = set()
    defines: set[str] = set()
    latest: dict[str, DatasetMeta] = {}
    for r in results:
        reads |= {n for n in r.reads if n not in written_so_far}
        writes |= set(r.writes)
        defines |= set(r.defines)
        latest.update({m.name: m for m in r.datasets})
        written_so_far |= set(r.writes)
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
    max_iterations: int = MAX_ITERATIONS,
) -> StepOutcome:
    transcript: list[Message] = [Message(role="user", text=f"{summary}\n\n# Request\n{prompt}")]
    code_blocks: list[str] = []
    consecutive_failures = 0
    iterations = 0

    def finish(status: StepStatus, note: str = "", error: str | None = None) -> StepOutcome:
        return StepOutcome(
            status=status,
            note=note,
            transcript=transcript,
            error_message=error,
            view=tools.view,
            code="\n\n".join(code_blocks),
            iterations=iterations,
            exec_results=list(tools.exec_results),
        )

    while iterations < max_iterations:
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
                result = tools.run(call)
            except KernelDead:
                return finish("error", error="kernel died during execution")
            results.append(result)
            if call.name != "run_python":
                continue
            code = call.input.get("code")
            if not result.is_error and isinstance(code, str):
                code_blocks.append(code)
            if any(r.status == "interrupted" for r in tools.exec_results):
                transcript.append(Message(role="user", tool_results=results))
                return finish("interrupted", error="interrupted by researcher")
            consecutive_failures = consecutive_failures + 1 if result.is_error else 0
        transcript.append(Message(role="user", tool_results=results))
        if consecutive_failures >= 2:
            return finish("error", error=_last_traceback(results))
    return finish("error", error=f"iteration cap reached ({max_iterations})")


def _last_traceback(results: list[ToolResult]) -> str:
    for result in reversed(results):
        if result.is_error:
            try:
                body = json.loads(result.content)
            except json.JSONDecodeError:
                return result.content
            error = body.get("error")
            if isinstance(error, dict):
                return str(error.get("traceback") or error.get("message") or result.content)
            return str(error or result.content)
    return "step failed"
