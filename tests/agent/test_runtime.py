import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from quarry.agent.fake import FakeProvider
from quarry.agent.loop import StepExecution, StepHalted, StepOutcome
from quarry.agent.runtime import ApiRuntime
from quarry.agent.tools import ToolExecutor
from quarry.agent.transpile import NoopTranspiler
from quarry.agent.types import AssistantTurn, Message, ProviderError, ToolCall, ToolDef, ToolResult
from quarry.components.library import ComponentLibrary
from quarry.kernel.client import KernelClient, KernelDead


@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ToolExecutor]:
    kernel = KernelClient.spawn(tmp_path)
    yield ToolExecutor(
        kernel=kernel,
        library=ComponentLibrary([tmp_path / "none"]),
        transpiler=NoopTranspiler(),
    )
    kernel.close()


def python_call(call_id: str, code: str) -> ToolCall:
    return ToolCall(id=call_id, name="run_python", input={"code": code})


@pytest.mark.parametrize("stop", ["end", "max_tokens", "refusal"])
def test_api_text_completion_keeps_stop_status(stop: str) -> None:
    turn = AssistantTurn.model_validate(
        {"text": "answer", "tool_calls": [], "stop": stop, "refusal_reason": "declined"}
    )
    provider = FakeProvider([turn])
    out = ApiRuntime(provider).complete_text(system="sys", prompt="tidy", cancel=threading.Event())
    assert out == turn
    assert provider.calls == [("sys", [Message(role="user", text="tidy")], [])]


@pytest.mark.parametrize("during", [False, True])
def test_api_text_completion_rejects_cancellation(during: bool) -> None:
    cancel = threading.Event()

    class CancelProvider(FakeProvider):
        def complete(
            self, *, system: str, messages: list[Message], tools: list[ToolDef]
        ) -> AssistantTurn:
            cancel.set()
            return super().complete(system=system, messages=messages, tools=tools)

    provider = CancelProvider([AssistantTurn(text="done", tool_calls=[], stop="end")])
    if not during:
        cancel.set()
    with pytest.raises(ProviderError) as failed:
        ApiRuntime(provider).complete_text(system="s", prompt="p", cancel=cancel)
    assert failed.value.retryable is False
    assert len(provider.calls) == int(during)


def test_api_text_completion_propagates_provider_failure() -> None:
    class FailingProvider:
        def complete(
            self, *, system: str, messages: list[Message], tools: list[ToolDef]
        ) -> AssistantTurn:
            raise ProviderError("rate limited", retryable=True)

    with pytest.raises(ProviderError, match="rate limited") as failed:
        ApiRuntime(FailingProvider()).complete_text(
            system="sys", prompt="tidy", cancel=threading.Event()
        )
    assert failed.value.retryable is True


def test_cancel_before_dispatch_skips_python(executor: ToolExecutor) -> None:
    cancel = threading.Event()
    cancel.set()
    step = StepExecution(tools=executor, cancel=cancel)
    with pytest.raises(StepHalted) as halted:
        step.dispatch(python_call("python", "x = 1"))
    assert halted.value.status == "interrupted"
    assert executor.runs == []
    assert step.finish(status="ok", transcript=[]).status == "interrupted"


def test_python_success_resets_failures(executor: ToolExecutor) -> None:
    step = StepExecution(tools=executor, cancel=threading.Event())
    for i, code in enumerate(["1/0", "x = 1", "1/0", "x = 2"]):
        step.dispatch(python_call(str(i), code))
    out = step.finish(status="ok", transcript=[], note="done")
    assert out.status == "ok" and out.code == "x = 1\n\nx = 2"
    assert [r.status for r in out.runs] == ["error", "ok", "error", "ok"]
    assert out.iterations is None


def test_non_python_failure_does_not_count_as_python_failure(executor: ToolExecutor) -> None:
    step = StepExecution(tools=executor, cancel=threading.Event())
    assert step.dispatch(ToolCall(id="unknown", name="unknown", input={})).is_error
    assert step.dispatch(python_call("first", "1/0")).is_error
    assert step.halt is None
    assert not step.dispatch(python_call("repair", "x = 1")).is_error


