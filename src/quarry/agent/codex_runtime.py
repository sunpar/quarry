"""Run fresh Codex subscription turns with only Quarry's registered tools."""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import signal
import subprocess
import threading
import time
from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any, Final, Self

from pydantic import ValidationError

from quarry import __version__
from quarry.agent.loop import StepExecution, StepHalted, StepOutcome
from quarry.agent.tools import TOOL_DEFS, ToolExecutor
from quarry.agent.types import AssistantTurn, Message, ProviderError, ToolCall, ToolResult
from quarry.config import QuarryConfig
from quarry.kernel.client import kill_group

_CODEX_VERSION: Final = "0.162.1"
_SIGKILL_WAIT: Final = 5.0  # seconds
_DISABLED: Final = (
    "shell_tool",
    "stable_environment_tools",
    "multi_agent",
    "multi_agent_v2",
    "code_mode",
    "code_mode_only",
    "code_mode_host",
    "hooks",
    "plugins",
    "apps",
    "connectors",
    "image_generation",
    "imagegenext",
    "browser_use",
    "browser_use_external",
    "computer_use",
    "in_app_browser",
    "memories",
    "memory_tool",
    "goals",
    "agent_message_board",
    "skill_search",
    "deferred_executor",
    "deferred_tool_world_state",
    "standalone_web_search",
    "token_budget",
    "current_time_reminder",
    "sleep_tool",
    "send_message_to_user_async",
    "shell_snapshot",
    "workspace_dependencies",
    "codex_git_commit",
)


