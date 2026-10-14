"""Drive the installed Claude Code CLI through the optional Agent SDK."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Any, Self
from uuid import uuid4

from quarry.agent.loop import StepExecution, StepHalted, StepOutcome
from quarry.agent.tools import TOOL_DEFS, ToolExecutor
from quarry.agent.types import AssistantTurn, Message, ProviderError, StopReason, ToolCall
from quarry.config import QuarryConfig

# The SDK merges options.env into its inherited environment, so empty values
# remove precedence without changing the server process or its native keychain.
_BILLING_PREFIXES = (
    "ANTHROPIC_",
    "CLAUDE_CODE_USE_",
    "CLAUDE_CODE_OAUTH_",
    "CLAUDE_CODE_API_KEY",
    "CLAUDE_CODE_GATEWAY",
    "AWS_",
    "GOOGLE_",
    "AZURE_",
)


def _sdk() -> Any:
    try:
        import claude_agent_sdk
    except ImportError as exc:
        raise ProviderError(
            "Claude Code requires the optional SDK: uv sync --extra claude-code",
            retryable=False,
        ) from exc
    return claude_agent_sdk


class ClaudeRuntime:
    def __init__(self, *, model: str, cli_path: Path | None = None) -> None:
        if not model.strip():
            raise ProviderError("Claude Code requires an explicit model", retryable=False)
        self.model = model
        self.resolved_model: str | None = None
        self.cli_path = cli_path or Path(shutil.which("claude") or "claude")

    @classmethod
    def from_config(cls, config: QuarryConfig) -> Self:
        return cls(model=config.provider.model, cli_path=config.provider.cli_path)

    def _environment(self) -> dict[str, str]:
        environment = {key: "" for key in os.environ if key.startswith(_BILLING_PREFIXES)}
        environment.update(
            {
                "CLAUDE_CODE_SIMPLE": "",
                "CLAUDE_CODE_SAFE_MODE": "1",
                "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
                "ENABLE_TOOL_SEARCH": "false",
            }
        )
        return environment

    def _check_cli(self) -> None:
        environment = {**os.environ, **self._environment()}
        try:
            version = subprocess.run(
                [str(self.cli_path), "--version"],
                env=environment,
                capture_output=True,
                text=True,
                timeout=10,
                check=True,
            ).stdout.split()[0]
            if version != "2.1.299":
                raise ProviderError(
                    f"Claude Code {version} has not passed Quarry's capability probes; "
                    "use the tested 2.1.299 binary",
                    retryable=False,
                )
            status = json.loads(
                subprocess.run(
                    [str(self.cli_path), "auth", "status"],
                    env=environment,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    check=True,
                ).stdout
            )
        except (OSError, subprocess.SubprocessError, ValueError, IndexError) as exc:
            raise ProviderError(
                "Cannot verify Claude Code subscription login; run claude auth login "
                "under the server's OS user",
                retryable=False,
            ) from exc
        if not (
            status.get("loggedIn")
            and status.get("authMethod") == "claude.ai"
            and status.get("apiProvider") == "firstParty"
            and status.get("subscriptionType")
        ):
            raise ProviderError(
                "Claude Code requires native subscription login; run claude auth login "
                "under the server's OS user",
                retryable=False,
            )

    def run_step(
        self,
        *,
        prompt: str,
        system: str,
        summary: str,
        tools: ToolExecutor,
        cancel: threading.Event,
    ) -> StepOutcome:
        execution = StepExecution(tools=tools, cancel=cancel, max_tool_calls=12)
        transcript = [Message(role="user", text=f"{summary}\n\n# Request\n{prompt}")]
        try:
            turn = asyncio.run(
                self._complete(
                    system=system,
                    prompt=transcript[0].text,
                    cancel=cancel,
                    execution=execution,
                    transcript=transcript,
                )
            )
        except ProviderError as exc:
            return execution.finish(
                status="error", transcript=transcript, error=str(exc), model=self.resolved_model
            )
        if execution.halt is not None and execution.halt[0] != "ok":
            status, error = execution.halt
            return execution.finish(
                status=status, transcript=transcript, error=error, model=self.resolved_model
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
        return asyncio.run(
            self._complete(
                system=system,
                prompt=prompt,
                cancel=cancel,
                execution=None,
                transcript=[],
            )
        )

    async def _complete(
        self,
        *,
        system: str,
        prompt: str,
        cancel: threading.Event,
        execution: StepExecution | None,
        transcript: list[Message],
    ) -> AssistantTurn:
        self.resolved_model = None
        if cancel.is_set():
            raise ProviderError("interrupted by researcher", retryable=False)
        library = _sdk()
        await asyncio.to_thread(self._check_cli)
        if cancel.is_set():
            raise ProviderError("interrupted by researcher", retryable=False)
        active: set[asyncio.Task[Any]] = set()
        serial = asyncio.Lock()

        servers = {}
        if execution is not None:
            from mcp.server import Server
            from mcp.types import CallToolResult, TextContent, Tool

            server = Server("quarry")

            @server.list_tools()  # type: ignore[no-untyped-call, untyped-decorator]
            async def list_tools() -> list[Tool]:
                return [
                    Tool(
                        name=definition.name,
                        description=definition.description,
                        inputSchema=definition.input_schema,
                    )
                    for definition in TOOL_DEFS
                ]

            # Quarry validates inside dispatch, after accounting for the request.
            # MCP schema validation here would let invalid requests bypass its caps.
            @server.call_tool(validate_input=False)  # type: ignore[untyped-decorator]
            async def dispatch(name: str, arguments: dict[str, Any]) -> CallToolResult:
                async with serial:
                    assert execution is not None
                    call = ToolCall(id=str(uuid4()), name=name, input=arguments)

                    async def execute() -> Any:
                        result = await asyncio.to_thread(execution.dispatch, call)
                        transcript.extend(
                            [
                                Message(role="assistant", tool_calls=[call]),
                                Message(role="user", tool_results=[result]),
                            ]
                        )
                        return result

                    task = asyncio.create_task(execute())
                    active.add(task)
                    try:
                        result = await asyncio.shield(task)
                    except StepHalted as exc:
                        return CallToolResult(
                            content=[TextContent(type="text", text=str(exc))], isError=True
                        )
                    finally:
                        # SDK disconnect can cancel a callback while its kernel call
                        # still runs. The adapter owns that thread until it settles.
                        if task.done():
                            active.discard(task)
                    return CallToolResult(
                        content=[TextContent(type="text", text=result.content)],
                        isError=result.is_error,
                    )

            servers["quarry"] = {"type": "sdk", "name": "quarry", "instance": server}
        allowed = [f"mcp__quarry__{definition.name}" for definition in TOOL_DEFS] if servers else []
        options = library.ClaudeAgentOptions(
            model=self.model,
            cli_path=self.cli_path,
            system_prompt=system,
            tools=[],
            allowed_tools=allowed,
            mcp_servers=servers,
            strict_mcp_config=True,
            setting_sources=[],
            skills=[],
            settings=json.dumps({"disableAllHooks": True}),
            permission_mode="dontAsk",
            env=self._environment(),
            extra_args={
                "safe-mode": None,
                "disable-slash-commands": None,
                "no-session-persistence": None,
                "no-chrome": None,
            },
        )
        client = library.ClaudeSDKClient(options)
        connected = False

        async def conversation() -> AssistantTurn:
            nonlocal connected
            await client.connect()
            connected = True
            await client.query(prompt)
            try:
                turn = await self._receive(client, library, allowed, transcript)
            except Exception as exc:
                if execution is not None:
                    execution.stop("error", str(exc))
                raise
            if execution is not None:
                if turn.stop == "refusal":
                    execution.stop("error", turn.refusal_reason or "request declined")
                elif turn.stop == "max_tokens":
                    execution.stop("error", "response truncated at max_tokens")
                else:
                    execution.stop("ok", "step finished")
            return turn

        receive = asyncio.create_task(conversation())
        try:
            while not receive.done():
                halt = execution.halt if execution is not None else None
                if cancel.is_set() or halt is not None:
                    if connected:
                        with contextlib.suppress(TimeoutError):
                            await asyncio.wait_for(client.interrupt(), timeout=2)
                    raise ProviderError(
                        "interrupted by researcher"
                        if cancel.is_set()
                        else str(halt[1] if halt is not None else "step halted"),
                        retryable=False,
                    )
                await asyncio.wait({receive}, timeout=0.05)
            return receive.result()
        except ProviderError as exc:
            if execution is not None:
                execution.stop("error", str(exc))
            raise
        except Exception as exc:
            # This is the native transport isolation boundary: an SDK failure
            # must become a step outcome, leaving completed kernel runs intact.
            error = f"Claude Code failed: {exc}"
            if execution is not None:
                execution.stop("error", error)
            raise ProviderError(error, retryable=False) from exc
        finally:
            if not receive.done():
                receive.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await receive
            try:
                await client.disconnect()
            except Exception as exc:
                error = f"Claude Code close failed: {exc}"
                if execution is not None:
                    execution.stop("error", error)
                raise ProviderError(error, retryable=False) from exc
            finally:
                if active:
                    await asyncio.gather(*active, return_exceptions=True)

    async def _receive(
        self,
        client: Any,
        library: Any,
        allowed: list[str],
        transcript: list[Message],
    ) -> AssistantTurn:
        initialized = False
        text = ""
        stop: str | None = None
        async for event in client.receive_response():
            if isinstance(event, library.SystemMessage) and event.subtype == "init":
                if set(event.data.get("tools", [])) != set(allowed):
                    raise ProviderError("Claude Code exposed unexpected tools", retryable=False)
                initialized = True
            elif isinstance(event, library.AssistantMessage):
                self.resolved_model = event.model
                if not initialized:
                    raise ProviderError("Claude Code omitted tool inventory", retryable=False)
                if event.error:
                    raise ProviderError(f"Claude Code: {event.error}", retryable=False)
                for block in event.content:
                    if isinstance(block, library.TextBlock):
                        text = block.text
                        transcript.append(Message(role="assistant", text=text))
                    elif isinstance(block, library.ToolUseBlock) and block.name not in allowed:
                        raise ProviderError(
                            "Claude Code requested unexpected tool", retryable=False
                        )
                stop = event.stop_reason
            elif isinstance(event, library.ResultMessage):
                if not initialized:
                    raise ProviderError("Claude Code omitted tool inventory", retryable=False)
                if event.is_error or event.subtype != "success":
                    raise ProviderError(
                        event.result
                        or "; ".join(event.errors or [])
                        or f"Claude Code: {event.subtype}",
                        retryable=False,
                    )
                final_stop = event.stop_reason or stop
                reasons: dict[str, StopReason] = {
                    "end_turn": "end",
                    "stop_sequence": "end",
                    "max_tokens": "max_tokens",
                    "refusal": "refusal",
                }
                reason = reasons.get(final_stop or "")
                if reason is None:
                    raise ProviderError(
                        f"Unknown Claude Code stop reason: {final_stop}", retryable=False
                    )
                final_text = event.result if event.result is not None else text
                if not transcript or transcript[-1].text != final_text:
                    transcript.append(Message(role="assistant", text=final_text))
                return AssistantTurn(
                    text=final_text,
                    tool_calls=[],
                    stop=reason,
                    refusal_reason=final_text if reason == "refusal" else None,
                )
        raise ProviderError("Claude Code omitted terminal result", retryable=False)
