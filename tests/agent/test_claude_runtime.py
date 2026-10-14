"""Replay Claude SDK sessions against Quarry's real execution boundary."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from typing import Any

import claude_agent_sdk as sdk
import pytest
from mcp.types import CallToolRequest, CallToolRequestParams, ListToolsRequest

from quarry.agent.claude_runtime import ClaudeRuntime
from quarry.agent.tools import ToolExecutor
from quarry.agent.transpile import NoopTranspiler
from quarry.agent.types import ProviderError
from quarry.components.library import ComponentLibrary
from quarry.kernel.client import KernelClient


def terminal(**values: Any) -> Any:
    return sdk.ResultMessage(
        **{
            "subtype": "success",
            "duration_ms": 1,
            "duration_api_ms": 1,
            "is_error": False,
            "num_turns": 1,
            "session_id": "synthetic",
            "stop_reason": "end_turn",
            "result": "done",
            **values,
        }
    )


@pytest.fixture
def executor(tmp_path: Path) -> Iterator[ToolExecutor]:
    kernel = KernelClient.spawn(tmp_path)
    yield ToolExecutor(
        kernel=kernel,
        library=ComponentLibrary([tmp_path / "none"]),
        transpiler=NoopTranspiler(),
    )
    kernel.close()


class Replay:
    def __init__(self) -> None:
        self.events: list[Any] = [terminal()]
        self.options: list[Any] = []
        self.definitions: dict[str, Any] = {}
        self.closed = 0
        self.interrupted = 0
        self.started = threading.Event()
        self.wait = False
        self.cancel: threading.Event | None = None
        self.concurrent = False
        self.background = False
        self.pending: list[asyncio.Task[Any]] = []
        self.failed = threading.Event()

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        replay = self

        class Client:
            def __init__(self, options: Any) -> None:
                self.options = options
                replay.options.append(options)

            async def connect(self) -> None:
                if self.options.mcp_servers:
                    server = self.options.mcp_servers["quarry"]["instance"]
                    result = await server.request_handlers[ListToolsRequest](
                        ListToolsRequest(method="tools/list")
                    )
                    replay.definitions = {t.name: t for t in result.root.tools}

            async def call(self, name: str, arguments: dict[str, Any]) -> Any:
                server = self.options.mcp_servers["quarry"]["instance"]
                return await server.request_handlers[CallToolRequest](
                    CallToolRequest(
                        method="tools/call",
                        params=CallToolRequestParams(
                            name=name,
                            arguments=arguments,
                        ),
                    )
                )

            async def query(self, prompt: str) -> None:
                replay.started.set()

            async def interrupt(self) -> None:
                replay.interrupted += 1

            async def disconnect(self) -> None:
                replay.closed += 1
                if replay.pending:
                    await asyncio.gather(*replay.pending, return_exceptions=True)

            async def receive_response(self) -> AsyncIterator[Any]:
                yield sdk.SystemMessage("init", {"tools": self.options.allowed_tools})
                for event in replay.events:
                    if isinstance(event, tuple):
                        name, arguments = event
                        if replay.background:
                            replay.pending.append(asyncio.create_task(self.call(name, arguments)))
                            await asyncio.sleep(0.02)
                        elif replay.concurrent:
                            await asyncio.gather(*(self.call(name, arg) for arg in arguments))
                        else:
                            await self.call(name, arguments)
                    elif isinstance(event, Exception):
                        replay.failed.set()
                        raise event
                    else:
                        yield event
                if replay.wait:
                    await asyncio.sleep(60)

        monkeypatch.setattr(sdk, "ClaudeSDKClient", Client)
        monkeypatch.setattr(ClaudeRuntime, "_check_cli", lambda self: None)


@pytest.fixture
def replay(monkeypatch: pytest.MonkeyPatch) -> Replay:
    replay = Replay()
    replay.install(monkeypatch)
    return replay


def run(replay: Replay, executor: ToolExecutor, cancel: threading.Event | None = None) -> Any:
    return ClaudeRuntime(model="claude-sonnet-5", cli_path=Path("/native/claude")).run_step(
        prompt="load",
        system="sys",
        summary="summary",
        tools=executor,
        cancel=cancel or threading.Event(),
    )


def test_records_runtime_resolved_model(replay: Replay, executor: ToolExecutor) -> None:
    replay.events = [
        sdk.AssistantMessage(content=[sdk.TextBlock("ready")], model="claude-resolved"),
        terminal(),
    ]
    assert run(replay, executor).model == "claude-resolved"


def test_native_options_exclude_customizations_and_billing_overrides(
    replay: Replay, executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "synthetic-key")
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://synthetic.invalid")
    monkeypatch.setenv("CLAUDE_CODE_USE_BEDROCK", "1")
    monkeypatch.setenv("CLAUDE_CODE_SIMPLE", "1")
    out = run(replay, executor)
    assert out.status == "ok"
    options = replay.options[0]
    assert options.cli_path == Path("/native/claude")
    assert options.tools == [] and options.strict_mcp_config
    assert options.setting_sources == [] and options.skills == []
    assert options.env["ANTHROPIC_API_KEY"] == ""
    assert options.env["ANTHROPIC_BASE_URL"] == ""
    assert options.env["CLAUDE_CODE_USE_BEDROCK"] == ""
    assert options.env["CLAUDE_CODE_SIMPLE"] == ""
    assert "HOME" not in options.env
    assert "bare" not in options.extra_args
    assert "safe-mode" in options.extra_args
    assert set(replay.definitions) == {
        "run_python",
        "describe_dataset",
        "search_components",
        "render_view",
        "write_view",
    }


def test_success_dispatches_real_kernel_and_normalizes_transcript(
    replay: Replay, executor: ToolExecutor
) -> None:
    replay.events = [("run_python", {"code": "frame = pl.DataFrame({'a': [1]})"}), terminal()]
    out = run(replay, executor)
    assert out.status == "ok" and out.note == "done"
    assert out.code == "frame = pl.DataFrame({'a': [1]})"
    call = next(m.tool_calls[0] for m in out.transcript if m.tool_calls)
    result = next(m.tool_results[0] for m in out.transcript if m.tool_results)
    assert call.id == result.call_id
    assert '"frame"' in result.content
    assert replay.closed == 1


@pytest.mark.parametrize(
    "final, error",
    [
        (terminal(is_error=True, result="monthly spend limit"), "monthly spend limit"),
        (terminal(stop_reason="max_tokens", result="partial"), "truncated"),
        (terminal(stop_reason="refusal", result="declined"), "declined"),
        (terminal(subtype="error_max_turns", result=None), "error_max_turns"),
        (RuntimeError("transport lost"), "transport lost"),
    ],
)
def test_failure_keeps_completed_runs(
    replay: Replay, executor: ToolExecutor, final: Any, error: str
) -> None:
    replay.events = [("run_python", {"code": "x = 1"}), final]
    out = run(replay, executor)
    assert out.status == "error" and error in out.error_message
    assert out.code == "x = 1" and len(out.runs) == 1
    assert replay.closed == 1


def test_two_python_failures_stop_queued_concurrent_callbacks(
    replay: Replay, executor: ToolExecutor
) -> None:
    replay.concurrent = True
    replay.events = [
        ("run_python", [{"code": "1/0"}, {"code": "1/0"}, {"code": "x = 1"}]),
        terminal(),
    ]
    out = run(replay, executor)
    assert out.status == "error" and "ZeroDivisionError" in out.error_message
    assert [r.code for r in out.runs] == ["1/0", "1/0"]


def test_thirteenth_tool_never_executes(replay: Replay, executor: ToolExecutor) -> None:
    replay.events = [("run_python", {"code": f"x = {i}"}) for i in range(13)] + [terminal()]
    out = run(replay, executor)
    assert out.status == "error" and len(out.runs) == 12
    assert out.runs[-1].code == "x = 11"


def test_model_wait_cancels_and_closes(replay: Replay, executor: ToolExecutor) -> None:
    replay.events = []
    replay.wait = True
    cancel = threading.Event()

    def cancel_after_start() -> None:
        replay.started.wait(2)
        cancel.set()

    timer = threading.Thread(target=cancel_after_start)
    timer.start()
    out = run(replay, executor, cancel)
    timer.join()
    assert out.status == "interrupted"
    assert replay.interrupted == 1 and replay.closed == 1


def test_missing_terminal_is_protocol_failure(replay: Replay, executor: ToolExecutor) -> None:
    replay.events = []
    out = run(replay, executor)
    assert out.status == "error" and "terminal" in out.error_message


@pytest.mark.parametrize(
    "stop, expected", [("end_turn", "end"), ("max_tokens", "max_tokens"), ("refusal", "refusal")]
)
def test_text_completion_retains_terminal_status_without_tools(
    replay: Replay, stop: str, expected: str
) -> None:
    replay.events = [terminal(stop_reason=stop, result="words")]
    runtime = ClaudeRuntime(model="claude-sonnet-5", cli_path=Path("/native/claude"))
    turn = runtime.complete_text(system="tidy", prompt="source", cancel=threading.Event())
    assert turn.stop == expected and turn.text == "words" and turn.tool_calls == []
    assert replay.options[0].mcp_servers == {} and replay.options[0].tools == []
    runtime.complete_text(system="tidy", prompt="source", cancel=threading.Event())
    assert len(replay.options) == 2 and replay.options[0] is not replay.options[1]


def test_text_operational_error_is_not_retryable(replay: Replay) -> None:
    replay.events = [terminal(is_error=True, result="authentication failed")]
    with pytest.raises(ProviderError, match="authentication failed") as caught:
        ClaudeRuntime(model="model", cli_path=Path("/native/claude")).complete_text(
            system="tidy",
            prompt="source",
            cancel=threading.Event(),
        )
    assert not caught.value.retryable


def test_cancel_waits_for_active_callback_and_keeps_its_transcript(
    replay: Replay, executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release, returned = threading.Event(), threading.Event(), threading.Event()
    cancel = threading.Event()
    original = executor.run

    def blocking(call: Any) -> Any:
        entered.set()
        assert release.wait(3)
        return original(call)

    monkeypatch.setattr(executor, "run", blocking)
    replay.events = [("run_python", {"code": "x = 1"}), terminal()]
    outcome: list[Any] = []

    def worker() -> None:
        outcome.append(run(replay, executor, cancel))
        returned.set()

    thread = threading.Thread(target=worker)
    thread.start()
    try:
        assert entered.wait(3)
        cancel.set()
        assert not returned.wait(0.2)
        release.set()
        thread.join(3)
        assert returned.is_set()
        assert outcome[0].status == "interrupted"
        assert outcome[0].runs[0].code == "x = 1"
        assert any(m.tool_results for m in outcome[0].transcript)
    finally:
        release.set()
        thread.join(3)


def test_non_python_callback_does_not_reset_failure_count(
    replay: Replay, executor: ToolExecutor
) -> None:
    replay.events = [
        ("run_python", {"code": "1/0"}),
        ("describe_dataset", {"name": "missing"}),
        ("run_python", {"code": "1/0"}),
        ("run_python", {"code": "x = 1"}),
        terminal(),
    ]
    out = run(replay, executor)
    assert out.status == "error" and len(out.runs) == 2
    assert "ZeroDivisionError" in out.error_message


def test_malformed_python_arguments_never_reach_kernel(
    replay: Replay, executor: ToolExecutor
) -> None:
    replay.events = [("run_python", {}), ("run_python", {}), terminal()]
    out = run(replay, executor)
    assert out.status == "error" and out.runs == []
    assert any(r.is_error for m in out.transcript for r in m.tool_results)


def test_unexpected_tool_inventory_fails_before_dispatch(
    replay: Replay, executor: ToolExecutor
) -> None:
    replay.events = [
        sdk.SystemMessage("init", {"tools": ["Bash"]}),
        ("run_python", {"code": "x = 1"}),
        terminal(),
    ]
    out = run(replay, executor)
    assert out.status == "error" and "unexpected tools" in out.error_message
    assert out.runs == []


def test_unknown_stop_reason_is_operational_failure(replay: Replay) -> None:
    replay.events = [terminal(stop_reason="unrecognized")]
    with pytest.raises(ProviderError, match="Unknown"):
        ClaudeRuntime(model="model").complete_text(
            system="",
            prompt="",
            cancel=threading.Event(),
        )


def test_disconnect_failure_becomes_step_error(
    replay: Replay, executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def disconnect(self: Any) -> None:
        raise RuntimeError("close failed")

    monkeypatch.setattr(sdk.ClaudeSDKClient, "disconnect", disconnect)
    out = run(replay, executor)
    assert out.status == "error" and "close failed" in out.error_message


def test_terminal_only_answer_is_recorded_in_step_transcript(
    replay: Replay, executor: ToolExecutor
) -> None:
    out = run(replay, executor)
    assert out.transcript[-1].role == "assistant" and out.transcript[-1].text == "done"


def test_cancel_during_connect_closes_without_waiting_for_model(
    replay: Replay, executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()

    async def connect(self: Any) -> None:
        cancel.set()
        await asyncio.sleep(60)

    monkeypatch.setattr(sdk.ClaudeSDKClient, "connect", connect)
    # Bound the failing implementation without relying on a model response.
    original = sdk.ClaudeSDKClient.connect
    expired = threading.Event()

    async def bounded_connect(self: Any) -> None:
        try:
            await asyncio.wait_for(original(self), timeout=0.3)
        except TimeoutError:
            expired.set()
            raise

    monkeypatch.setattr(sdk.ClaudeSDKClient, "connect", bounded_connect)
    out = run(replay, executor, cancel)
    assert not expired.is_set()
    assert out.status == "interrupted"
    assert replay.closed == 1 and replay.interrupted == 0


def test_cancel_during_auth_preflight_does_not_create_session(
    replay: Replay, executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    cancel = threading.Event()
    monkeypatch.setattr(ClaudeRuntime, "_check_cli", lambda self: cancel.set())
    out = run(replay, executor, cancel)
    assert out.status == "interrupted" and replay.options == []


@pytest.mark.parametrize(
    "status",
    [
        {"loggedIn": False},
        {"loggedIn": True, "authMethod": "api_key", "apiProvider": "firstParty"},
        {"loggedIn": True, "authMethod": "claude.ai", "apiProvider": "bedrock"},
    ],
)
def test_native_auth_rejects_non_subscription_status(
    monkeypatch: pytest.MonkeyPatch, status: dict[str, Any]
) -> None:
    import json
    import subprocess

    def command(args: list[str], **kwargs: Any) -> subprocess.CompletedProcess[str]:
        output = "2.1.299 (Claude Code)" if args[-1] == "--version" else json.dumps(status)
        return subprocess.CompletedProcess(args, 0, stdout=output, stderr="")

    monkeypatch.setattr(subprocess, "run", command)
    with pytest.raises(ProviderError, match="subscription login"):
        ClaudeRuntime(model="model")._check_cli()


def test_native_cli_rejects_unprobed_version(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    monkeypatch.setattr(
        subprocess,
        "run",
        lambda *args, **kwargs: subprocess.CompletedProcess(args, 0, stdout="2.1.300", stderr=""),
    )
    with pytest.raises(ProviderError, match="has not passed"):
        ClaudeRuntime(model="model")._check_cli()


def test_transport_failure_closes_dispatch_before_active_callback_settles(
    replay: Replay, executor: ToolExecutor, monkeypatch: pytest.MonkeyPatch
) -> None:
    entered, release = threading.Event(), threading.Event()
    original = executor.run

    def blocking(call: Any) -> Any:
        entered.set()
        assert release.wait(3)
        return original(call)

    monkeypatch.setattr(executor, "run", blocking)
    replay.background = True
    replay.events = [
        ("run_python", {"code": "x = 1"}),
        ("run_python", {"code": "x = 2"}),
        RuntimeError("native crashed"),
    ]
    outcomes: list[Any] = []
    worker = threading.Thread(target=lambda: outcomes.append(run(replay, executor)))
    worker.start()
    try:
        assert entered.wait(3) and replay.failed.wait(3)
        release.set()
        worker.join(3)
        assert not worker.is_alive()
        assert outcomes[0].status == "error" and "native crashed" in outcomes[0].error_message
        assert [r.code for r in outcomes[0].runs] == ["x = 1"]
    finally:
        release.set()
        worker.join(3)


def test_real_mcp_invalid_python_calls_consume_repair_policy(
    replay: Replay, executor: ToolExecutor
) -> None:
    replay.events = [("run_python", {}) for _ in range(13)] + [
        ("run_python", {"code": "x = 1"}),
        terminal(),
    ]
    out = run(replay, executor)
    assert out.status == "error" and out.runs == []
    results = [r for message in out.transcript for r in message.tool_results]
    assert len(results) == 2 and all(result.is_error for result in results)


def test_real_mcp_invalid_non_python_calls_consume_tool_budget(
    replay: Replay, executor: ToolExecutor
) -> None:
    replay.events = [("describe_dataset", {}) for _ in range(13)] + [
        ("run_python", {"code": "x = 1"}),
        terminal(),
    ]
    out = run(replay, executor)
    assert out.status == "error" and "cap reached" in out.error_message
    assert out.runs == []
    assert sum(len(message.tool_results) for message in out.transcript) == 12


def test_real_mcp_advertises_required_python_code_schema(
    replay: Replay, executor: ToolExecutor
) -> None:
    run(replay, executor)
    schema = replay.definitions["run_python"].inputSchema
    assert schema["type"] == "object" and schema["required"] == ["code"]
    assert schema["properties"]["code"]["type"] == "string"
