import json
import os
import signal
import sys
import threading
import time
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import pytest

from quarry.agent.codex_runtime import CodexRuntime, _Connection
from quarry.agent.loop import StepOutcome
from quarry.agent.tools import TOOL_DEFS, ToolExecutor
from quarry.agent.transpile import NoopTranspiler
from quarry.agent.types import ProviderError, ToolCall, ToolResult
from quarry.components.library import ComponentLibrary
from quarry.config import ProviderConfig, QuarryConfig
from quarry.kernel.client import KernelClient
from quarry.projects.tidy import tidy_recipe
from tests.components.test_library import write_component
from tests.kernel.test_client import exits_soon

_FAKE = r"""
import json, os, signal, sys, time
from pathlib import Path

if "--version" in sys.argv:
    print("codex-cli " + os.environ.get("QUARRY_CODEX_VERSION", "0.162.1"))
    sys.exit()
plan = json.loads(Path(os.environ["QUARRY_CODEX_PLAN"]).read_text())
log = Path(os.environ["QUARRY_CODEX_LOG"])


def record(value):
    with log.open("a") as out:
        out.write(json.dumps(value) + "\n")


def send(value):
    print(json.dumps(value), flush=True)


def notify(method, params):
    send({"method": method, "params": params})


def terminal():
    notify(
        "item/agentMessage/delta",
        {"threadId": "thread", "turnId": "turn", "itemId": "answer", "delta": "done"},
    )
    for item in plan.get("messages", [{"type":"agentMessage","id":"answer","text":"done"}]):
        notify("item/completed", {"threadId":"thread","turnId":"turn","item":item})
    notify(
        "turn/completed",
        {
            "threadId": "thread",
            "turn": plan.get("terminal_payload", {
                "id": "turn",
                "status": plan.get("terminal", "completed"),
                "error": plan.get("error"),
            }),
        },
    )


def terminate(*_):
    record({"terminated": True})
    sys.exit()


signal.signal(signal.SIGTERM, terminate)
record(
    {
        "pid": os.getpid(),
        "args": sys.argv[1:],
        "api_env": any(
            k in os.environ for k in ["OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"]
        ),
    }
)
remaining = len(plan.get("calls", []))
for line in sys.stdin:
    req = json.loads(line)
    record(req)
    method = req.get("method")
    rid = req.get("id")
    if method == "initialize":
        notify("noise", {"interleaved": True})
        send({"id": rid, "result": {"userAgent": "Codex/0.162.1"}})
    elif method == "account/read":
        send(
            {
                "id": rid,
                "result": {
                    "account": {"type": plan.get("auth", "chatgpt")},
                    "requiresOpenaiAuth": True,
                },
            }
        )
    elif method == "config/read":
        effective = {
            "model_catalog_json": next(
                a.split("=", 1)[1].strip('"')
                for a in sys.argv
                if a.startswith("model_catalog_json=")
            ),
            "features": {},
        }
        for arg in sys.argv:
            if arg.startswith("features.") and arg.endswith("=false"):
                effective["features"][arg.split(".", 1)[1].split("=")[0]] = False
        effective.update(plan.get("config", {}))
        effective["mcp_servers"] = {
            "inherited": {"command": "untrusted", "env": {"SECRET": "never expose"}}
        }
        send({"id": rid, "result": {"config": effective}})
    elif method == "mcpServerStatus/list":
        send({"id": rid, "result": {"data": plan.get("mcp_status", []), "nextCursor": None}})
    elif method == "thread/start":
        catalog = json.loads(
            Path(
                next(
                    a.split("=", 1)[1].strip('"')
                    for a in sys.argv
                    if a.startswith("model_catalog_json=")
                )
            ).read_text()
        )
        record({"catalog": catalog})
        send(
            {
                "id": rid,
                "result": {
                    "thread": {"id": "thread", "environments": req["params"]["environments"]},
                    "model": req["params"]["model"],
                    "modelProvider": "openai",
                },
            }
        )
    elif method == "turn/start":
        if plan.get("rpc_error"):
            send({"id": rid, "error": {"message": plan["rpc_error"]}})
            continue
        events = plan.get("calls", [])
        if not plan.get("before_ack"):
            send({"id": rid, "result": {"turn": {"id": "turn", "status": "inProgress"}}})
        for i, call in enumerate(events):
            send(
                {
                    "id": "tool-" + str(i),
                    "method": "item/tool/call",
                    "params": {
                        "threadId": "thread",
                        "turnId": "turn",
                        "callId": "call-" + str(i),
                        "tool": call["name"],
                        "arguments": call["input"],
                    },
                }
            )
        if plan.get("before_ack"):
            send({"id": rid, "result": {"turn": {"id": "turn", "status": "inProgress"}}})
        if plan.get("block_reads"):
            while True:
                time.sleep(.1)
        if plan.get("crash_marker"):
            while not Path(plan["crash_marker"]).exists():
                time.sleep(0.005)
            sys.exit(7)
        if plan.get("malformed"):
            print("not-json", flush=True)
        elif plan.get("foreign"):
            notify(
                "item/completed",
                {
                    "threadId": "foreign",
                    "turnId": "turn",
                    "item": {"type": "agentMessage", "id": "answer", "text": "contaminated"},
                },
            )
        elif plan.get("crash"):
            sys.exit(7)
        elif not events and not plan.get("wait"):
            terminal()
    elif method == "turn/interrupt":
        send({"id": rid, "result": {}})
        notify(
            "turn/completed",
            {"threadId": "thread", "turn": {"id": "turn", "status": "interrupted", "error": None}},
        )
    elif "result" in req:
        remaining -= 1
        if remaining == 0 and not plan.get("wait"):
            terminal()
"""