class _Connection:
    def __init__(self, argv: list[str], cwd: Path, cancel: threading.Event) -> None:
        environment = dict(os.environ)
        for name in ("OPENAI_API_KEY", "CODEX_API_KEY", "OPENAI_BASE_URL"):
            environment.pop(name, None)
        self.process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=environment,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            encoding="utf-8",
            start_new_session=True,
        )
        self.cancel = cancel
        self.serial = 0
        self.messages: queue.Queue[dict[str, Any] | ProviderError] = queue.Queue()
        self.pending: deque[dict[str, Any]] = deque()
        self.outgoing: queue.Queue[dict[str, Any] | None] = queue.Queue()
        self.writer = threading.Thread(target=self._write, daemon=True)
        self.writer.start()
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self) -> None:
        assert self.process.stdout is not None
        try:
            for line in self.process.stdout:
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError("JSON object required")
                self.messages.put(value)
        except (ValueError, UnicodeError, OSError):
            self.messages.put(
                ProviderError("Codex emitted malformed protocol output", retryable=False)
            )
        finally:
            self.messages.put(ProviderError("Codex app-server exited", retryable=False))

    def _write(self) -> None:
        assert self.process.stdin is not None
        while (message := self.outgoing.get()) is not None:
            try:
                self.process.stdin.write(json.dumps(message) + "\n")
                self.process.stdin.flush()
            except (BrokenPipeError, OSError, ValueError):
                self.messages.put(ProviderError("Codex app-server exited", retryable=False))
                return

    def send(self, message: dict[str, Any]) -> None:
        self.outgoing.put(message)

    def request(self, method: str, params: dict[str, Any]) -> dict[str, Any]:
        self.serial += 1
        request_id = self.serial
        self.send({"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + 30
        while True:
            message = self.receive(deadline, settle_on_cancel=method == "turn/start")
            if "method" in message:
                self.pending.append(message)
            elif message.get("id") == request_id:
                if "error" in message:
                    raise ProviderError(
                        f"Codex {method}: {message['error'].get('message', 'request failed')}",
                        retryable=False,
                    )
                result = message.get("result")
                if not isinstance(result, dict):
                    raise ProviderError("Codex emitted malformed RPC result", retryable=False)
                return result
            else:
                raise ProviderError("Codex emitted an uncorrelated RPC response", retryable=False)

    def receive(
        self, deadline: float | None = None, *, settle_on_cancel: bool = False
    ) -> dict[str, Any]:
        cancel_deadline: float | None = None
        while not self.cancel.is_set() or settle_on_cancel:
            if settle_on_cancel and self.cancel.is_set():
                if cancel_deadline is None:
                    cancel_deadline = time.monotonic() + 1
                deadline = (
                    min(deadline, cancel_deadline) if deadline is not None else cancel_deadline
                )
            if deadline is not None and time.monotonic() >= deadline:
                raise ProviderError("Codex response timed out", retryable=False)
            try:
                message = self.messages.get(timeout=0.05)
            except queue.Empty:
                continue
            if isinstance(message, ProviderError):
                raise message
            return message
        raise ProviderError("interrupted by researcher", retryable=False)

    def close(self, thread_id: str | None, turn_id: str | None) -> None:
        if thread_id is not None and turn_id is not None and self.process.poll() is None:
            self.serial += 1
            self.send(
                {
                    "id": self.serial,
                    "method": "turn/interrupt",
                    "params": {
                        "threadId": thread_id,
                        "turnId": turn_id,
                    },
                }
            )
            deadline = time.monotonic() + 0.3
            while time.monotonic() < deadline:
                try:
                    response = self.messages.get(timeout=0.05)
                except queue.Empty:
                    continue
                if isinstance(response, ProviderError) or response.get("id") == self.serial:
                    break
        # Not once the poll above reaped it: its pid, the group's id, may name another group.
        if self.process.returncode is None:
            kill_group(self.process, signal.SIGTERM)
        self.outgoing.put(None)  # the writer ends even if the app-server outlives SIGKILL
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            kill_group(self.process)
            try:
                self.process.wait(timeout=_SIGKILL_WAIT)
            except subprocess.TimeoutExpired:
                # Refused, or outlived, SIGKILL. Closing its pipes would wait for it too.
                raise ProviderError("Codex app-server outlived SIGKILL", retryable=False) from None
        self.writer.join(timeout=1)
        for stream in (self.process.stdin, self.process.stdout):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass  # The writer can leave a broken pipe pending in its buffer.
        self.reader.join(timeout=1)


class CodexRuntime:
    def __init__(self, *, model: str, cli_path: Path | None = None) -> None:
        if not model.strip():
            raise ValueError("Codex requires an explicit nonblank model")
        self.model = model
        self.cli_path = cli_path
        self.resolved_model: str | None = None

    @classmethod
    def from_config(cls, config: QuarryConfig) -> Self:
        return cls(model=config.provider.model, cli_path=config.provider.cli_path)

    def run_step(
        self,
        *,
        prompt: str,
        system: str,
        summary: str,
        tools: ToolExecutor,
        cancel: threading.Event,
    ) -> StepOutcome:
        transcript = [Message(role="user", text=f"{summary}\n\n# Request\n{prompt}")]
        execution = StepExecution(tools=tools, cancel=cancel, max_tool_calls=12)
        try:
            turn = self._turn(system, transcript, cancel, execution)
        except ProviderError as exc:
            return execution.finish(
                status="interrupted" if cancel.is_set() else "error",
                transcript=transcript,
                error=str(exc),
                model=self.resolved_model,
            )
        return execution.finish(
            status="ok", transcript=transcript, note=turn.text, model=self.resolved_model
        )

    def complete_text(
        self,
        *,
        system: str,
        prompt: str,
        cancel: threading.Event,
    ) -> AssistantTurn:
        return self._turn(system, [Message(role="user", text=prompt)], cancel, None)

    def _turn(
        self,
        system: str,
        transcript: list[Message],
        cancel: threading.Event,
        execution: StepExecution | None,
    ) -> AssistantTurn:
        self.resolved_model = None
        if cancel.is_set():
            raise ProviderError("interrupted by researcher", retryable=False)
        binary = str(self.cli_path) if self.cli_path is not None else shutil.which("codex")
        if binary is None:
            raise ProviderError("Install Codex 0.162.1 and run codex login", retryable=False)
        try:
            version = subprocess.run(
                [binary, "--version"],
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout
        except (OSError, subprocess.SubprocessError):
            raise ProviderError(
                "Cannot run Codex; install 0.162.1 and run codex login", retryable=False
            ) from None
        if re.search(r"\b0\.162\.1\b", version) is None:
            raise ProviderError(
                "Quarry supports Codex 0.162.1 only; verify CLI version", retryable=False
            )
        with TemporaryDirectory(prefix="quarry-codex-") as directory:
            cwd = Path(directory)
            catalog = cwd / "models.json"
            # Model-owned tool metadata overrides feature flags. Replace it at startup,
            # before any tool registration, without changing the requested inference model.
            catalog.write_text(
                json.dumps(
                    {
                        "models": [
                            {
                                "slug": self.model,
                                "display_name": self.model,
                                "base_instructions": system,
                                "supported_reasoning_levels": [],
                                "shell_type": "disabled",
                                "visibility": "list",
                                "supported_in_api": True,
                                "priority": 0,
                                "support_verbosity": False,
                                "truncation_policy": {"mode": "bytes", "limit": 10000},
                                "experimental_supported_tools": [],
                                "tool_mode": "direct",
                                "include_apps_usage_instructions": False,
                            }
                        ]
                    }
                )
            )
            argv = [binary, "app-server", "--listen", "stdio://"]
            overrides = [
                'model_provider="openai"',
                'forced_login_method="chatgpt"',
                f"model_catalog_json={json.dumps(str(catalog))}",
                "agents.enabled=false",
                "notify=[]",
                'web_search="disabled"',
                "features.skip_host_skill_discovery=true",
                "tools.experimental_request_user_input.enabled=false",
                "tools.update_plan.enabled=false",
                "project_doc_max_bytes=0",
                'developer_instructions=""',
            ]
            overrides.extend(f"features.{feature}=false" for feature in _DISABLED)
            for override in overrides:
                argv.extend(["-c", override])
            try:
                connection = _Connection(argv, cwd, cancel)
            except OSError:
                raise ProviderError("Cannot start Codex app-server", retryable=False) from None
            return self._conversation(connection, cwd, system, transcript, execution)

    def _conversation(
        self,
        connection: _Connection,
        cwd: Path,
        system: str,
        transcript: list[Message],
        execution: StepExecution | None,
    ) -> AssistantTurn:
        thread_id = turn_id = None
        calls: list[tuple[int | str, ToolCall, Future[ToolResult]]] = []
        settled: set[str] = set()
        workers = ThreadPoolExecutor(max_workers=1)
        terminal: dict[str, Any] | None = None
        final_texts: list[str] = []
        legacy_texts: list[str] = []
        try:
            initialized = connection.request(
                "initialize",
                {
                    "clientInfo": {"name": "quarry", "version": __version__},
                    "capabilities": {"experimentalApi": True},
                },
            )
            # The userAgent reads "originator/version (os; arch) terminal": compare the
            # whole version token, so 0.162.10 or 10.162.1 never pass for 0.162.1.
            agent = initialized.get("userAgent", "")
            if agent.partition("/")[2].split(" ", 1)[0] != _CODEX_VERSION:
                raise ProviderError("Unexpected Codex app-server version", retryable=False)
            connection.send({"method": "initialized", "params": {}})
            account = connection.request("account/read", {"refreshToken": False})
            if (account.get("account") or {}).get("type") != "chatgpt" or not account.get(
                "requiresOpenaiAuth"
            ):
                raise ProviderError(
                    "Codex requires ChatGPT subscription login; run codex login", retryable=False
                )
            config = connection.request("config/read", {"cwd": str(cwd), "includeLayers": False})[
                "config"
            ]
            if config.get("model_catalog_json") != str(cwd / "models.json") or any(
                (
                    config.get("features", {}).get(feature, True).get("enabled", True)
                    if isinstance(config.get("features", {}).get(feature), dict)
                    else config.get("features", {}).get(feature, True)
                )
                is not False
                for feature in _DISABLED
            ):
                raise ProviderError(
                    "Codex configuration changed the capability boundary", retryable=False
                )
            if (
                config.get("openai_base_url")
                or config.get("model_providers", {}).get("openai")
                or (
                    config.get("chatgpt_base_url", "https://chatgpt.com/backend-api/").rstrip("/")
                    != "https://chatgpt.com/backend-api"
                )
            ):
                raise ProviderError(
                    "Codex requires the built-in ChatGPT subscription provider", retryable=False
                )
            inherited_servers = config.get("mcp_servers", {})
            started = connection.request(
                "thread/start",
                {
                    "model": self.model,
                    "modelProvider": "openai",
                    "ephemeral": True,
                    "cwd": str(cwd),
                    "environments": [],
                    "allowProviderModelFallback": False,
                    "baseInstructions": system,
                    "developerInstructions": "",
                    "config": {
                        "mcp_servers": {name: {"enabled": False} for name in inherited_servers}
                    },
                    "dynamicTools": [
                        {
                            "type": "function",
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": t.input_schema,
                        }
                        for t in TOOL_DEFS
                    ]
                    if execution
                    else [],
                },
            )
            thread_id = started["thread"]["id"]
            if (
                started.get("modelProvider") != "openai"
                or started["thread"].get("environments") != []
            ):
                raise ProviderError(
                    "Codex changed the required provider or environment boundary", retryable=False
                )
            cursor = None
            while True:
                inventory = connection.request(
                    "mcpServerStatus/list",
                    {
                        "threadId": thread_id,
                        "detail": "toolsAndAuthOnly",
                        "cursor": cursor,
                    },
                )
                if any(server["tools"] for server in inventory["data"]):
                    raise ProviderError("Codex exposed inherited MCP tools", retryable=False)
                cursor = inventory.get("nextCursor")
                if cursor is None:
                    break
            self.resolved_model = started.get("model", self.model)
            turn = connection.request(
                "turn/start",
                {
                    "threadId": thread_id,
                    "input": [{"type": "text", "text": transcript[0].text}],
                },
            )
            turn_id = turn["turn"]["id"]
            while terminal is None:
                for request_id, call, future in calls:
                    if future.done() and call.id not in settled:
                        result = future.result()
                        settled.add(call.id)
                        transcript.append(Message(role="user", tool_results=[result]))
                        connection.send(
                            {
                                "id": request_id,
                                "result": {
                                    "contentItems": [{"type": "inputText", "text": result.content}],
                                    "success": not result.is_error,
                                },
                            }
                        )
                        if execution is not None and execution.halt is not None:
                            raise ProviderError(execution.halt[1], retryable=False)
                message = (
                    connection.pending.popleft() if connection.pending else connection.receive()
                )
                method = message.get("method")
                params = message.get("params", {})
                if (
                    params.get("threadId", thread_id) != thread_id
                    or params.get("turnId", turn_id) != turn_id
                ):
                    raise ProviderError(
                        "Codex emitted an event for another thread or turn", retryable=False
                    )
                if method == "item/tool/call":
                    if execution is None or params.get("tool") not in {t.name for t in TOOL_DEFS}:
                        raise ProviderError("Codex requested an unregistered tool", retryable=False)
                    call = ToolCall(
                        id=params["callId"], name=params["tool"], input=params["arguments"]
                    )
                    if call.id in {existing.id for _, existing, _ in calls}:
                        raise ProviderError("Codex repeated a tool call ID", retryable=False)
                    transcript.append(Message(role="assistant", tool_calls=[call]))
                    future = workers.submit(execution.dispatch, call)
                    future.add_done_callback(
                        lambda _: connection.messages.put({"method": "quarry/callback/settled"})
                    )
                    calls.append((message["id"], call, future))
                elif method == "item/completed" and params["item"]["type"] == "agentMessage":
                    item = params["item"]
                    transcript.append(Message(role="assistant", text=item["text"]))
                    if item.get("phase") == "final_answer":
                        final_texts.append(item["text"])
                    elif item.get("phase") is None:
                        legacy_texts.append(item["text"])
                elif method == "turn/completed":
                    completed = params["turn"]
                    if completed["id"] != turn_id:
                        raise ProviderError("Codex completed another turn", retryable=False)
                    if completed["status"] not in ("completed", "failed", "interrupted"):
                        raise ProviderError(
                            "Codex emitted malformed terminal status", retryable=False
                        )
                    terminal = completed
                elif method == "error":
                    raise ProviderError(params["error"]["message"], retryable=False)
                elif "id" in message:
                    raise ProviderError("Codex emitted an unsupported request", retryable=False)
            assert terminal is not None
            if terminal["status"] != "completed":
                error = terminal.get("error") or {}
                raise ProviderError(
                    error.get("message") or f"Codex turn {terminal['status']}", retryable=False
                )
            text = "\n".join(final_texts or legacy_texts)
            return AssistantTurn(text=text, tool_calls=[], stop="end")
        except ProviderError as exc:
            if execution is not None:
                execution.stop("interrupted" if connection.cancel.is_set() else "error", str(exc))
            raise
        except StepHalted as exc:
            raise ProviderError(exc.message, retryable=False) from None
        except (KeyError, TypeError, AttributeError, ValidationError) as exc:
            if execution is not None:
                execution.stop("error", "Codex emitted malformed protocol data")
            raise ProviderError("Codex emitted malformed protocol data", retryable=False) from exc
        finally:
            if execution is not None:
                execution.stop(
                    "ok" if terminal and terminal["status"] == "completed" else "error",
                    "Codex turn ended",
                )
            connection.close(thread_id, turn_id if terminal is None else None)
            workers.shutdown(wait=True, cancel_futures=True)
            for _, call, future in calls:
                if call.id not in settled and not future.cancelled():
                    try:
                        result = future.result()
                    except StepHalted:
                        continue
                    transcript.append(Message(role="user", tool_results=[result]))
