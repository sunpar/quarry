import json
import threading
from collections.abc import Iterator
from pathlib import Path

import pytest

from quarry.agent.fake import FakeProvider
from quarry.agent.loop import StepOutcome, run_agent_step, step_lineage
from quarry.agent.tools import ToolExecutor
from quarry.agent.transpile import NoopTranspiler
from quarry.agent.types import AssistantTurn, Message, ProviderError, ToolCall, ToolDef
from quarry.components.library import ComponentLibrary
from quarry.kernel.client import KernelClient
from quarry.kernel.executor import ExecResult


@pytest.fixture
def kernel(tmp_path: Path) -> Iterator[KernelClient]:
    client = KernelClient.spawn(tmp_path)
    yield client
    client.close()


def tools(kernel: KernelClient, tmp_path: Path) -> ToolExecutor:
    return ToolExecutor(
        kernel=kernel,
        library=ComponentLibrary([tmp_path / "none"]),
        transpiler=NoopTranspiler(),
    )


def py(call_id: str, code: str) -> AssistantTurn:
    call = ToolCall(id=call_id, name="run_python", input={"code": code})
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def end(text: str = "done") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], stop="end")


def run(
    provider: FakeProvider,
    kernel: KernelClient,
    tmp_path: Path,
    cancel: threading.Event | None = None,
    **kw: int,
) -> StepOutcome:
    return run_agent_step(
        prompt="load",
        system="sys",
        summary="# Session so far",
        provider=provider,
        tools=tools(kernel, tmp_path),
        cancel=cancel or threading.Event(),
        **kw,
    )