@pytest.fixture
def codex_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Path, Path, Path]]:
    binary, plan, log = (tmp_path / name for name in ("codex-fake", "codex-plan", "codex-log"))
    binary.write_text(f"#!{sys.executable}\n{_FAKE}")
    binary.chmod(0o700)
    plan.write_text("{}")
    monkeypatch.setenv("QUARRY_CODEX_PLAN", str(plan))
    monkeypatch.setenv("QUARRY_CODEX_LOG", str(log))
    yield binary, plan, log


@pytest.fixture
def codex_tools(tmp_path: Path) -> Iterator[ToolExecutor]:
    kernel = KernelClient.spawn(tmp_path / "kernel")
    write_component(tmp_path / "lib", "table", ["table"], [])
    yield ToolExecutor(
        kernel=kernel,
        library=ComponentLibrary([tmp_path / "lib"]),
        transpiler=NoopTranspiler(),
    )
    kernel.close()


def records(log: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in log.read_text().splitlines()]


def step(cli: Path, tools: ToolExecutor, cancel: threading.Event | None = None) -> StepOutcome:
    return CodexRuntime(model="gpt-6.1-sol", cli_path=cli).run_step(
        prompt="load",
        system="sys",
        summary="summary",
        tools=tools,
        cancel=cancel or threading.Event(),
    )