def test_native_thirteenth_tool_dispatch_never_executes(executor: ToolExecutor) -> None:
    step = StepExecution(tools=executor, cancel=threading.Event(), max_tool_calls=12)
    for i in range(12):
        step.dispatch(python_call(str(i), f"x = {i}"))
    with pytest.raises(StepHalted) as halted:
        step.dispatch(python_call("thirteenth", "x = 99"))
    assert halted.value.status == "error"
    assert "12" in halted.value.message
    out = step.finish(status="ok", transcript=[])
    assert out.status == "error" and len(out.runs) == 12
    assert out.runs[-1].code == "x = 11"


def test_native_budget_counts_non_python_calls(executor: ToolExecutor) -> None:
    step = StepExecution(tools=executor, cancel=threading.Event(), max_tool_calls=1)
    step.dispatch(ToolCall(id="search", name="search_components", input={"dataset": ""}))
    with pytest.raises(StepHalted):
        step.dispatch(python_call("python", "x = 1"))
    assert executor.runs == []


def test_second_python_failure_blocks_queued_callback(
    executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release, queued = threading.Event(), threading.Event(), threading.Event()
    run = executor.run

    def blocked_run(call: ToolCall) -> ToolResult:
        if call.id == "second":
            entered.set()
            assert release.wait(5)
        return run(call)

    monkeypatch.setattr(executor, "run", blocked_run)
    step = StepExecution(tools=executor, cancel=threading.Event())
    step.dispatch(python_call("first", "1/0"))

    def queued_dispatch() -> ToolResult:
        queued.set()
        return step.dispatch(python_call("third", "x = 99"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        second = pool.submit(step.dispatch, python_call("second", "1/0"))
        assert entered.wait(5)
        third = pool.submit(queued_dispatch)
        assert queued.wait(5)
        release.set()
        assert second.result(timeout=5).is_error
        with pytest.raises(StepHalted) as halted:
            third.result(timeout=5)
    assert halted.value.status == "error"
    assert "ZeroDivisionError" in halted.value.message
    assert [code for code, _ in executor.runs] == ["1/0", "1/0"]


def test_finish_waits_for_executing_tool_after_adapter_failure(
    executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release, finishing = threading.Event(), threading.Event(), threading.Event()
    run = executor.run

    def blocked_run(call: ToolCall) -> ToolResult:
        entered.set()
        assert release.wait(5)
        return run(call)

    monkeypatch.setattr(executor, "run", blocked_run)
    step = StepExecution(tools=executor, cancel=threading.Event())

    def finish() -> StepOutcome:
        finishing.set()
        return step.finish(status="error", transcript=[], error="native process exited")

    with ThreadPoolExecutor(max_workers=2) as pool:
        running = pool.submit(step.dispatch, python_call("python", "x = 1"))
        assert entered.wait(5)
        outcome = pool.submit(finish)
        assert finishing.wait(5)
        assert not outcome.done()
        release.set()
        running.result(timeout=5)
        out = outcome.result(timeout=5)
    assert out.status == "error" and out.error_message == "native process exited"
    assert out.code == "x = 1" and [(r.code, r.status) for r in out.runs] == [("x = 1", "ok")]
    with pytest.raises(StepHalted):
        step.dispatch(python_call("late", "x = 2"))


def test_cancel_during_execution_keeps_completed_python_run(
    executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    run = executor.run

    def cancelling_run(call: ToolCall) -> ToolResult:
        cancel.set()
        return run(call)

    monkeypatch.setattr(executor, "run", cancelling_run)
    step = StepExecution(tools=executor, cancel=cancel)
    assert not step.dispatch(python_call("python", "x = 1")).is_error
    with pytest.raises(StepHalted) as halted:
        step.dispatch(python_call("late", "x = 2"))
    assert halted.value.status == "interrupted"
    out = step.finish(status="error", transcript=[], error="native process exited")
    assert out.status == "interrupted" and out.code == "x = 1"


def test_kernel_death_closes_dispatch(
    executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    def dead_run(call: ToolCall) -> ToolResult:
        raise KernelDead("kernel exited")

    monkeypatch.setattr(executor, "run", dead_run)
    step = StepExecution(tools=executor, cancel=threading.Event())
    with pytest.raises(StepHalted) as halted:
        step.dispatch(python_call("python", "x = 1"))
    assert halted.value.status == "error" and "kernel died" in halted.value.message
    out = step.finish(status="ok", transcript=[])
    assert out.status == "error" and out.runs == []


def test_stop_closes_queued_dispatch_before_active_callback_settles(
    executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release, queued = threading.Event(), threading.Event(), threading.Event()
    run = executor.run

    def blocked_run(call: ToolCall) -> ToolResult:
        if call.id == "active":
            entered.set()
            assert release.wait(5)
        return run(call)

    monkeypatch.setattr(executor, "run", blocked_run)
    step = StepExecution(tools=executor, cancel=threading.Event())

    def queued_dispatch() -> ToolResult:
        queued.set()
        return step.dispatch(python_call("queued", "x = 2"))

    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(step.dispatch, python_call("active", "x = 1"))
        assert entered.wait(5)
        pending = pool.submit(queued_dispatch)
        assert queued.wait(5)
        try:
            step.stop("error", "transport died")
            assert step.halt == ("error", "transport died")
        finally:
            release.set()
        assert not active.result(timeout=5).is_error
        with pytest.raises(StepHalted, match="transport died"):
            pending.result(timeout=5)
    out = step.finish(status="ok", transcript=[])
    assert out.status == "error" and out.error_message == "transport died"
    assert out.code == "x = 1" and len(out.runs) == 1


def test_finish_closes_dispatch_before_waiting_for_active_callback(
    executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release, collecting = threading.Event(), threading.Event(), threading.Event()
    run = executor.run

    def blocked_run(call: ToolCall) -> ToolResult:
        entered.set()
        assert release.wait(5)
        return run(call)

    class ObservedLock:
        def __init__(self) -> None:
            self.lock = threading.Lock()
            self.entries = 0

        def __enter__(self) -> None:
            self.entries += 1
            if self.entries == 2:
                collecting.set()
            self.lock.acquire()

        def __exit__(self, *args: object) -> None:
            self.lock.release()

    monkeypatch.setattr(executor, "run", blocked_run)
    step = StepExecution(tools=executor, cancel=threading.Event())
    monkeypatch.setattr(step, "_lock", ObservedLock())
    with ThreadPoolExecutor(max_workers=2) as pool:
        active = pool.submit(step.dispatch, python_call("active", "x = 1"))
        assert entered.wait(5)
        pending = pool.submit(step.finish, status="error", transcript=[], error="transport died")
        assert collecting.wait(5)
        try:
            assert step.halt == ("error", "transport died")
        finally:
            release.set()
        active.result(timeout=5)
        out = pending.result(timeout=5)
    assert out.status == "error" and out.code == "x = 1"


def test_executing_python_failure_overrides_completion_trigger(
    executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    run = executor.run

    def blocked_run(call: ToolCall) -> ToolResult:
        if call.id == "second":
            entered.set()
            assert release.wait(5)
        return run(call)

    monkeypatch.setattr(executor, "run", blocked_run)
    step = StepExecution(tools=executor, cancel=threading.Event())
    step.dispatch(python_call("first", "1/0"))
    with ThreadPoolExecutor(max_workers=1) as pool:
        active = pool.submit(step.dispatch, python_call("second", "1/0"))
        assert entered.wait(5)
        step.stop("ok", "native completed")
        release.set()
        assert active.result(timeout=5).is_error
    out = step.finish(status="ok", transcript=[])
    assert out.status == "error" and "ZeroDivisionError" in (out.error_message or "")
    assert [r.status for r in out.runs] == ["error", "error"]