def test_happy_path_runs_code_and_records_transcript(kernel: KernelClient, tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", "df = pl.DataFrame({'a': [1]})"), end("loaded")])
    out = run(provider, kernel, tmp_path)
    assert out.status == "ok" and out.note == "loaded"
    assert out.code == "df = pl.DataFrame({'a': [1]})"
    assert out.iterations == 2
    assert [m.role for m in out.transcript] == ["user", "assistant", "user", "assistant"]
    first = out.transcript[0].text
    assert first.startswith("# Session so far") and first.endswith("# Request\nload")
    assert json.loads(out.transcript[2].tool_results[0].content)["writes"] == ["df"]


def test_second_consecutive_python_error_ends_step(kernel: KernelClient, tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", "1/0"), py("c2", "1/0"), end()])
    out = run(provider, kernel, tmp_path)
    assert out.status == "error"
    assert out.error_message is not None and "ZeroDivisionError" in out.error_message
    assert out.iterations == 2
    assert len(provider.calls) == 2
    result_messages = [m for m in out.transcript if m.tool_results]
    assert len(result_messages) == 2
    for message in result_messages:
        assert message.role == "user"
        assert all(r.is_error and "ZeroDivisionError" in r.content for r in message.tool_results)


def test_one_error_then_success_is_ok(kernel: KernelClient, tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", "1/0"), py("c2", "x = 1"), end()])
    assert run(provider, kernel, tmp_path).status == "ok"


def test_code_shows_ok_blocks_and_runs_keep_every_block(
    kernel: KernelClient, tmp_path: Path
) -> None:
    provider = FakeProvider([py("c1", "1/0"), py("c2", "x = 1"), end()])
    out = run(provider, kernel, tmp_path)
    assert out.status == "ok"
    assert out.code == "x = 1"
    assert [(r.code, r.status) for r in out.runs] == [("1/0", "error"), ("x = 1", "ok")]


def test_second_failure_stops_the_rest_of_the_turn(kernel: KernelClient, tmp_path: Path) -> None:
    calls = [
        ToolCall(id=f"c{i}", name="run_python", input={"code": code})
        for i, code in enumerate(["1/0", "1/0", "x = 1"])
    ]
    provider = FakeProvider([AssistantTurn(text="", tool_calls=calls, stop="tool_use"), end()])
    out = run(provider, kernel, tmp_path)
    assert out.status == "error"
    assert [r.code for r in out.runs] == ["1/0", "1/0"]


def test_refusal_and_truncation(kernel: KernelClient, tmp_path: Path) -> None:
    declined = AssistantTurn(text="", tool_calls=[], stop="refusal", refusal_reason="no")
    refused = run(FakeProvider([declined]), kernel, tmp_path)
    assert refused.status == "error" and refused.error_message == "no"
    cut = AssistantTurn(text="partial", tool_calls=[], stop="max_tokens")
    truncated = run(FakeProvider([cut]), kernel, tmp_path)
    assert truncated.status == "error" and "truncated" in (truncated.error_message or "")


def test_iteration_cap(kernel: KernelClient, tmp_path: Path) -> None:
    provider = FakeProvider([py(f"c{i}", "x = 1") for i in range(5)])
    out = run(provider, kernel, tmp_path, max_iterations=3)
    assert out.status == "error" and "iteration cap" in (out.error_message or "")
    assert out.iterations == 3


def test_provider_error_fails_step(kernel: KernelClient, tmp_path: Path) -> None:
    class Boom:
        def complete(
            self, *, system: str, messages: list[Message], tools: list[ToolDef]
        ) -> AssistantTurn:
            raise ProviderError("rate limited", retryable=True)

    out = run_agent_step(
        prompt="p",
        system="s",
        summary="",
        provider=Boom(),
        tools=tools(kernel, tmp_path),
        cancel=threading.Event(),
    )
    assert out.status == "error" and out.error_message == "rate limited"


def test_interrupted_python_marks_step_interrupted(kernel: KernelClient, tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", "raise KeyboardInterrupt"), end()])
    assert run(provider, kernel, tmp_path).status == "interrupted"


def test_cancel_before_a_provider_call_skips_it(kernel: KernelClient, tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    provider = FakeProvider([end()])
    out = run(provider, kernel, tmp_path, cancel)
    assert out.status == "interrupted" and out.error_message == "interrupted by researcher"
    assert provider.calls == [] and out.iterations == 0


def test_cancel_during_a_provider_call_skips_its_tools(
    kernel: KernelClient, tmp_path: Path
) -> None:
    cancel = threading.Event()

    class CancelsOnSecondCall(FakeProvider):
        def complete(
            self, *, system: str, messages: list[Message], tools: list[ToolDef]
        ) -> AssistantTurn:
            turn = super().complete(system=system, messages=messages, tools=tools)
            if len(self.calls) == 2:
                cancel.set()
            return turn

    provider = CancelsOnSecondCall([py("c1", "x = 1"), py("c2", "y = 2"), end()])
    out = run(provider, kernel, tmp_path, cancel)
    assert out.status == "interrupted" and out.error_message == "interrupted by researcher"
    assert [r.code for r in out.runs] == ["x = 1"] and len(provider.calls) == 2


def test_step_lineage_self_rebinding_keeps_read_edge() -> None:
    def res(reads: list[str], writes: list[str]) -> ExecResult:
        return ExecResult(
            status="ok",
            stdout_tail="",
            stderr_tail="",
            error=None,
            reads=reads,
            writes=writes,
            defines=[],
            datasets=[],
            duration_ms=0,
        )

    one = step_lineage([res(["df"], ["df"])])
    assert one.reads == ["df"] and one.writes == ["df"]
    two = step_lineage([res([], ["tmp"]), res(["tmp", "prices"], ["out"])])
    assert two.reads == ["prices"] and two.writes == ["out", "tmp"]


def test_view_is_captured(kernel: KernelClient, tmp_path: Path) -> None:
    write_view = ToolCall(
        id="c2",
        name="write_view",
        input={
            "source": "export default () => null",
            "datasets": ["df"],
            "initial_state": "{}",
        },
    )
    turns = [
        py("c1", "df = pl.DataFrame({'a': [1]})"),
        AssistantTurn(text="", tool_calls=[write_view], stop="tool_use"),
        end(),
    ]
    out = run(FakeProvider(turns), kernel, tmp_path)
    assert out.view is not None and out.view.component_id == "inline"