def test_text_completion_uses_fresh_private_capability_catalog(
    codex_cli: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    cli, _, log = codex_cli
    monkeypatch.setenv("OPENAI_API_KEY", "never-forward")
    runtime = CodexRuntime(model="gpt-6.1-sol", cli_path=cli)
    for _ in range(2):
        out = runtime.complete_text(system="sys", prompt="tidy", cancel=threading.Event())
        assert out.text == "done" and out.stop == "end" and out.tool_calls == []
    entries = records(log)
    starts = [r["params"] for r in entries if r.get("method") == "thread/start"]
    assert len(starts) == 2 and starts[0]["cwd"] != starts[1]["cwd"]
    for start in starts:
        assert start["ephemeral"] and start["environments"] == []
        assert start["dynamicTools"] == [] and not start["allowProviderModelFallback"]
        assert start["modelProvider"] == "openai"
        assert start["config"]["mcp_servers"]["inherited"]["enabled"] is False
        assert not Path(start["cwd"]).exists()
    catalogs = [r["catalog"]["models"][0] for r in entries if "catalog" in r]
    assert len(catalogs) == 2
    assert all(m["tool_mode"] == "direct" and m["shell_type"] == "disabled" for m in catalogs)
    assert all(m["experimental_supported_tools"] == [] for m in catalogs)
    assert all(m["slug"] == "gpt-6.1-sol" for m in catalogs)
    children = [r for r in entries if "args" in r]
    assert all(not r["api_env"] for r in children)
    assert all("agents.enabled=false" in r["args"] for r in children)
    assert "never expose" not in log.read_text()


def test_step_dispatches_only_quarry_tools_and_deduplicates_text(
    codex_cli: tuple[Path, Path, Path], codex_tools: ToolExecutor
) -> None:
    cli, plan, log = codex_cli
    plan.write_text(
        json.dumps(
            {
                "before_ack": True,
                "calls": [
                    {"name": "run_python", "input": {"code": "df = pl.DataFrame({'a':[1]})"}},
                    {"name": "describe_dataset", "input": {"name": "df"}},
                ],
            }
        )
    )
    out = step(cli, codex_tools)
    assert out.status == "ok" and out.note == "done" and out.iterations is None
    assert out.model == "gpt-6.1-sol"
    assert len(out.runs) == 1 and out.runs[0].status == "ok"
    assert sum(m.text == "done" for m in out.transcript) == 1
    results = [r for m in out.transcript for r in m.tool_results]
    assert len(results) == 2 and not any(r.is_error for r in results)
    starts = [r["params"] for r in records(log) if r.get("method") == "thread/start"]
    assert [t["name"] for t in starts[0]["dynamicTools"]] == [t.name for t in TOOL_DEFS]


@pytest.mark.parametrize(
    "plan_data,expected",
    [
        ({"auth": "apiKey"}, "ChatGPT"),
        ({"rpc_error": "quota exceeded"}, "quota"),
        ({"malformed": True}, "malformed"),
        ({"foreign": True}, "thread"),
        ({"crash": True}, "exited"),
        ({"terminal": "failed", "error": {"message": "rate limit"}}, "rate limit"),
    ],
)
def test_operational_failures_are_explicit(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
    plan_data: dict[str, Any],
    expected: str,
) -> None:
    cli, plan, _ = codex_cli
    plan.write_text(json.dumps(plan_data))
    out = step(cli, codex_tools)
    assert out.status == "error" and out.error is not None and expected in out.error.message
    with pytest.raises(ProviderError) as failed:
        CodexRuntime(model="gpt-6.1-sol", cli_path=cli).complete_text(
            system="s", prompt="p", cancel=threading.Event()
        )
    assert failed.value.retryable is False


def test_unsupported_cli_fails_before_start(
    codex_cli: tuple[Path, Path, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    cli, _, log = codex_cli
    monkeypatch.setenv("QUARRY_CODEX_VERSION", "0.999.0")
    with pytest.raises(ProviderError, match=r"0\.162\.1"):
        CodexRuntime(model="gpt-6.1-sol", cli_path=cli).complete_text(
            system="s", prompt="p", cancel=threading.Event()
        )
    assert not log.exists()


def test_from_config_keeps_explicit_model_and_binary(codex_cli: tuple[Path, Path, Path]) -> None:
    cli, _, _ = codex_cli
    config = QuarryConfig(
        root=cli.parent, provider=ProviderConfig(name="codex", model="chosen", cli_path=cli)
    )
    runtime = CodexRuntime.from_config(config)
    assert runtime.model == "chosen" and runtime.cli_path == cli


@pytest.mark.parametrize(
    "name,arguments,expected",
    [
        ("exec_command", {}, "unregistered"),
        ("run_python", "not an object", "malformed"),
    ],
)
def test_unknown_tools_and_malformed_arguments_never_execute(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
    name: str,
    arguments: Any,
    expected: str,
) -> None:
    cli, plan, _ = codex_cli
    plan.write_text(json.dumps({"calls": [{"name": name, "input": arguments}]}))
    out = step(cli, codex_tools)
    assert out.status == "error" and out.error is not None and expected in out.error.message
    assert out.runs == []


def test_two_python_errors_stop_queued_execution_after_another_tool(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
) -> None:
    cli, plan, _ = codex_cli
    plan.write_text(
        json.dumps(
            {
                "calls": [
                    {"name": "run_python", "input": {"code": "1/0"}},
                    {"name": "describe_dataset", "input": {"name": "missing"}},
                    {"name": "run_python", "input": {"code": "1/0"}},
                    {"name": "run_python", "input": {"code": "x = 99"}},
                ]
            }
        )
    )
    out = step(cli, codex_tools)
    assert out.status == "error" and out.error is not None and out.error.type == "ZeroDivisionError"
    assert [r.code for r in out.runs] == ["1/0", "1/0"]


def test_native_budget_blocks_thirteenth_call(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
) -> None:
    cli, plan, _ = codex_cli
    plan.write_text(
        json.dumps(
            {"calls": [{"name": "run_python", "input": {"code": f"x = {i}"}} for i in range(13)]}
        )
    )
    out = step(cli, codex_tools)
    assert out.status == "error" and out.error is not None and "12" in out.error.message
    assert len(out.runs) == 12 and out.runs[-1].code == "x = 11"


def wait_for(log: Path, method: str) -> None:
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if log.exists() and any(r.get("method") == method for r in records(log)):
            return
        time.sleep(0.01)
    pytest.fail(f"fake Codex never received {method}")


def test_cancel_interrupts_model_wait_and_cleans_up(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
) -> None:
    cli, plan, log = codex_cli
    plan.write_text(json.dumps({"wait": True}))
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(step, cli, codex_tools, cancel)
        wait_for(log, "turn/start")
        cancel.set()
        out = future.result(timeout=3)
    assert out.status == "interrupted"
    assert any(r.get("method") == "turn/interrupt" for r in records(log))
    assert any(r.get("terminated") for r in records(log))


@pytest.mark.parametrize("crash", [True, False])
def test_crash_or_cancel_waits_for_running_callback_and_blocks_queued_run(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    crash: bool,
) -> None:
    cli, plan, log = codex_cli
    marker = tmp_path / "codex-entered"
    data: dict[str, Any] = {
        "wait": True,
        "calls": [
            {"name": "run_python", "input": {"code": "x = 1"}},
            {"name": "run_python", "input": {"code": "x = 99"}},
        ],
    }
    if crash:
        data["crash_marker"] = str(marker)
    plan.write_text(json.dumps(data))
    entered, release, cancel = threading.Event(), threading.Event(), threading.Event()
    original = codex_tools.run

    def gated(call: ToolCall) -> ToolResult:
        marker.touch()
        entered.set()
        assert release.wait(5)
        return original(call)

    monkeypatch.setattr(codex_tools, "run", gated)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(step, cli, codex_tools, cancel)
        assert entered.wait(5)
        if not crash:
            cancel.set()
            wait_for(log, "turn/interrupt")
        else:
            time.sleep(0.15)
        assert not future.done()
        release.set()
        out = future.result(timeout=3)
    assert out.status == ("error" if crash else "interrupted")
    assert [(r.code, r.status) for r in out.runs] == [("x = 1", "ok")]
    assert [r.call_id for m in out.transcript for r in m.tool_results] == ["call-0"]


def test_text_completion_cancellation_is_operational_failure(
    codex_cli: tuple[Path, Path, Path],
) -> None:
    cli, plan, log = codex_cli
    plan.write_text(json.dumps({"wait": True}))
    cancel = threading.Event()
    runtime = CodexRuntime(model="gpt-6.1-sol", cli_path=cli)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(runtime.complete_text, system="s", prompt="p", cancel=cancel)
        wait_for(log, "turn/start")
        cancel.set()
        with pytest.raises(ProviderError, match="interrupted") as failed:
            future.result(timeout=3)
    assert not failed.value.retryable


@pytest.mark.parametrize(
    "config,expected",
    [
        ({"model_catalog_json": "/tmp/inherited-catalog"}, "capability"),
        ({"features": {"hooks": True}}, "capability"),
        ({"openai_base_url": "https://unintended.invalid"}, "subscription"),
        ({"model_providers": {"openai": {"env_key": "OTHER_KEY"}}}, "subscription"),
    ],
)
def test_inherited_configuration_cannot_relax_the_boundary(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
    config: dict[str, Any],
    expected: str,
) -> None:
    cli, plan, log = codex_cli
    plan.write_text(json.dumps({"config": config}))
    out = step(cli, codex_tools)
    assert out.status == "error" and out.error is not None and expected in out.error.message
    assert not any(r.get("method") == "thread/start" for r in records(log))


def test_thread_inventory_rejects_an_inherited_mcp_tool_before_inference(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
) -> None:
    cli, plan, log = codex_cli
    plan.write_text(json.dumps({"mcp_status": [{"name": "unexpected", "tools": {"unsafe": {}}}]}))
    out = step(cli, codex_tools)
    assert out.status == "error" and out.error is not None and "MCP" in out.error.message
    assert not any(r.get("method") == "turn/start" for r in records(log))


def test_step_creates_dataset_and_mounts_view_through_quarry(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
) -> None:
    cli, plan, _ = codex_cli
    plan.write_text(
        json.dumps(
            {
                "calls": [
                    {"name": "run_python", "input": {"code": "df = pl.DataFrame({'a':[1]})"}},
                    {
                        "name": "render_view",
                        "input": {
                            "component_id": "table",
                            "datasets": ["df"],
                            "initial_state": "{}",
                        },
                    },
                ]
            }
        )
    )
    out = step(cli, codex_tools)
    assert out.status == "ok" and out.view is not None
    assert out.view.component_id == "table" and out.view.datasets == ["df"]
    assert len(out.runs) == 1


@pytest.mark.parametrize("crash", [True, False])
def test_native_cleanup_finishes_while_real_python_is_still_executing(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
    tmp_path: Path,
    crash: bool,
) -> None:
    cli, plan, log = codex_cli
    entered, release = tmp_path / "codex-python-entered", tmp_path / "codex-python-release"
    code = (
        "from pathlib import Path\nimport time\n"
        f"Path({str(entered)!r}).touch()\n"
        f"while not Path({str(release)!r}).exists():\n    time.sleep(0.01)\n"
        "x = 1"
    )
    data: dict[str, Any] = {
        "wait": True,
        "calls": [
            {"name": "run_python", "input": {"code": code}},
            {"name": "run_python", "input": {"code": "x = 99"}},
        ],
    }
    if crash:
        data["crash_marker"] = str(entered)
    plan.write_text(json.dumps(data))
    cancel = threading.Event()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(step, cli, codex_tools, cancel)
        try:
            deadline = time.monotonic() + 5
            while not entered.exists() and time.monotonic() < deadline:
                time.sleep(0.01)
            assert entered.exists()
            if crash:
                time.sleep(0.15)
            else:
                cancel.set()
                wait_for(log, "turn/interrupt")
                deadline = time.monotonic() + 3
                while (
                    not any(r.get("terminated") for r in records(log))
                    and time.monotonic() < deadline
                ):
                    time.sleep(0.01)
                assert any(r.get("terminated") for r in records(log))
            assert not future.done()
        finally:
            release.touch()
        out = future.result(timeout=3)
    assert out.status == ("error" if crash else "interrupted")
    assert [(r.code, r.status) for r in out.runs] == [(code, "ok")]
    assert len([r for m in out.transcript for r in m.tool_results]) == 1


def test_slow_python_does_not_expire_the_native_turn(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import quarry.agent.codex_runtime as codex_runtime

    cli, plan, log = codex_cli
    plan.write_text(json.dumps({"calls": [{"name": "run_python", "input": {"code": "x = 1"}}]}))
    entered, release = threading.Event(), threading.Event()
    original = codex_tools.run
    elapsed = [0.0]
    original_clock = time.monotonic

    class Clock:
        @staticmethod
        def monotonic() -> float:
            return original_clock() + elapsed[0]

    def gated(call: ToolCall) -> ToolResult:
        entered.set()
        assert release.wait(5)
        return original(call)

    monkeypatch.setattr(codex_runtime, "time", Clock)
    monkeypatch.setattr(codex_tools, "run", gated)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(step, cli, codex_tools)
        assert entered.wait(5)
        elapsed[0] = 1000
        time.sleep(0.15)
        assert not any(r.get("terminated") for r in records(log))
        release.set()
        out = future.result(timeout=3)
    assert out.status == "ok" and len(out.runs) == 1


def test_cancellation_stays_responsive_when_native_stops_reading_results(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cli, plan, log = codex_cli
    plan.write_text(
        json.dumps(
            {
                "block_reads": True,
                "calls": [
                    {"name": "describe_dataset", "input": {"name": "synthetic"}},
                ],
            }
        )
    )
    entered, cancel = threading.Event(), threading.Event()

    def large_result(call: ToolCall) -> ToolResult:
        entered.set()
        return ToolResult(call_id=call.id, content="synthetic" * 200000)

    monkeypatch.setattr(codex_tools, "run", large_result)
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(step, cli, codex_tools, cancel)
        try:
            assert entered.wait(5)
            time.sleep(0.15)
            cancel.set()
            out = future.result(timeout=3)
        finally:
            pid = next(r["pid"] for r in records(log) if "pid" in r)
            try:
                os.kill(pid, signal.SIGTERM)
            except ProcessLookupError:
                pass
    assert out.status == "interrupted"


def test_close_after_the_app_server_exited_unreaped(tmp_path: Path) -> None:
    connection = _Connection([sys.executable, "-c", ""], tmp_path, threading.Event())
    # A zombie, exited but not reaped: on macOS, signalling its group then fails with EPERM.
    assert exits_soon(connection.process.pid)
    connection.close(None, None)
    assert connection.process.returncode == 0


def test_missing_terminal_status_returns_error_and_closes_transport(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
) -> None:
    cli, plan, log = codex_cli
    plan.write_text(json.dumps({"terminal_payload": {"id": "turn"}}))
    try:
        out = step(cli, codex_tools)
        assert out.status == "error" and out.error is not None and "malformed" in out.error.message
        assert any(r.get("terminated") for r in records(log))
    finally:
        pid = next(r["pid"] for r in records(log) if "pid" in r)
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


@pytest.mark.parametrize("final_phase", ["final_answer", None])
def test_commentary_is_preserved_but_tidy_and_step_note_receive_only_answer(
    codex_cli: tuple[Path, Path, Path],
    codex_tools: ToolExecutor,
    final_phase: str | None,
) -> None:
    cli, plan, _ = codex_cli
    commentary = "I will check the recipe and simplify it"
    partial = "The dataset assignment is the part to keep"
    code = "df = pl.DataFrame({'a':[1]})\n"
    answer = f"```python\n{code}```"
    messages = [
        {"type": "agentMessage", "id": "progress", "text": commentary, "phase": "commentary"},
        {"type": "agentMessage", "id": "partial", "text": partial, "phase": "partial_answer"},
        {"type": "agentMessage", "id": "answer", "text": answer, "phase": final_phase},
    ]
    plan.write_text(json.dumps({"messages": messages}))
    runtime = CodexRuntime(model="gpt-6.1-sol", cli_path=cli)
    assert tidy_recipe(runtime, code, "df", cancel=threading.Event()) == code
    out = step(cli, codex_tools)
    assert out.status == "ok" and out.note == answer
    assert [message.text for message in out.transcript[1:]] == [commentary, partial, answer]
