# Quarry Stage 2: Server and Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Put a FastAPI server and an agent loop on top of the Stage 1 core so a researcher can drive a session from curl: post a prompt, the agent writes and runs polars in the kernel, the step is persisted, and the browser-facing endpoints (status, steps, query, interrupt, restart) exist.

**Architecture:** `quarry.agent` holds a provider-neutral message model, two provider adapters (Anthropic via the official SDK's beta messages endpoint, OpenAI via chat completions), five tools, a context builder, and the loop. `quarry.server` holds session models, the on-disk session store, a kernel manager with restart-and-replay, a session service that runs one step at a time per session in a background thread, and the FastAPI app with bearer-token auth. `quarry.cli` starts it all on loopback and prints the port-forward instructions. Nothing in Stage 2 renders a view; `render_view` and `write_view` only validate and record one.

**Tech Stack:** Python 3.11+, FastAPI, uvicorn, anthropic SDK (1.x), openai SDK, pydantic 2, httpx (FastAPI test client), pytest. Stage 1 package as built.

**Spec:** `docs/superpowers/specs/2026-10-08-quarry-design.md` (sections 4, 5 Session/Step/View, 6 restart-and-replay, 8, 11 sessions and config, 12, 13, 14, 15 stage 2). Stage 1 interfaces: `docs/superpowers/plans/2026-10-08-quarry-stage1-core.md`.

## Global Constraints

- Everything in the Stage 1 plan's Global Constraints still applies (typing, ruff, mypy, no bare excepts, pathlib).
- Commit messages use a bare Conventional Commit type (`feat:`, `test:`, `docs:`, `build:`); the pre-commit hook rejects scoped types and attribution trailers.
- Default model is `claude-opus-5-5`. Anthropic requests go through `client.beta.messages.create` with `max_tokens=16000`, `output_config={"effort": "high"}`, `betas=["server-side-fallback-2026-07-01"]`, `fallbacks="default"`, no `thinking` parameter, `tool_choice` left at auto, every tool `strict: True` with `additionalProperties: false`.
- No streaming anywhere. A step request returns a step id immediately; the loop runs in a background thread; the client polls status.
- One in-flight step per session. A second step request while one is running returns HTTP 409.
- Agent loop hard cap: 12 provider calls per step. Repair rule: the second consecutive `run_python` error ends the step as `error`.
- Server binds `127.0.0.1` only. Every request except `GET /healthz` needs `Authorization: Bearer <token>`.
- `Step.transcript` stores provider-neutral `Message` objects, never vendor SDK objects.
- Steps are written to disk once, on completion. A running step exists only in memory.

## Review Focus

1. The model refuses (`stop_reason == "refusal"`). Expected: the step fails with the refusal explanation, nothing crashes, the session stays usable. Pinned in Task 3.
2. The model emits a `run_python` call whose code fails twice in a row. Expected: the step ends as `error` after the second failure, with both tracebacks in the transcript, and no third attempt. Pinned in Task 8.
3. Two prompts posted to the same session back to back. Expected: the second gets 409, the first completes normally. Pinned in Task 10.
4. The kernel dies mid-step. Expected: the step is marked `error` with a kernel message, status reports the kernel dead, and `POST /restart` replays prior steps and returns the first failing step if any. Pinned in Task 9 and Task 10.
5. The server is restarted while a session directory exists on disk. Expected: `GET /sessions/{id}` returns the persisted steps and a fresh kernel is spawned on the next request. Pinned in Task 10.

---

### Task 1: Dependencies and model default

**Files:**

- Modify: `pyproject.toml`
- Modify: `src/quarry/config.py` (one line)
- Modify: `docs/superpowers/specs/2026-10-08-quarry-design.md` (one line)
- Modify: `tests/test_config.py` (one assertion)

**Interfaces:**

- Produces: `anthropic`, `openai`, `fastapi`, `uvicorn` as runtime dependencies; `httpx` as a dev dependency for the FastAPI test client; `ProviderConfig.model` defaults to `"claude-opus-5-5"`.

- [ ] **Step 1: Add dependencies**

In `pyproject.toml`, change the dependency lists to:

```toml
dependencies = [
    "polars>=1.0",
    "duckdb>=1.0",
    "pydantic>=2.0",
    "pyarrow>=15.0",
    "anthropic>=1.0",
    "openai>=1.50",
    "fastapi>=0.115",
    "uvicorn>=0.30",
]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.5",
    "mypy>=1.10",
    "httpx>=0.27",
]
```

Add under `[[tool.mypy.overrides]]` module list: `"openai", "openai.*"` (the anthropic SDK ships types; openai does too, but keep the override in case the installed version lacks `py.typed`).

- [ ] **Step 2: Change the model default and pin it with a test**

In `src/quarry/config.py`, change `model: str = "claude-sonnet-5-5"` to `model: str = "claude-opus-5-5"`.

In `docs/superpowers/specs/2026-10-08-quarry-design.md`, change `model = "claude-sonnet-5-5"` to `model = "claude-opus-5-5"`.

In `tests/test_config.py`, add to `test_defaults_when_no_file`:

```python
    assert cfg.provider.model == "claude-opus-5-5"
```

- [ ] **Step 3: Install and run the suite**

Run: `uv sync && uv run pytest -q`
Expected: all Stage 1 tests pass, plus the new assertion.

- [ ] **Step 4: Commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add pyproject.toml uv.lock src/quarry/config.py tests/test_config.py docs/superpowers/specs/2026-10-08-quarry-design.md
git commit -m "build: add server and provider dependencies, default to claude-opus-5-5"
```

---

### Task 2: Provider-neutral message model and fake provider

**Files:**

- Create: `src/quarry/agent/__init__.py`
- Create: `src/quarry/agent/types.py`
- Create: `src/quarry/agent/fake.py`
- Test: `tests/agent/__init__.py`
- Test: `tests/agent/test_types.py`

**Interfaces:**

- Produces (in `quarry.agent.types`):
  - `class ToolDef(BaseModel)`: `name: str`, `description: str`, `input_schema: dict[str, Json]`
  - `class ToolCall(BaseModel)`: `id: str`, `name: str`, `input: dict[str, Json]`
  - `class ToolResult(BaseModel)`: `call_id: str`, `content: str`, `is_error: bool = False`
  - `class Message(BaseModel)`: `role: Literal["user", "assistant"]`, `text: str = ""`, `tool_calls: list[ToolCall] = []`, `tool_results: list[ToolResult] = []`
  - `StopReason = Literal["end", "tool_use", "max_tokens", "refusal"]`
  - `class AssistantTurn(BaseModel)`: `text: str`, `tool_calls: list[ToolCall]`, `stop: StopReason`, `refusal_reason: str | None = None`; method `as_message(self) -> Message`
  - `class Provider(Protocol)`: `def complete(self, *, system: str, messages: list[Message], tools: list[ToolDef]) -> AssistantTurn`
  - `class ProviderError(Exception)`: `__init__(self, message: str, *, retryable: bool)`; attribute `retryable: bool`
- Produces (in `quarry.agent.fake`): `class FakeProvider`: `__init__(self, turns: list[AssistantTurn])`; `complete(...)` returns the next scripted turn and records every call in `self.calls: list[tuple[str, list[Message], list[ToolDef]]]`; raises `AssertionError("FakeProvider exhausted")` when out of turns.

- [ ] **Step 1: Write the failing tests**

`tests/agent/__init__.py`: empty.

`tests/agent/test_types.py`:

```python
import pytest

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, Message, ToolCall, ToolDef, ToolResult


def test_message_defaults():
    m = Message(role="user", text="hi")
    assert m.tool_calls == [] and m.tool_results == []


def test_assistant_turn_as_message():
    turn = AssistantTurn(
        text="running",
        tool_calls=[ToolCall(id="c1", name="run_python", input={"code": "x = 1"})],
        stop="tool_use",
    )
    msg = turn.as_message()
    assert msg.role == "assistant"
    assert msg.text == "running"
    assert msg.tool_calls[0].name == "run_python"


def test_round_trip_json():
    msg = Message(role="user", tool_results=[ToolResult(call_id="c1", content="{}", is_error=True)])
    assert Message.model_validate_json(msg.model_dump_json()) == msg


def test_fake_provider_replays_and_records():
    turns = [AssistantTurn(text="a", tool_calls=[], stop="end")]
    fake = FakeProvider(turns)
    tools = [ToolDef(name="t", description="d", input_schema={"type": "object", "properties": {}})]
    out = fake.complete(system="sys", messages=[Message(role="user", text="q")], tools=tools)
    assert out.text == "a"
    assert fake.calls[0][0] == "sys"
    assert fake.calls[0][1][0].text == "q"
    with pytest.raises(AssertionError, match="exhausted"):
        fake.complete(system="sys", messages=[], tools=tools)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.agent'`

- [ ] **Step 3: Write the implementation**

`src/quarry/agent/__init__.py`: empty docstring module.

`src/quarry/agent/types.py`:

```python
"""Provider-neutral message model shared by the loop, the adapters, and step transcripts."""

from __future__ import annotations

from typing import Literal, Protocol

from pydantic import BaseModel, Field

from quarry.query.spec import Json

StopReason = Literal["end", "tool_use", "max_tokens", "refusal"]


class ToolDef(BaseModel):
    name: str
    description: str
    input_schema: dict[str, Json]


class ToolCall(BaseModel):
    id: str
    name: str
    input: dict[str, Json]


class ToolResult(BaseModel):
    call_id: str
    content: str
    is_error: bool = False


class Message(BaseModel):
    role: Literal["user", "assistant"]
    text: str = ""
    tool_calls: list[ToolCall] = Field(default_factory=list)
    tool_results: list[ToolResult] = Field(default_factory=list)


class AssistantTurn(BaseModel):
    text: str
    tool_calls: list[ToolCall]
    stop: StopReason
    refusal_reason: str | None = None

    def as_message(self) -> Message:
        return Message(role="assistant", text=self.text, tool_calls=self.tool_calls)


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool) -> None:
        super().__init__(message)
        self.retryable = retryable


class Provider(Protocol):
    def complete(self, *, system: str, messages: list[Message], tools: list[ToolDef]) -> AssistantTurn: ...
```

`src/quarry/agent/fake.py`:

```python
"""Scripted provider for tests."""

from __future__ import annotations

from quarry.agent.types import AssistantTurn, Message, ToolDef


class FakeProvider:
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self._turns = list(turns)
        self.calls: list[tuple[str, list[Message], list[ToolDef]]] = []

    def complete(self, *, system: str, messages: list[Message], tools: list[ToolDef]) -> AssistantTurn:
        self.calls.append((system, list(messages), list(tools)))
        if not self._turns:
            raise AssertionError("FakeProvider exhausted")
        return self._turns.pop(0)
```

- [ ] **Step 4: Run tests, format, commit**

Run: `uv run pytest tests/agent/test_types.py -v` → 4 passed.

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/agent tests/agent
git commit -m "feat: provider-neutral agent message model and fake provider"
```

---

### Task 3: Anthropic provider adapter

**Files:**

- Create: `src/quarry/agent/anthropic_provider.py`
- Test: `tests/agent/test_anthropic_provider.py`

**Interfaces:**

- Consumes: `Message`, `ToolDef`, `ToolCall`, `AssistantTurn`, `ProviderError` (Task 2); `QuarryConfig`, `api_key` (Stage 1).
- Produces: `class AnthropicProvider`: `__init__(self, *, model: str, create: CreateFn)` where `CreateFn = Callable[..., object]` is the SDK's `client.beta.messages.create` or a test double; `@classmethod from_config(cls, config: QuarryConfig) -> AnthropicProvider` builds `anthropic.Anthropic(api_key=api_key(config), max_retries=2)`; `complete(...)`. Module-level pure helpers `to_api_messages(messages: list[Message]) -> list[dict[str, Json]]`, `to_api_tools(tools: list[ToolDef]) -> list[dict[str, Json]]`, `from_api_response(response: object) -> AssistantTurn`.

- [ ] **Step 1: Write the failing tests**

`tests/agent/test_anthropic_provider.py`:

```python
from types import SimpleNamespace

import anthropic
import pytest

from quarry.agent.anthropic_provider import AnthropicProvider, from_api_response, to_api_messages, to_api_tools
from quarry.agent.types import Message, ProviderError, ToolCall, ToolDef, ToolResult


def test_to_api_messages_shapes():
    msgs = [
        Message(role="user", text="load it"),
        Message(role="assistant", text="ok", tool_calls=[ToolCall(id="c1", name="run_python", input={"code": "x=1"})]),
        Message(role="user", tool_results=[ToolResult(call_id="c1", content="{}", is_error=True)]),
    ]
    api = to_api_messages(msgs)
    assert api[0] == {"role": "user", "content": "load it"}
    assert api[1]["role"] == "assistant"
    assert api[1]["content"][0] == {"type": "text", "text": "ok"}
    assert api[1]["content"][1] == {"type": "tool_use", "id": "c1", "name": "run_python", "input": {"code": "x=1"}}
    assert api[2]["content"][0] == {"type": "tool_result", "tool_use_id": "c1", "content": "{}", "is_error": True}


def test_to_api_tools_are_strict():
    tools = [ToolDef(name="t", description="d", input_schema={"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"]})]
    api = to_api_tools(tools)
    assert api[0]["strict"] is True
    assert api[0]["input_schema"]["additionalProperties"] is False


def test_from_api_response_tool_use():
    response = SimpleNamespace(
        stop_reason="tool_use",
        stop_details=None,
        content=[
            SimpleNamespace(type="text", text="running"),
            SimpleNamespace(type="tool_use", id="c1", name="run_python", input={"code": "x=1"}),
        ],
    )
    turn = from_api_response(response)
    assert turn.stop == "tool_use"
    assert turn.text == "running"
    assert turn.tool_calls == [ToolCall(id="c1", name="run_python", input={"code": "x=1"})]


def test_from_api_response_refusal():
    response = SimpleNamespace(
        stop_reason="refusal",
        stop_details=SimpleNamespace(type="refusal", category="cyber", explanation="declined"),
        content=[],
    )
    turn = from_api_response(response)
    assert turn.stop == "refusal"
    assert turn.refusal_reason == "declined"


def test_complete_passes_required_parameters():
    captured: dict[str, object] = {}

    def create(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(stop_reason="end_turn", stop_details=None, content=[SimpleNamespace(type="text", text="done")])

    provider = AnthropicProvider(model="claude-opus-5-5", create=create)
    turn = provider.complete(system="sys", messages=[Message(role="user", text="q")], tools=[])
    assert turn.stop == "end" and turn.text == "done"
    assert captured["model"] == "claude-opus-5-5"
    assert captured["max_tokens"] == 16000
    assert captured["output_config"] == {"effort": "high"}
    assert captured["betas"] == ["server-side-fallback-2026-07-01"]
    assert captured["fallbacks"] == "default"
    assert captured["system"] == [{"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}]
    assert "thinking" not in captured
    assert "tool_choice" not in captured


def test_complete_maps_sdk_errors():
    def rate_limited(**kwargs: object) -> object:
        raise anthropic.RateLimitError("slow down", response=SimpleNamespace(status_code=429, headers={}), body=None)

    with pytest.raises(ProviderError) as info:
        AnthropicProvider(model="m", create=rate_limited).complete(system="s", messages=[], tools=[])
    assert info.value.retryable is True

    def bad_request(**kwargs: object) -> object:
        raise anthropic.BadRequestError("nope", response=SimpleNamespace(status_code=400, headers={}), body=None)

    with pytest.raises(ProviderError) as info2:
        AnthropicProvider(model="m", create=bad_request).complete(system="s", messages=[], tools=[])
    assert info2.value.retryable is False
```

If constructing `anthropic.RateLimitError` with a `SimpleNamespace` response fails in the installed SDK version, build a real response with `httpx2.Response(429, request=httpx2.Request("POST", "https://x"))` (`import httpx2 as httpx`; anthropic 1.x is built on httpx2).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_anthropic_provider.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.agent.anthropic_provider'`

- [ ] **Step 3: Write the implementation**

`src/quarry/agent/anthropic_provider.py`:

```python
"""Anthropic adapter: provider-neutral messages in, AssistantTurn out."""

from __future__ import annotations

from collections.abc import Callable
from typing import Final

import anthropic

from quarry.agent.types import AssistantTurn, Message, ProviderError, StopReason, ToolCall, ToolDef
from quarry.config import QuarryConfig, api_key
from quarry.query.spec import Json

CreateFn = Callable[..., object]

MAX_TOKENS: Final = 16000
EFFORT: Final = "high"
FALLBACK_BETA: Final = "server-side-fallback-2026-07-01"
STOP_MAP: Final[dict[str, StopReason]] = {
    "end_turn": "end",
    "stop_sequence": "end",
    "tool_use": "tool_use",
    "max_tokens": "max_tokens",
    "refusal": "refusal",
}


class AnthropicProvider:
    def __init__(self, *, model: str, create: CreateFn) -> None:
        self._model = model
        self._create = create

    @classmethod
    def from_config(cls, config: QuarryConfig) -> AnthropicProvider:
        client = anthropic.Anthropic(api_key=api_key(config), max_retries=2)
        return cls(model=config.provider.model, create=client.beta.messages.create)

    def complete(self, *, system: str, messages: list[Message], tools: list[ToolDef]) -> AssistantTurn:
        try:
            response = self._create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                tools=to_api_tools(tools),
                messages=to_api_messages(messages),
                output_config={"effort": EFFORT},
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
        except anthropic.RateLimitError as exc:
            raise ProviderError(str(exc), retryable=True) from exc
        except anthropic.InternalServerError as exc:
            raise ProviderError(str(exc), retryable=True) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(str(exc), retryable=True) from exc
        except anthropic.APIStatusError as exc:
            raise ProviderError(str(exc), retryable=False) from exc
        return from_api_response(response)


def to_api_messages(messages: list[Message]) -> list[dict[str, Json]]:
    out: list[dict[str, Json]] = []
    for m in messages:
        if m.role == "assistant":
            blocks: list[Json] = []
            if m.text:
                blocks.append({"type": "text", "text": m.text})
            blocks += [{"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in m.tool_calls]
            out.append({"role": "assistant", "content": blocks})
        elif m.tool_results:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {"type": "tool_result", "tool_use_id": r.call_id, "content": r.content, "is_error": r.is_error}
                        for r in m.tool_results
                    ],
                }
            )
        else:
            out.append({"role": "user", "content": m.text})
    return out


def to_api_tools(tools: list[ToolDef]) -> list[dict[str, Json]]:
    return [
        {
            "name": t.name,
            "description": t.description,
            "input_schema": {**t.input_schema, "additionalProperties": False},
            "strict": True,
        }
        for t in tools
    ]


def from_api_response(response: object) -> AssistantTurn:
    stop_reason = str(getattr(response, "stop_reason", "end_turn"))
    stop = STOP_MAP.get(stop_reason, "end")
    text_parts: list[str] = []
    calls: list[ToolCall] = []
    for block in getattr(response, "content", []):
        kind = getattr(block, "type", "")
        if kind == "text":
            text_parts.append(str(block.text))
        elif kind == "tool_use":
            calls.append(ToolCall(id=str(block.id), name=str(block.name), input=dict(block.input)))
    refusal = None
    if stop == "refusal":
        details = getattr(response, "stop_details", None)
        refusal = str(getattr(details, "explanation", None) or "request declined by safety classifier")
    return AssistantTurn(text="".join(text_parts), tool_calls=calls, stop=stop, refusal_reason=refusal)
```

Retry policy: the SDK retries 429, 5xx, and connection errors twice with backoff (`max_retries=2` on the client). The loop does not retry again on top of that; `retryable` on `ProviderError` is informational for the step's error message.

- [ ] **Step 4: Run tests, format, commit**

Run: `uv run pytest tests/agent/test_anthropic_provider.py -v` → 6 passed.

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/agent tests/agent
git commit -m "feat: anthropic provider adapter with strict tools and server-side fallbacks"
```

---

### Task 4: OpenAI provider adapter

**Files:**

- Create: `src/quarry/agent/openai_provider.py`
- Test: `tests/agent/test_openai_provider.py`

**Interfaces:**

- Consumes: Task 2 types, `QuarryConfig`, `api_key`.
- Produces: `class OpenAIProvider`: `__init__(self, *, model: str, create: CreateFn)`; `from_config(config)` builds `openai.OpenAI(api_key=api_key(config), max_retries=2)` and passes `client.chat.completions.create`; `complete(...)`. Helpers `to_openai_messages(system, messages) -> list[dict[str, Json]]`, `to_openai_tools(tools) -> list[dict[str, Json]]`, `from_openai_response(response) -> AssistantTurn`.

- [ ] **Step 1: Write the failing tests**

`tests/agent/test_openai_provider.py`:

```python
import json
from types import SimpleNamespace

import openai
import pytest

from quarry.agent.openai_provider import OpenAIProvider, from_openai_response, to_openai_messages, to_openai_tools
from quarry.agent.types import Message, ProviderError, ToolCall, ToolDef, ToolResult


def test_to_openai_messages_shapes():
    msgs = [
        Message(role="user", text="load it"),
        Message(role="assistant", text="ok", tool_calls=[ToolCall(id="c1", name="run_python", input={"code": "x=1"})]),
        Message(role="user", tool_results=[ToolResult(call_id="c1", content="{}", is_error=True)]),
    ]
    api = to_openai_messages("sys", msgs)
    assert api[0] == {"role": "system", "content": "sys"}
    assert api[1] == {"role": "user", "content": "load it"}
    assert api[2]["role"] == "assistant"
    assert api[2]["tool_calls"][0]["function"] == {"name": "run_python", "arguments": json.dumps({"code": "x=1"})}
    assert api[3] == {"role": "tool", "tool_call_id": "c1", "content": "{}"}


def test_to_openai_tools():
    tools = [ToolDef(name="t", description="d", input_schema={"type": "object", "properties": {}, "required": []})]
    api = to_openai_tools(tools)
    assert api[0]["type"] == "function"
    assert api[0]["function"]["parameters"]["additionalProperties"] is False
    assert api[0]["function"]["strict"] is True


def test_from_openai_response_tool_calls():
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[SimpleNamespace(id="c1", function=SimpleNamespace(name="run_python", arguments='{"code": "x=1"}'))],
                ),
            )
        ]
    )
    turn = from_openai_response(response)
    assert turn.stop == "tool_use"
    assert turn.tool_calls == [ToolCall(id="c1", name="run_python", input={"code": "x=1"})]


def test_from_openai_response_length_and_refusal():
    length = SimpleNamespace(choices=[SimpleNamespace(finish_reason="length", message=SimpleNamespace(content="partial", tool_calls=None))])
    assert from_openai_response(length).stop == "max_tokens"
    refusal = SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content=None, tool_calls=None, refusal="no"))])
    turn = from_openai_response(refusal)
    assert turn.stop == "refusal" and turn.refusal_reason == "no"


def test_complete_maps_errors():
    def rate_limited(**kwargs: object) -> object:
        raise openai.RateLimitError("slow", response=SimpleNamespace(status_code=429, headers={}, request=None), body=None)

    with pytest.raises(ProviderError) as info:
        OpenAIProvider(model="gpt", create=rate_limited).complete(system="s", messages=[], tools=[])
    assert info.value.retryable is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_openai_provider.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`src/quarry/agent/openai_provider.py`:

```python
"""OpenAI adapter over chat completions with function tools."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Final

import openai

from quarry.agent.types import AssistantTurn, Message, ProviderError, StopReason, ToolCall, ToolDef
from quarry.config import QuarryConfig, api_key
from quarry.query.spec import Json

CreateFn = Callable[..., object]
MAX_TOKENS: Final = 16000
FINISH_MAP: Final[dict[str, StopReason]] = {"stop": "end", "tool_calls": "tool_use", "length": "max_tokens"}


class OpenAIProvider:
    def __init__(self, *, model: str, create: CreateFn) -> None:
        self._model = model
        self._create = create

    @classmethod
    def from_config(cls, config: QuarryConfig) -> OpenAIProvider:
        client = openai.OpenAI(api_key=api_key(config), max_retries=2)
        return cls(model=config.provider.model, create=client.chat.completions.create)

    def complete(self, *, system: str, messages: list[Message], tools: list[ToolDef]) -> AssistantTurn:
        kwargs: dict[str, object] = {
            "model": self._model,
            "messages": to_openai_messages(system, messages),
            "max_completion_tokens": MAX_TOKENS,
        }
        if tools:
            kwargs["tools"] = to_openai_tools(tools)
        try:
            response = self._create(**kwargs)
        except (openai.RateLimitError, openai.InternalServerError, openai.APIConnectionError) as exc:
            raise ProviderError(str(exc), retryable=True) from exc
        except openai.APIStatusError as exc:
            raise ProviderError(str(exc), retryable=False) from exc
        return from_openai_response(response)


def to_openai_messages(system: str, messages: list[Message]) -> list[dict[str, Json]]:
    out: list[dict[str, Json]] = [{"role": "system", "content": system}]
    for m in messages:
        if m.role == "assistant":
            entry: dict[str, Json] = {"role": "assistant", "content": m.text or None}
            if m.tool_calls:
                entry["tool_calls"] = [
                    {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.input)}}
                    for c in m.tool_calls
                ]
            out.append(entry)
        elif m.tool_results:
            out += [{"role": "tool", "tool_call_id": r.call_id, "content": r.content} for r in m.tool_results]
        else:
            out.append({"role": "user", "content": m.text})
    return out


def to_openai_tools(tools: list[ToolDef]) -> list[dict[str, Json]]:
    return [
        {
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description,
                "parameters": {**t.input_schema, "additionalProperties": False},
                "strict": True,
            },
        }
        for t in tools
    ]


def from_openai_response(response: object) -> AssistantTurn:
    choice = response.choices[0]  # type: ignore[attr-defined]
    message = choice.message
    refusal = getattr(message, "refusal", None)
    if refusal:
        return AssistantTurn(text="", tool_calls=[], stop="refusal", refusal_reason=str(refusal))
    calls = [
        ToolCall(id=str(c.id), name=str(c.function.name), input=json.loads(c.function.arguments or "{}"))
        for c in (message.tool_calls or [])
    ]
    stop = FINISH_MAP.get(str(choice.finish_reason), "end")
    return AssistantTurn(text=str(message.content or ""), tool_calls=calls, stop=stop)
```

- [ ] **Step 4: Run tests, format, commit**

Run: `uv run pytest tests/agent/test_openai_provider.py -v` → 5 passed. If `openai.RateLimitError` needs a real `httpx.Response`, construct one as in Task 3's note (the openai SDK uses `httpx`, not `httpx2`).

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/agent tests/agent
git commit -m "feat: openai provider adapter over chat completions"
```

---

### Task 5: Component library, transpile check, and the five tools

**Files:**

- Create: `src/quarry/components/__init__.py`
- Create: `src/quarry/components/library.py`
- Create: `src/quarry/components/builtin/.gitkeep`
- Create: `src/quarry/agent/transpile.py`
- Create: `src/quarry/agent/tools.py`
- Test: `tests/components/__init__.py`
- Test: `tests/components/test_library.py`
- Test: `tests/agent/test_transpile.py`
- Test: `tests/agent/test_tools.py`

**Interfaces:**

- Consumes: `KernelClient` (`execute`, `describe`, `KernelDead`, `RpcFailure`), `DatasetMeta`, `Column` from Stage 1.
- Produces (in `quarry.components.library`):
  - `class SchemaRequirement(BaseModel)`: `role: str`, `dtype: Literal["datetime", "numeric", "string", "any"]`, `min: int = 1`
  - `class ComponentManifest(BaseModel)`: `id: str`, `name: str`, `description: str`, `tags: list[str]`, `contract_version: int = 1`, `schema_: ComponentSchema` (alias `schema`), `origin: Literal["builtin", "generated", "imported"]`, `created_at: str`; `class ComponentSchema(BaseModel)`: `requires: list[SchemaRequirement]`
  - `class ComponentEntry(BaseModel)`: `manifest: ComponentManifest`, `source_path: Path`
  - `class ComponentLibrary`: `__init__(self, roots: list[Path])`; `entries(self) -> list[ComponentEntry]` (every `<root>/<id>/manifest.json` with a sibling `component.tsx`, first root wins on duplicate ids); `get(self, component_id: str) -> ComponentEntry | None`; `search(self, *, dataset: DatasetMeta | None, tags: list[str]) -> list[ComponentManifest]` returning entries whose requirements the dataset satisfies (all entries when `dataset` is None), ranked by tag overlap descending then id.
  - `def dtype_class(dtype: str) -> Literal["datetime", "numeric", "string", "other"]`: polars dtype string to class (`Date`/`Datetime*` → datetime; `Int*`/`UInt*`/`Float*`/`Decimal*` → numeric; `String`/`Utf8`/`Categorical*`/`Enum*` → string).
  - `def builtin_root() -> Path` = `Path(__file__).parent / "builtin"`.
- Produces (in `quarry.agent.transpile`): `class Transpiler(Protocol)`: `def check(self, source: str) -> str | None` (error text or None); `class NoopTranspiler`; `class CommandTranspiler`: `__init__(self, command: list[str])`, runs the command with `source` on stdin, returns `stderr` when exit code is nonzero; `def default_transpiler(static_dir: Path) -> Transpiler`: `CommandTranspiler(["node", str(static_dir / "transpile-check.mjs")])` when `shutil.which("node")` and that file exist, else `NoopTranspiler()`. Stage 3 produces `transpile-check.mjs`.
- Produces (in `quarry.agent.tools`):
  - `TOOL_DEFS: list[ToolDef]` for `run_python`, `describe_dataset`, `search_components`, `render_view`, `write_view`, with the JSON schemas below.
  - `class PendingView(BaseModel)`: `component_id: str`, `source: str`, `initial_state: dict[str, Json]`, `datasets: list[str]`
  - `class ToolExecutor`: `__init__(self, *, kernel: KernelClient, library: ComponentLibrary, transpiler: Transpiler)`; `run(self, call: ToolCall) -> ToolResult`; attribute `view: PendingView | None` set by `render_view`/`write_view`; attribute `last_python_failed: bool`; attribute `exec_results: list[ExecResult]`, one entry per `run_python` call in order. Unknown tool or bad arguments → `ToolResult(is_error=True)`. `KernelDead` propagates (the loop handles it).

Tool schemas:

```python
RUN_PYTHON = {"type": "object", "properties": {"code": {"type": "string", "description": "Python to execute in the session kernel. polars is `pl`, duckdb is `duckdb`, loaders under `loaders.*`, `sql(query)`, `pq(glob)`, `sql_local(query)`. Assign results to well-named top-level variables; every top-level DataFrame, LazyFrame or DuckDB relation becomes a dataset."}}, "required": ["code"]}
DESCRIBE_DATASET = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
SEARCH_COMPONENTS = {"type": "object", "properties": {"dataset": {"type": "string", "description": "Dataset the component should render; filters by schema compatibility."}, "tags": {"type": "array", "items": {"type": "string"}}}, "required": ["dataset", "tags"]}
RENDER_VIEW = {"type": "object", "properties": {"component_id": {"type": "string"}, "datasets": {"type": "array", "items": {"type": "string"}}, "initial_state": {"type": "string", "description": "JSON object encoded as a string, e.g. \"{}\""}}, "required": ["component_id", "datasets", "initial_state"]}
WRITE_VIEW = {"type": "object", "properties": {"source": {"type": "string", "description": "A TSX module whose default export is the component. Only `react`, the design system, the chart libraries listed in the guide, and the hooks module may be imported."}, "datasets": {"type": "array", "items": {"type": "string"}}, "initial_state": {"type": "string", "description": "JSON object encoded as a string, e.g. \"{}\""}}, "required": ["source", "datasets", "initial_state"]}
```

Strict mode (both providers) requires every property to be required and every nested object to be closed, so `initial_state` travels as a JSON string and is parsed by a validator; `tags` and `datasets` are required arrays that may be empty.

- [ ] **Step 1: Write the failing library tests**

`tests/components/__init__.py`: empty.

`tests/components/test_library.py`:

```python
import json
from pathlib import Path

from quarry.components.library import ComponentLibrary, dtype_class
from quarry.kernel.datasets import Column, DatasetMeta


def write_component(root: Path, cid: str, tags: list[str], requires: list[dict[str, object]]) -> None:
    d = root / cid
    d.mkdir(parents=True)
    (d / "component.tsx").write_text("export default function V() { return null }")
    (d / "manifest.json").write_text(
        json.dumps({"id": cid, "name": cid, "description": "", "tags": tags, "schema": {"requires": requires}, "origin": "builtin", "created_at": "2026-10-08T00:00:00Z"})
    )


def meta(cols: list[tuple[str, str]]) -> DatasetMeta:
    return DatasetMeta(name="d", backing="polars", schema=[Column(name=n, dtype=t) for n, t in cols], rows=1, preview=[])


def test_dtype_class():
    assert dtype_class("Date") == "datetime"
    assert dtype_class("Datetime(time_unit='us', time_zone=None)") == "datetime"
    assert dtype_class("Int64") == "numeric"
    assert dtype_class("Float32") == "numeric"
    assert dtype_class("String") == "string"
    assert dtype_class("Boolean") == "other"


def test_entries_and_first_root_wins(tmp_path: Path):
    a, b = tmp_path / "a", tmp_path / "b"
    write_component(a, "table", ["table"], [])
    write_component(b, "table", ["dup"], [])
    write_component(b, "line", ["chart"], [])
    lib = ComponentLibrary([a, b])
    ids = sorted(e.manifest.id for e in lib.entries())
    assert ids == ["line", "table"]
    assert lib.get("table") is not None and lib.get("table").manifest.tags == ["table"]
    assert lib.get("nope") is None


def test_search_filters_by_schema_and_ranks_by_tags(tmp_path: Path):
    write_component(tmp_path, "ts", ["chart", "time"], [{"role": "x", "dtype": "datetime"}, {"role": "y", "dtype": "numeric"}])
    write_component(tmp_path, "table", ["table"], [])
    write_component(tmp_path, "scatter", ["chart"], [{"role": "x", "dtype": "numeric", "min": 2}])
    lib = ComponentLibrary([tmp_path])
    with_dates = meta([("date", "Date"), ("ret", "Float64")])
    assert [m.id for m in lib.search(dataset=with_dates, tags=["chart"])] == ["ts", "table"]
    numeric_only = meta([("a", "Int64"), ("b", "Int64")])
    assert [m.id for m in lib.search(dataset=numeric_only, tags=[])] == ["scatter", "table"]
    assert [m.id for m in lib.search(dataset=None, tags=["table"])][0] == "table"
```

- [ ] **Step 2: Write the failing transpile and tool tests**

`tests/agent/test_transpile.py`:

```python
import sys
from pathlib import Path

from quarry.agent.transpile import CommandTranspiler, NoopTranspiler, default_transpiler


def test_noop_accepts_anything():
    assert NoopTranspiler().check("not even code") is None


def test_command_transpiler_reports_stderr_on_failure():
    ok = CommandTranspiler([sys.executable, "-c", "import sys; sys.stdin.read()"])
    assert ok.check("x") is None
    bad = CommandTranspiler([sys.executable, "-c", "import sys; sys.stderr.write('syntax error at 1:3'); sys.exit(1)"])
    assert bad.check("x") == "syntax error at 1:3"


def test_default_transpiler_is_noop_without_bundle(tmp_path: Path):
    assert isinstance(default_transpiler(tmp_path), NoopTranspiler)
```

`tests/agent/test_tools.py`:

```python
import json
from pathlib import Path

import pytest

from quarry.agent.tools import TOOL_DEFS, ToolExecutor
from quarry.agent.transpile import CommandTranspiler, NoopTranspiler
from quarry.agent.types import ToolCall
from quarry.components.library import ComponentLibrary
from quarry.kernel.client import KernelClient
from tests.components.test_library import write_component


@pytest.fixture
def kernel(tmp_path: Path):
    client = KernelClient.spawn(tmp_path)
    yield client
    client.close()


def executor(kernel: KernelClient, tmp_path: Path, transpiler=None) -> ToolExecutor:
    write_component(tmp_path / "lib", "table", ["table"], [])
    return ToolExecutor(kernel=kernel, library=ComponentLibrary([tmp_path / "lib"]), transpiler=transpiler or NoopTranspiler())


def test_tool_defs_names():
    assert [t.name for t in TOOL_DEFS] == ["run_python", "describe_dataset", "search_components", "render_view", "write_view"]


def test_run_python_success_and_failure(kernel: KernelClient, tmp_path: Path):
    ex = executor(kernel, tmp_path)
    ok = ex.run(ToolCall(id="1", name="run_python", input={"code": "df = pl.DataFrame({'a': [1]})"}))
    assert ok.is_error is False
    body = json.loads(ok.content)
    assert body["writes"] == ["df"]
    assert ex.last_python_failed is False
    bad = ex.run(ToolCall(id="2", name="run_python", input={"code": "1/0"}))
    assert bad.is_error is True
    assert "ZeroDivisionError" in bad.content
    assert ex.last_python_failed is True
    assert [r.status for r in ex.exec_results] == ["ok", "error"]


def test_describe_dataset(kernel: KernelClient, tmp_path: Path):
    ex = executor(kernel, tmp_path)
    ex.run(ToolCall(id="1", name="run_python", input={"code": "df = pl.DataFrame({'a': [1, 2]})"}))
    out = ex.run(ToolCall(id="2", name="describe_dataset", input={"name": "df"}))
    assert json.loads(out.content)["rows"] == 2
    missing = ex.run(ToolCall(id="3", name="describe_dataset", input={"name": "zz"}))
    assert missing.is_error is True


def test_search_and_render_view(kernel: KernelClient, tmp_path: Path):
    ex = executor(kernel, tmp_path)
    ex.run(ToolCall(id="1", name="run_python", input={"code": "df = pl.DataFrame({'a': [1]})"}))
    found = ex.run(ToolCall(id="2", name="search_components", input={"dataset": "df", "tags": ["table"]}))
    assert json.loads(found.content)[0]["id"] == "table"
    rendered = ex.run(ToolCall(id="3", name="render_view", input={"component_id": "table", "datasets": ["df"], "initial_state": "{}"}))
    assert rendered.is_error is False
    assert ex.view is not None and ex.view.component_id == "table" and ex.view.source.startswith("export default")
    unknown = ex.run(ToolCall(id="4", name="render_view", input={"component_id": "nope", "datasets": ["df"], "initial_state": "{}"}))
    assert unknown.is_error is True
    missing_ds = ex.run(ToolCall(id="5", name="render_view", input={"component_id": "table", "datasets": ["zz"], "initial_state": "{}"}))
    assert missing_ds.is_error is True


def test_write_view_uses_transpiler(kernel: KernelClient, tmp_path: Path):
    import sys

    failing = CommandTranspiler([sys.executable, "-c", "import sys; sys.stderr.write('bad jsx'); sys.exit(1)"])
    ex = executor(kernel, tmp_path, transpiler=failing)
    ex.run(ToolCall(id="1", name="run_python", input={"code": "df = pl.DataFrame({'a': [1]})"}))
    out = ex.run(ToolCall(id="2", name="write_view", input={"source": "<", "datasets": ["df"], "initial_state": "{}"}))
    assert out.is_error is True and "bad jsx" in out.content
    assert ex.view is None
    ok = executor(kernel, tmp_path)
    good = ok.run(ToolCall(id="3", name="write_view", input={"source": "export default () => null", "datasets": ["df"], "initial_state": '{"k": 1}'}))
    bad_json = ok.run(ToolCall(id="4", name="write_view", input={"source": "export default () => null", "datasets": ["df"], "initial_state": "[1]"}))
    assert bad_json.is_error is True
    assert good.is_error is False
    assert ok.view is not None and ok.view.component_id == "inline" and ok.view.initial_state == {"k": 1}


def test_unknown_tool_and_bad_args(kernel: KernelClient, tmp_path: Path):
    ex = executor(kernel, tmp_path)
    assert ex.run(ToolCall(id="1", name="fly", input={})).is_error is True
    assert ex.run(ToolCall(id="2", name="run_python", input={})).is_error is True
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/components tests/agent/test_transpile.py tests/agent/test_tools.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write library.py**

`src/quarry/components/__init__.py`: empty docstring module. `src/quarry/components/builtin/.gitkeep`: empty.

`src/quarry/components/library.py`:

```python
"""Component manifests and the three-root library (builtin, researcher, team)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quarry.kernel.datasets import DatasetMeta

DtypeClass = Literal["datetime", "numeric", "string", "other"]


class SchemaRequirement(BaseModel):
    role: str
    dtype: Literal["datetime", "numeric", "string", "any"]
    min: int = 1


class ComponentSchema(BaseModel):
    requires: list[SchemaRequirement] = Field(default_factory=list)


class ComponentManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    contract_version: int = 1
    schema_: ComponentSchema = Field(alias="schema", default_factory=ComponentSchema)
    origin: Literal["builtin", "generated", "imported"]
    created_at: str


class ComponentEntry(BaseModel):
    manifest: ComponentManifest
    source_path: Path


def builtin_root() -> Path:
    return Path(__file__).parent / "builtin"


class ComponentLibrary:
    def __init__(self, roots: list[Path]) -> None:
        self._roots = roots

    def entries(self) -> list[ComponentEntry]:
        seen: dict[str, ComponentEntry] = {}
        for root in self._roots:
            if not root.is_dir():
                continue
            for manifest_path in sorted(root.glob("*/manifest.json")):
                source = manifest_path.parent / "component.tsx"
                if not source.exists():
                    continue
                manifest = ComponentManifest.model_validate(json.loads(manifest_path.read_text()))
                seen.setdefault(manifest.id, ComponentEntry(manifest=manifest, source_path=source))
        return list(seen.values())

    def get(self, component_id: str) -> ComponentEntry | None:
        return next((e for e in self.entries() if e.manifest.id == component_id), None)

    def search(self, *, dataset: DatasetMeta | None, tags: list[str]) -> list[ComponentManifest]:
        wanted = set(tags)
        matches = [e.manifest for e in self.entries() if dataset is None or satisfies(e.manifest, dataset)]
        return sorted(matches, key=lambda m: (-len(wanted & set(m.tags)), m.id))


def satisfies(manifest: ComponentManifest, dataset: DatasetMeta) -> bool:
    counts: dict[str, int] = {"datetime": 0, "numeric": 0, "string": 0, "other": 0}
    for col in dataset.schema_:
        counts[dtype_class(col.dtype)] += 1
    for req in manifest.schema_.requires:
        available = len(dataset.schema_) if req.dtype == "any" else counts[req.dtype]
        if available < req.min:
            return False
    return True


def dtype_class(dtype: str) -> DtypeClass:
    if dtype == "Date" or dtype.startswith("Datetime"):
        return "datetime"
    if dtype.startswith(("Int", "UInt", "Float", "Decimal")):
        return "numeric"
    if dtype in {"String", "Utf8"} or dtype.startswith(("Categorical", "Enum")):
        return "string"
    return "other"
```

- [ ] **Step 5: Write transpile.py and tools.py**

`src/quarry/agent/transpile.py`:

```python
"""Server-side syntax check for generated TSX, delegated to a node bundle when present."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Protocol


class Transpiler(Protocol):
    def check(self, source: str) -> str | None: ...


class NoopTranspiler:
    def check(self, source: str) -> str | None:
        return None


class CommandTranspiler:
    def __init__(self, command: list[str]) -> None:
        self._command = command

    def check(self, source: str) -> str | None:
        done = subprocess.run(self._command, input=source, text=True, capture_output=True, check=False)
        return None if done.returncode == 0 else (done.stderr.strip() or f"exit code {done.returncode}")


def default_transpiler(static_dir: Path) -> Transpiler:
    bundle = static_dir / "transpile-check.mjs"
    if shutil.which("node") and bundle.exists():
        return CommandTranspiler(["node", str(bundle)])
    return NoopTranspiler()
```

`src/quarry/agent/tools.py`:

```python
"""The five tools the agent can call, executed against one session's kernel."""

from __future__ import annotations

import json
from typing import Final

from pydantic import BaseModel, Field, ValidationError, field_validator

from quarry.agent.transpile import Transpiler
from quarry.agent.types import ToolCall, ToolDef, ToolResult
from quarry.components.library import ComponentLibrary
from quarry.kernel.client import KernelClient, RpcFailure
from quarry.kernel.executor import ExecResult
from quarry.query.spec import Json

RUN_PYTHON: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": (
                "Python to execute in the session kernel. polars is `pl`, duckdb is `duckdb`, "
                "loaders under `loaders.*`, `sql(query)`, `pq(glob)`, `sql_local(query)`. Assign results "
                "to well-named top-level variables; every top-level DataFrame, LazyFrame or DuckDB "
                "relation becomes a dataset."
            ),
        }
    },
    "required": ["code"],
}
DESCRIBE_DATASET: Final[dict[str, Json]] = {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}
SEARCH_COMPONENTS: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {
        "dataset": {"type": "string", "description": "Dataset the component should render; filters by schema compatibility."},
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["dataset", "tags"],
}
RENDER_VIEW: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {
        "component_id": {"type": "string"},
        "datasets": {"type": "array", "items": {"type": "string"}},
        "initial_state": {"type": "string", "description": 'JSON object encoded as a string, e.g. "{}"'},
    },
    "required": ["component_id", "datasets", "initial_state"],
}
WRITE_VIEW: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": (
                "A TSX module whose default export is the component. Only `react`, the design system, "
                "the chart libraries listed in the guide, and the hooks module may be imported."
            ),
        },
        "datasets": {"type": "array", "items": {"type": "string"}},
        "initial_state": {"type": "string", "description": 'JSON object encoded as a string, e.g. "{}"'},
    },
    "required": ["source", "datasets", "initial_state"],
}

TOOL_DEFS: Final[list[ToolDef]] = [
    ToolDef(name="run_python", description="Execute Python in the session kernel and register any datasets it assigns.", input_schema=RUN_PYTHON),
    ToolDef(name="describe_dataset", description="Schema, row count and preview of a dataset.", input_schema=DESCRIBE_DATASET),
    ToolDef(name="search_components", description="Find library components compatible with a dataset, ranked by tags.", input_schema=SEARCH_COMPONENTS),
    ToolDef(name="render_view", description="Mount a library component against named datasets.", input_schema=RENDER_VIEW),
    ToolDef(name="write_view", description="Mount a new TSX component you wrote against named datasets.", input_schema=WRITE_VIEW),
]


class PendingView(BaseModel):
    component_id: str
    source: str
    initial_state: dict[str, Json] = Field(default_factory=dict)
    datasets: list[str] = Field(default_factory=list)


class _RunPython(BaseModel):
    code: str


class _Describe(BaseModel):
    name: str


class _Search(BaseModel):
    dataset: str
    tags: list[str] = Field(default_factory=list)


def _parse_state(value: object) -> dict[str, Json]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError("initial_state must be a JSON object string")
    parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("initial_state must encode a JSON object")
    return parsed


class _Render(BaseModel):
    component_id: str
    datasets: list[str]
    initial_state: dict[str, Json] = Field(default_factory=dict)

    @field_validator("initial_state", mode="before")
    @classmethod
    def _state(cls, value: object) -> dict[str, Json]:
        return _parse_state(value)


class _Write(BaseModel):
    source: str
    datasets: list[str]
    initial_state: dict[str, Json] = Field(default_factory=dict)

    @field_validator("initial_state", mode="before")
    @classmethod
    def _state(cls, value: object) -> dict[str, Json]:
        return _parse_state(value)


class ToolExecutor:
    def __init__(self, *, kernel: KernelClient, library: ComponentLibrary, transpiler: Transpiler) -> None:
        self._kernel = kernel
        self._library = library
        self._transpiler = transpiler
        self.view: PendingView | None = None
        self.last_python_failed = False
        self.exec_results: list[ExecResult] = []

    def run(self, call: ToolCall) -> ToolResult:
        try:
            match call.name:
                case "run_python":
                    return self._run_python(call, _RunPython.model_validate(call.input))
                case "describe_dataset":
                    return self._describe(call, _Describe.model_validate(call.input))
                case "search_components":
                    return self._search(call, _Search.model_validate(call.input))
                case "render_view":
                    return self._render(call, _Render.model_validate(call.input))
                case "write_view":
                    return self._write(call, _Write.model_validate(call.input))
                case _:
                    return _error(call, f"unknown tool {call.name!r}")
        except ValidationError as exc:
            return _error(call, f"invalid arguments: {exc}")

    def _run_python(self, call: ToolCall, args: _RunPython) -> ToolResult:
        result = self._kernel.execute(args.code)
        self.exec_results.append(result)
        self.last_python_failed = result.status != "ok"
        content = result.model_dump(by_alias=True, mode="json")
        return ToolResult(call_id=call.id, content=json.dumps(content), is_error=result.status != "ok")

    def _describe(self, call: ToolCall, args: _Describe) -> ToolResult:
        try:
            meta = self._kernel.describe(args.name)
        except RpcFailure as exc:
            return _error(call, str(exc))
        return ToolResult(call_id=call.id, content=meta.model_dump_json(by_alias=True))

    def _search(self, call: ToolCall, args: _Search) -> ToolResult:
        try:
            meta = self._kernel.describe(args.dataset)
        except RpcFailure as exc:
            return _error(call, str(exc))
        found = self._library.search(dataset=meta, tags=args.tags)
        return ToolResult(call_id=call.id, content=json.dumps([m.model_dump(by_alias=True) for m in found]))

    def _render(self, call: ToolCall, args: _Render) -> ToolResult:
        entry = self._library.get(args.component_id)
        if entry is None:
            return _error(call, f"no component {args.component_id!r}")
        missing = self._missing_datasets(args.datasets)
        if missing:
            return _error(call, f"unknown datasets: {missing}")
        self.view = PendingView(
            component_id=args.component_id,
            source=entry.source_path.read_text(),
            initial_state=args.initial_state,
            datasets=args.datasets,
        )
        return ToolResult(call_id=call.id, content=json.dumps({"mounted": args.component_id}))

    def _write(self, call: ToolCall, args: _Write) -> ToolResult:
        missing = self._missing_datasets(args.datasets)
        if missing:
            return _error(call, f"unknown datasets: {missing}")
        problem = self._transpiler.check(args.source)
        if problem is not None:
            return _error(call, f"transpile error: {problem}")
        self.view = PendingView(component_id="inline", source=args.source, initial_state=args.initial_state, datasets=args.datasets)
        return ToolResult(call_id=call.id, content=json.dumps({"mounted": "inline"}))

    def _missing_datasets(self, names: list[str]) -> list[str]:
        known = {m.name for m in self._kernel.list_datasets()}
        return [n for n in names if n not in known]


def _error(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(call_id=call.id, content=json.dumps({"error": message}), is_error=True)
```

- [ ] **Step 6: Run tests, format, commit**

Run: `uv run pytest tests/components tests/agent -v` → all pass.

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/components src/quarry/agent tests/components tests/agent
git commit -m "feat: component library, transpile check protocol, and the five agent tools"
```

---

### Task 6: Session and step models with the on-disk store

**Files:**

- Create: `src/quarry/server/__init__.py`
- Create: `src/quarry/server/models.py`
- Create: `src/quarry/server/store.py`
- Test: `tests/server/__init__.py`
- Test: `tests/server/test_store.py`

**Interfaces:**

- Consumes: `DatasetMeta`, `ExecError` (Stage 1), `Message` (Task 2), `Json`.
- Produces (in `quarry.server.models`):
  - `StepKind = Literal["prompt", "manual", "load", "recall"]`; `StepStatus = Literal["running", "ok", "error", "interrupted"]`
  - `class Snapshot(BaseModel)`: `ts: str`, `state: dict[str, Json]`, `queries: list[dict[str, Json]]`
  - `class View(BaseModel)`: `component_id: str`, `content_hash: str`, `source: str`, `initial_state: dict[str, Json]`, `datasets: list[str]`, `snapshots: list[Snapshot] = []`; `@classmethod from_pending(cls, pending: PendingView) -> View` (sha256 of source)
  - `class Step(BaseModel)`: `id: str`, `index: int`, `kind: StepKind`, `prompt: str | None`, `code: str`, `status: StepStatus`, `error: ExecError | None`, `note: str = ""`, `stdout_tail: str = ""`, `stderr_tail: str = ""`, `reads: list[str] = []`, `writes: list[str] = []`, `defines: list[str] = []`, `datasets: list[DatasetMeta] = []`, `view: View | None = None`, `transcript: list[Message] | None = None`, `created_at: str`, `duration_ms: int = 0`
  - `class ProviderInfo(BaseModel)`: `name: str`, `model: str`
  - `class KernelStatus(BaseModel)`: `status: Literal["starting", "idle", "running", "dead"]`, `pid: int | None = None`
  - `class SessionMeta(BaseModel)`: `id: str`, `title: str`, `created_at: str`, `provider: ProviderInfo`
  - `class Session(BaseModel)`: `meta: SessionMeta`, `steps: list[Step]`
  - `def now_iso() -> str`, `def new_id() -> str` (12 hex chars from `secrets.token_hex(6)`)
- Produces (in `quarry.server.store`): `class SessionStore`: `__init__(self, root: Path)` (uses `root / "sessions"`); `create(self, *, title: str, provider: ProviderInfo) -> SessionMeta`; `list(self) -> list[SessionMeta]` newest first; `get(self, session_id: str) -> Session` raising `KeyError`; `append_step(self, session_id: str, step: Step) -> None` writing `steps/NNNN.json` (`index` zero-padded to four digits); `next_index(self, session_id: str) -> int`. A step with `status == "running"` is rejected with `ValueError`.

- [ ] **Step 1: Write the failing tests**

`tests/server/__init__.py`: empty.

`tests/server/test_store.py`:

```python
from pathlib import Path

import pytest

from quarry.agent.tools import PendingView
from quarry.server.models import ProviderInfo, Step, View, now_iso
from quarry.server.store import SessionStore


def step(index: int, status: str = "ok") -> Step:
    return Step(id=f"s{index}", index=index, kind="prompt", prompt="p", code="x = 1", status=status, error=None, created_at=now_iso())


def test_create_list_get(tmp_path: Path):
    store = SessionStore(tmp_path)
    a = store.create(title="first", provider=ProviderInfo(name="anthropic", model="claude-opus-5-5"))
    b = store.create(title="second", provider=ProviderInfo(name="anthropic", model="claude-opus-5-5"))
    assert [m.id for m in store.list()] == [b.id, a.id]
    assert store.get(a.id).meta.title == "first"
    assert store.get(a.id).steps == []
    with pytest.raises(KeyError):
        store.get("missing")


def test_append_and_reload_steps(tmp_path: Path):
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    assert store.next_index(meta.id) == 0
    store.append_step(meta.id, step(0))
    store.append_step(meta.id, step(1))
    assert store.next_index(meta.id) == 2
    reloaded = SessionStore(tmp_path).get(meta.id)
    assert [s.index for s in reloaded.steps] == [0, 1]
    assert (tmp_path / "sessions" / meta.id / "steps" / "0001.json").exists()


def test_running_step_is_rejected(tmp_path: Path):
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    with pytest.raises(ValueError, match="running"):
        store.append_step(meta.id, step(0, status="running"))


def test_view_from_pending_hashes_source():
    pending = PendingView(component_id="inline", source="export default () => null", initial_state={"a": 1}, datasets=["df"])
    view = View.from_pending(pending)
    assert len(view.content_hash) == 64
    assert view.initial_state == {"a": 1} and view.datasets == ["df"] and view.snapshots == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/server/test_store.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`src/quarry/server/__init__.py`: empty docstring module.

`src/quarry/server/models.py`:

```python
"""Session, step, and view records as persisted on disk."""

from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, Field

from quarry.agent.tools import PendingView
from quarry.agent.types import Message
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import ExecError
from quarry.query.spec import Json

StepKind = Literal["prompt", "manual", "load", "recall"]
StepStatus = Literal["running", "ok", "error", "interrupted"]


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def new_id() -> str:
    return secrets.token_hex(6)


class Snapshot(BaseModel):
    ts: str
    state: dict[str, Json]
    queries: list[dict[str, Json]]


class View(BaseModel):
    component_id: str
    content_hash: str
    source: str
    initial_state: dict[str, Json] = Field(default_factory=dict)
    datasets: list[str] = Field(default_factory=list)
    snapshots: list[Snapshot] = Field(default_factory=list)

    @classmethod
    def from_pending(cls, pending: PendingView) -> View:
        digest = hashlib.sha256(pending.source.encode("utf-8")).hexdigest()
        return cls(
            component_id=pending.component_id,
            content_hash=digest,
            source=pending.source,
            initial_state=pending.initial_state,
            datasets=pending.datasets,
        )


class Step(BaseModel):
    id: str
    index: int
    kind: StepKind
    prompt: str | None
    code: str
    status: StepStatus
    error: ExecError | None
    note: str = ""
    stdout_tail: str = ""
    stderr_tail: str = ""
    reads: list[str] = Field(default_factory=list)
    writes: list[str] = Field(default_factory=list)
    defines: list[str] = Field(default_factory=list)
    datasets: list[DatasetMeta] = Field(default_factory=list)
    view: View | None = None
    transcript: list[Message] | None = None
    created_at: str
    duration_ms: int = 0


class ProviderInfo(BaseModel):
    name: str
    model: str


class KernelStatus(BaseModel):
    status: Literal["starting", "idle", "running", "dead"]
    pid: int | None = None


class SessionMeta(BaseModel):
    id: str
    title: str
    created_at: str
    provider: ProviderInfo


class Session(BaseModel):
    meta: SessionMeta
    steps: list[Step]
```

`src/quarry/server/store.py`:

```python
"""Sessions on disk: one directory per session, one JSON file per completed step."""

from __future__ import annotations

from pathlib import Path

from quarry.server.models import ProviderInfo, Session, SessionMeta, Step, new_id, now_iso


class SessionStore:
    def __init__(self, root: Path) -> None:
        self._dir = root / "sessions"

    def create(self, *, title: str, provider: ProviderInfo) -> SessionMeta:
        meta = SessionMeta(id=new_id(), title=title, created_at=now_iso(), provider=provider)
        path = self._dir / meta.id
        (path / "steps").mkdir(parents=True)
        (path / "session.json").write_text(meta.model_dump_json(indent=2))
        return meta

    def list(self) -> list[SessionMeta]:
        if not self._dir.is_dir():
            return []
        metas = [SessionMeta.model_validate_json((p / "session.json").read_text()) for p in self._dir.iterdir() if (p / "session.json").exists()]
        return sorted(metas, key=lambda m: m.created_at, reverse=True)

    def get(self, session_id: str) -> Session:
        path = self._dir / session_id / "session.json"
        if not path.exists():
            raise KeyError(session_id)
        meta = SessionMeta.model_validate_json(path.read_text())
        steps = [Step.model_validate_json(p.read_text()) for p in sorted((self._dir / session_id / "steps").glob("*.json"))]
        return Session(meta=meta, steps=steps)

    def append_step(self, session_id: str, step: Step) -> None:
        if step.status == "running":
            raise ValueError("a running step cannot be persisted")
        self.get(session_id)
        target = self._dir / session_id / "steps" / f"{step.index:04d}.json"
        target.write_text(step.model_dump_json(by_alias=True, indent=2))

    def next_index(self, session_id: str) -> int:
        return len(list((self._dir / session_id / "steps").glob("*.json")))
```

- [ ] **Step 4: Run tests, format, commit**

Run: `uv run pytest tests/server/test_store.py -v` → 4 passed.

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/server tests/server
git commit -m "feat: session and step models with on-disk session store"
```

---

### Task 7: Context builder

**Files:**

- Create: `src/quarry/agent/context.py`
- Create: `src/quarry/agent/guide.md`
- Test: `tests/agent/test_context.py`

**Interfaces:**

- Consumes: `Step`, `DatasetMeta`, `QuarryConfig`, `describe_loaders`, `LoaderRegistry`, `PartitionLayout`.
- Produces:
  - `def estimate_tokens(text: str) -> int` = `len(text) // 4`
  - `class SystemContext(BaseModel)`: `loaders: str`, `layout: list[PartitionLayout]`, `enabled_libraries: list[str]`
  - `def build_system(ctx: SystemContext) -> str`: the contract, the three hooks, the library guide filtered to enabled libraries, loaders, layout, and the "computation belongs in Python and query specs" rule. Deterministic: same input, same string (no timestamps).
  - `def enabled_libraries(config: QuarryConfig) -> list[str]`: always `["lightweight-charts", "plotly", "echarts", "recharts", "perspective", "ag-grid", "tanstack-table", "d3"]`, plus `"highcharts"` when `libraries.highcharts_license` is set, `"scichart"` when `libraries.scichart_license` is set.
  - `def build_summary(steps: list[Step], datasets: list[DatasetMeta], *, budget_tokens: int = 24000, keep_full: int = 8) -> str`: for each prior step a block with its prompt and code; once the full rendering exceeds the budget, steps older than the last `keep_full` collapse to prompt plus `writes`. Ends with the dataset list (name, backing, rows, columns with dtypes).
- `guide.md` holds the library guide text from spec section 8 with one `## <library-id>` heading per library so `build_system` can filter sections by id.

- [ ] **Step 1: Write guide.md**

`src/quarry/agent/guide.md`:

```markdown
## lightweight-charts

Price and return series, OHLC. Use when speed and a clean look matter more than annotations. Import `createChart` from "lightweight-charts". Keep the attribution logo enabled.

## plotly

Scatter, heatmap, 3D, statistical plots, anything general. Import `Plot` from "react-plotly.js".

## echarts

Series with more than about 100k points, calendar and sankey. Import `ReactECharts` from "echarts-for-react".

## recharts

Small aggregated bar and line charts inside shadcn layouts. Import from "recharts".

## perspective

When the researcher should drive pivots and filters directly. Import `PerspectiveViewer` from "@quarry/perspective". Request `format: "arrow"` in its query.

## ag-grid

Tables with column filters and resizing. Import `AgGridReact` from "ag-grid-react".

## tanstack-table

Tables that need custom cell rendering inside shadcn styling. Import from "@tanstack/react-table".

## d3

Only when nothing above fits. Import from "d3".

## highcharts

Full stock charts: navigator, range selector, indicators, annotations. Import `HighchartsReact` from "highcharts-react-official" with `Highcharts` from "highcharts/highstock".

## scichart

Very large series and realtime rendering. Import from "scichart-react".
```

- [ ] **Step 2: Write the failing tests**

`tests/agent/test_context.py`:

```python
from pathlib import Path

from quarry.agent.context import SystemContext, build_summary, build_system, enabled_libraries, estimate_tokens
from quarry.config import QuarryConfig
from quarry.data.parquet import PartitionLayout
from quarry.kernel.datasets import Column, DatasetMeta
from quarry.server.models import Step, now_iso


def test_estimate_tokens():
    assert estimate_tokens("a" * 400) == 100


def test_enabled_libraries(tmp_path: Path):
    base = enabled_libraries(QuarryConfig(root=tmp_path))
    assert "plotly" in base and "highcharts" not in base
    cfg = QuarryConfig.model_validate({"root": tmp_path, "libraries": {"highcharts_license": "k"}})
    assert "highcharts" in enabled_libraries(cfg)


def test_build_system_is_deterministic_and_filtered():
    ctx = SystemContext(loaders="loaders.x: x() -- d", layout=[PartitionLayout(dataset="prices", keys=["year"])], enabled_libraries=["plotly", "ag-grid"])
    a = build_system(ctx)
    b = build_system(ctx)
    assert a == b
    assert "useQuery" in a and "useViewState" in a and "useDatasetSchema" in a
    assert "## plotly" in a and "## ag-grid" in a and "## highcharts" not in a and "## recharts" not in a
    assert "loaders.x" in a and "prices" in a and "year" in a


def step(i: int, prompt: str, code: str, writes: list[str]) -> Step:
    return Step(id=f"s{i}", index=i, kind="prompt", prompt=prompt, code=code, status="ok", error=None, writes=writes, created_at=now_iso())


def test_build_summary_full_when_under_budget():
    steps = [step(0, "load", "a = 1", ["a"]), step(1, "filter", "b = a", ["b"])]
    ds = [DatasetMeta(name="b", backing="polars", schema=[Column(name="x", dtype="Int64")], rows=3, preview=[])]
    text = build_summary(steps, ds)
    assert "load" in text and "a = 1" in text and "b = a" in text
    assert "b (polars, 3 rows): x: Int64" in text


def test_build_summary_collapses_old_steps_over_budget():
    steps = [step(i, f"prompt {i}", "x" * 4000, [f"d{i}"]) for i in range(12)]
    text = build_summary(steps, [], budget_tokens=5000, keep_full=8)
    assert "prompt 0" in text and "d0" in text
    assert text.count("x" * 4000) == 8
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_context.py -v` → `ModuleNotFoundError`

- [ ] **Step 4: Write the implementation**

`src/quarry/agent/context.py`:

````python
"""System prompt and per-step session summary for the agent."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from pydantic import BaseModel, Field

from quarry.config import QuarryConfig
from quarry.data.parquet import PartitionLayout
from quarry.kernel.datasets import DatasetMeta
from quarry.server.models import Step

GUIDE_PATH: Final = Path(__file__).parent / "guide.md"
ALWAYS_ON: Final[list[str]] = [
    "lightweight-charts", "plotly", "echarts", "recharts", "perspective", "ag-grid", "tanstack-table", "d3",
]

CONTRACT: Final = """You are Quarry, a data exploration agent for a quant researcher. You work in a persistent
Python kernel through the run_python tool. polars is `pl`, duckdb is `duckdb`. Every top-level
DataFrame, LazyFrame or DuckDB relation you assign becomes a named dataset the researcher can see.
Name variables well. Do computation in Python, never in view JavaScript.

After producing data, show it: call search_components and render_view for routine tables and
charts, or write_view with a TSX component when nothing in the library fits. A component's default
export is the component. It may import react, the design system (@/components/ui/*), the chart
libraries listed below, and exactly these hooks from "@quarry/hooks":

  useQuery(spec): {status:"loading"} | {status:"success", rows, schema} | {status:"error", message}
    spec = {dataset, select?, filters?, group_by?, aggs?, pivot?, sort?, limit?, offset?, format?}
  useViewState(key, initial): [value, setValue]  (recorded; keys starting with "shared:" are linked)
  useDatasetSchema(name): Column[] | null

Push filtering, grouping and pivoting into the query spec so the researcher's manipulations can be
turned back into Python. Keep answers short; the researcher sees the data, not your prose."""


class SystemContext(BaseModel):
    loaders: str = ""
    layout: list[PartitionLayout] = Field(default_factory=list)
    enabled_libraries: list[str] = Field(default_factory=list)


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def enabled_libraries(config: QuarryConfig) -> list[str]:
    extra = []
    if config.libraries.highcharts_license:
        extra.append("highcharts")
    if config.libraries.scichart_license:
        extra.append("scichart")
    return [*ALWAYS_ON, *extra]


def build_system(ctx: SystemContext) -> str:
    sections = [CONTRACT, "# Chart and table libraries", _guide_for(ctx.enabled_libraries)]
    if ctx.loaders:
        sections += ["# Registered loaders (call as loaders.<name>)", ctx.loaders]
    if ctx.layout:
        lines = [f"- {l.dataset}: partitioned by {', '.join(l.keys)}" for l in ctx.layout]
        sections += ["# Parquet cache layout (use pq('<dataset>/**/*.parquet'))", "\n".join(lines)]
    sections += ["# Data helpers", "sql(query) -> SQL Server as polars. pq(glob) -> DuckDB relation over the cache. sql_local(query) -> DuckDB over registered frames."]
    return "\n\n".join(sections)


def build_summary(steps: list[Step], datasets: list[DatasetMeta], *, budget_tokens: int = 24000, keep_full: int = 8) -> str:
    blocks = [_full_block(s) for s in steps]
    if estimate_tokens("\n".join(blocks)) > budget_tokens:
        cutoff = max(len(steps) - keep_full, 0)
        blocks = [_short_block(s) for s in steps[:cutoff]] + [_full_block(s) for s in steps[cutoff:]]
    ds_lines = [f"- {d.name} ({d.backing}, {d.rows if d.rows is not None else '?'} rows): " + ", ".join(f"{c.name}: {c.dtype}" for c in d.schema_) for d in datasets]
    return "\n".join(["# Session so far", *blocks, "", "# Datasets in the kernel", *ds_lines])


def _full_block(s: Step) -> str:
    head = f"## Step {s.index} ({s.kind}, {s.status})"
    prompt = f"Prompt: {s.prompt}" if s.prompt else ""
    return "\n".join(x for x in [head, prompt, "```python", s.code, "```"] if x)


def _short_block(s: Step) -> str:
    return f"## Step {s.index} ({s.kind}, {s.status}) Prompt: {s.prompt or ''} Wrote: {', '.join(s.writes) or 'nothing'}"


def _guide_for(enabled: list[str]) -> str:
    text = GUIDE_PATH.read_text()
    sections = [f"## {part}" for part in text.split("## ")[1:]]
    keep = [sec for sec in sections if sec.split("\n", 1)[0].strip() in {f"## {e}" for e in enabled}]
    return "\n".join(keep)
````

Add `"src/quarry/agent/guide.md"` is picked up by hatch automatically since it lives inside the package directory; confirm with `uv build` once in Task 11.

- [ ] **Step 5: Run tests, format, commit**

Run: `uv run pytest tests/agent/test_context.py -v` → 5 passed.

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/agent tests/agent
git commit -m "feat: agent system prompt, library guide, and collapsing session summary"
```

---

### Task 8: Agent loop

**Files:**

- Create: `src/quarry/agent/loop.py`
- Test: `tests/agent/test_loop.py`

**Interfaces:**

- Consumes: `Provider`, `AssistantTurn`, `Message`, `ToolResult`, `ProviderError` (Task 2); `ToolExecutor`, `TOOL_DEFS`, `PendingView` (Task 5); `KernelDead`.
- Produces:
  - `class StepOutcome(BaseModel)`: `status: Literal["ok", "error", "interrupted"]`, `note: str`, `transcript: list[Message]`, `error_message: str | None`, `view: PendingView | None`, `code: str` (every `run_python` code joined by two newlines, in order), `iterations: int`, `exec_results: list[ExecResult]` (copied from the executor)
  - `def step_lineage(results: list[ExecResult]) -> Lineage` with `class Lineage(BaseModel)`: `reads`, `writes`, `defines: list[str]`, `datasets: list[DatasetMeta]`. `writes` = union of call writes; `reads` = union of call reads minus names written by an earlier call in the same step; `defines` = union; `datasets` = the last `DatasetMeta` per written name. All sorted by name.
  - `def run_agent_step(*, prompt: str, system: str, summary: str, provider: Provider, tools: ToolExecutor, max_iterations: int = 12) -> StepOutcome`. Rules: first user message is `summary + "\n\n# Request\n" + prompt`; loop until `stop == "end"`; `refusal` → error with the reason; `max_tokens` → error "response truncated"; a `ProviderError` → error with its message; `KernelDead` → error "kernel died" with status `error`; a `run_python` result whose `status` is `interrupted` → outcome `interrupted`; two consecutive `run_python` errors → stop, status `error`, `error_message` from the last traceback; after `max_iterations` provider calls → error "iteration cap reached". Every tool result for one turn goes back in a single user message.

- [ ] **Step 1: Write the failing tests**

`tests/agent/test_loop.py`:

```python
import json
from pathlib import Path

import pytest

from quarry.agent.fake import FakeProvider
from quarry.agent.loop import run_agent_step, step_lineage
from quarry.agent.tools import ToolExecutor
from quarry.agent.transpile import NoopTranspiler
from quarry.agent.types import AssistantTurn, ProviderError, ToolCall
from quarry.components.library import ComponentLibrary
from quarry.kernel.client import KernelClient


@pytest.fixture
def kernel(tmp_path: Path):
    client = KernelClient.spawn(tmp_path)
    yield client
    client.close()


def tools(kernel: KernelClient, tmp_path: Path) -> ToolExecutor:
    return ToolExecutor(kernel=kernel, library=ComponentLibrary([tmp_path / "none"]), transpiler=NoopTranspiler())


def py(call_id: str, code: str) -> AssistantTurn:
    return AssistantTurn(text="", tool_calls=[ToolCall(id=call_id, name="run_python", input={"code": code})], stop="tool_use")


def end(text: str = "done") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], stop="end")


def run(provider: FakeProvider, kernel: KernelClient, tmp_path: Path, **kw):
    return run_agent_step(prompt="load", system="sys", summary="# Session so far", provider=provider, tools=tools(kernel, tmp_path), **kw)


def test_happy_path_runs_code_and_records_transcript(kernel, tmp_path):
    provider = FakeProvider([py("c1", "df = pl.DataFrame({'a': [1]})"), end("loaded")])
    out = run(provider, kernel, tmp_path)
    assert out.status == "ok" and out.note == "loaded"
    assert out.code == "df = pl.DataFrame({'a': [1]})"
    assert out.iterations == 2
    assert [m.role for m in out.transcript] == ["user", "assistant", "user", "assistant"]
    assert out.transcript[0].text.startswith("# Session so far") and out.transcript[0].text.endswith("# Request\nload")
    assert json.loads(out.transcript[2].tool_results[0].content)["writes"] == ["df"]


def test_second_consecutive_python_error_ends_step(kernel, tmp_path):
    provider = FakeProvider([py("c1", "1/0"), py("c2", "1/0"), end()])
    out = run(provider, kernel, tmp_path)
    assert out.status == "error"
    assert out.error_message is not None and "ZeroDivisionError" in out.error_message
    assert out.iterations == 2
    assert len(provider.calls) == 2


def test_one_error_then_success_is_ok(kernel, tmp_path):
    provider = FakeProvider([py("c1", "1/0"), py("c2", "x = 1"), end()])
    assert run(provider, kernel, tmp_path).status == "ok"


def test_refusal_and_truncation(kernel, tmp_path):
    refused = run(FakeProvider([AssistantTurn(text="", tool_calls=[], stop="refusal", refusal_reason="no")]), kernel, tmp_path)
    assert refused.status == "error" and refused.error_message == "no"
    truncated = run(FakeProvider([AssistantTurn(text="partial", tool_calls=[], stop="max_tokens")]), kernel, tmp_path)
    assert truncated.status == "error" and "truncated" in (truncated.error_message or "")


def test_iteration_cap(kernel, tmp_path):
    provider = FakeProvider([py(f"c{i}", "x = 1") for i in range(5)])
    out = run(provider, kernel, tmp_path, max_iterations=3)
    assert out.status == "error" and "iteration cap" in (out.error_message or "")
    assert out.iterations == 3


def test_provider_error_fails_step(kernel, tmp_path):
    class Boom:
        def complete(self, **kw):
            raise ProviderError("rate limited", retryable=True)

    out = run_agent_step(prompt="p", system="s", summary="", provider=Boom(), tools=tools(kernel, tmp_path))
    assert out.status == "error" and out.error_message == "rate limited"


def test_interrupted_python_marks_step_interrupted(kernel, tmp_path):
    provider = FakeProvider([py("c1", "raise KeyboardInterrupt"), end()])
    assert run(provider, kernel, tmp_path).status == "interrupted"


def test_step_lineage_self_rebinding_keeps_read_edge():
    from quarry.agent.loop import step_lineage
    from quarry.kernel.executor import ExecResult

    def res(reads, writes):
        return ExecResult(status="ok", stdout_tail="", stderr_tail="", error=None, reads=reads, writes=writes, defines=[], datasets=[], duration_ms=0)

    one = step_lineage([res(["df"], ["df"])])
    assert one.reads == ["df"] and one.writes == ["df"]
    two = step_lineage([res([], ["tmp"]), res(["tmp", "prices"], ["out"])])
    assert two.reads == ["prices"] and two.writes == ["out", "tmp"]


def test_view_is_captured(kernel, tmp_path):
    turns = [
        py("c1", "df = pl.DataFrame({'a': [1]})"),
        AssistantTurn(text="", tool_calls=[ToolCall(id="c2", name="write_view", input={"source": "export default () => null", "datasets": ["df"], "initial_state": "{}"})], stop="tool_use"),
        end(),
    ]
    out = run(FakeProvider(turns), kernel, tmp_path)
    assert out.view is not None and out.view.component_id == "inline"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/agent/test_loop.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`src/quarry/agent/loop.py`:

```python
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


class StepOutcome(BaseModel):
    status: Literal["ok", "error", "interrupted"]
    note: str
    transcript: list[Message]
    error_message: str | None
    view: PendingView | None
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

    def finish(status: Literal["ok", "error", "interrupted"], note: str = "", error: str | None = None) -> StepOutcome:
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
            if call.name == "run_python" and isinstance(call.input.get("code"), str):
                code_blocks.append(str(call.input["code"]))
            try:
                result = tools.run(call)
            except KernelDead:
                return finish("error", error="kernel died during execution")
            results.append(result)
            if call.name == "run_python":
                status = _python_status(result)
                if status == "interrupted":
                    transcript.append(Message(role="user", tool_results=results))
                    return finish("interrupted", error="interrupted by researcher")
                consecutive_failures = consecutive_failures + 1 if result.is_error else 0
        transcript.append(Message(role="user", tool_results=results))
        if consecutive_failures >= 2:
            return finish("error", error=_last_traceback(results))
    return finish("error", error=f"iteration cap reached ({max_iterations})")


def _python_status(result: ToolResult) -> str:
    try:
        return str(json.loads(result.content).get("status", ""))
    except json.JSONDecodeError:
        return ""


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
```

- [ ] **Step 4: Run tests, format, commit**

Run: `uv run pytest tests/agent/test_loop.py -v` → 8 passed.

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/agent tests/agent
git commit -m "feat: agent loop with repair-once rule, refusal handling, and iteration cap"
```

---

### Task 9: Kernel manager with restart and replay

**Files:**

- Create: `src/quarry/server/kernels.py`
- Test: `tests/server/test_kernels.py`

**Interfaces:**

- Consumes: `KernelClient`, `KernelDead`, `Step`, `KernelStatus`.
- Produces: `class ReplayReport(BaseModel)`: `replayed: int`, `failed_step: int | None`, `error: str | None`; `class KernelManager`: `__init__(self, root: Path)`; `get(self, session_id: str) -> KernelClient` (spawn on first use or if the previous one is dead); `status(self, session_id: str) -> KernelStatus` (`idle` if alive and no step running, `running` while `mark_running` is set, `dead` if the client exists and is not alive, `starting` if never spawned); `mark_running(self, session_id: str, running: bool) -> None`; `restart(self, session_id: str, steps: list[Step]) -> ReplayReport` (close the old client, spawn a new one, execute each step's `code` in index order, stop at the first non-ok result); `close_all(self) -> None`.

- [ ] **Step 1: Write the failing tests**

`tests/server/test_kernels.py`:

```python
from pathlib import Path

import pytest

from quarry.server.kernels import KernelManager
from quarry.server.models import Step, now_iso


def step(i: int, code: str) -> Step:
    return Step(id=f"s{i}", index=i, kind="manual", prompt=None, code=code, status="ok", error=None, created_at=now_iso())


@pytest.fixture
def manager(tmp_path: Path):
    m = KernelManager(tmp_path)
    yield m
    m.close_all()


def test_get_spawns_once_and_status(manager: KernelManager):
    assert manager.status("s").status == "starting"
    a = manager.get("s")
    assert manager.get("s") is a
    assert manager.status("s").status == "idle"
    manager.mark_running("s", True)
    assert manager.status("s").status == "running"
    manager.mark_running("s", False)


def test_dead_kernel_is_detected_and_respawned(manager: KernelManager):
    a = manager.get("s")
    with pytest.raises(Exception):
        a.execute("import os\nos._exit(1)\n")
    assert manager.status("s").status == "dead"
    b = manager.get("s")
    assert b is not a and b.execute("x = 1").status == "ok"


def test_restart_replays_in_order_and_stops_on_failure(manager: KernelManager):
    k = manager.get("s")
    k.execute("x = 1")
    report = manager.restart("s", [step(0, "a = 1"), step(1, "b = a + 1"), step(2, "c = zzz"), step(3, "d = 1")])
    assert report.replayed == 2
    assert report.failed_step == 2
    assert report.error is not None and "NameError" in report.error
    fresh = manager.get("s")
    assert fresh is not k
    assert fresh.execute("print(b)").stdout_tail.strip() == "2"
    assert fresh.execute("print(d)").status == "error"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/server/test_kernels.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`src/quarry/server/kernels.py`:

```python
"""One kernel per session, with restart-and-replay."""

from __future__ import annotations

import threading
from pathlib import Path

from pydantic import BaseModel

from quarry.kernel.client import KernelClient
from quarry.server.models import KernelStatus, Step


class ReplayReport(BaseModel):
    replayed: int
    failed_step: int | None
    error: str | None


class KernelManager:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._clients: dict[str, KernelClient] = {}
        self._running: set[str] = set()
        self._lock = threading.Lock()

    def get(self, session_id: str) -> KernelClient:
        with self._lock:
            client = self._clients.get(session_id)
            if client is None or not client.is_alive():
                if client is not None:
                    client.close()
                client = KernelClient.spawn(self._root)
                self._clients[session_id] = client
            return client

    def status(self, session_id: str) -> KernelStatus:
        client = self._clients.get(session_id)
        if client is None:
            return KernelStatus(status="starting")
        if not client.is_alive():
            return KernelStatus(status="dead")
        return KernelStatus(status="running" if session_id in self._running else "idle")

    def mark_running(self, session_id: str, running: bool) -> None:
        if running:
            self._running.add(session_id)
        else:
            self._running.discard(session_id)

    def restart(self, session_id: str, steps: list[Step]) -> ReplayReport:
        with self._lock:
            old = self._clients.pop(session_id, None)
            if old is not None:
                old.close()
        client = self.get(session_id)
        for step in sorted(steps, key=lambda s: s.index):
            result = client.execute(step.code)
            if result.status != "ok":
                message = result.error.traceback if result.error else result.status
                return ReplayReport(replayed=step.index, failed_step=step.index, error=message)
        return ReplayReport(replayed=len(steps), failed_step=None, error=None)

    def close_all(self) -> None:
        with self._lock:
            for client in self._clients.values():
                client.close()
            self._clients.clear()
```

Note `replayed` counts successfully replayed steps, which equals the failing step's index when one fails.

- [ ] **Step 4: Run tests, format, commit**

Run: `uv run pytest tests/server/test_kernels.py -v` → 3 passed.

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/server tests/server
git commit -m "feat: kernel manager with dead-kernel respawn and restart-and-replay"
```

---

### Task 10: Session service and FastAPI app

**Files:**

- Create: `src/quarry/server/service.py`
- Create: `src/quarry/server/app.py`
- Test: `tests/server/test_app.py`

**Interfaces:**

- Consumes: everything above plus `QuerySpec`, `QueryResult`, `KernelClient.query`, `describe_loaders`, `load_loaders`, `scan_layout`, `builtin_root`, `default_transpiler`.
- Produces (in `quarry.server.service`):
  - `ProviderFactory = Callable[[QuarryConfig], Provider]`; `def provider_from_config(config: QuarryConfig) -> Provider` choosing `AnthropicProvider.from_config` or `OpenAIProvider.from_config`.
  - `class StepRequest(BaseModel)`: `prompt: str`; `class ManualStepRequest(BaseModel)`: `code: str`; `class CreateSessionRequest(BaseModel)`: `title: str = "Untitled"`
  - `class SessionStatus(BaseModel)`: `session_id: str`, `running_step: str | None`, `kernel: KernelStatus`, `last_error: str | None`
  - `class SessionService`: `__init__(self, *, config: QuarryConfig, store: SessionStore, kernels: KernelManager, provider_factory: ProviderFactory, library: ComponentLibrary, transpiler: Transpiler)`; `create(title) -> SessionMeta`; `list() -> list[SessionMeta]`; `get(session_id) -> Session`; `start_prompt(session_id, prompt) -> Step` (returns the running step; raises `SessionBusy` if one is in flight; runs `_execute_prompt` in a `threading.Thread`); `start_manual(session_id, code) -> Step` (same threading, executes the code directly, no provider); `status(session_id) -> SessionStatus`; `interrupt(session_id) -> None`; `query(session_id, spec) -> QueryResult`; `datasets(session_id) -> list[DatasetMeta]`; `restart(session_id) -> ReplayReport`; `shutdown() -> None`. `class SessionBusy(Exception)`.
  - System prompt is built once per service from config: loaders described via `load_loaders(config.root / "loaders.toml")`, layout from `scan_layout(config.data.parquet_root)` when set, enabled libraries from config.
- Produces (in `quarry.server.app`): `def create_app(*, config: QuarryConfig, token: str, provider_factory: ProviderFactory = provider_from_config, static_dir: Path | None = None) -> FastAPI`. Routes:
  - `GET /healthz` (no auth) → `{"ok": true}`
  - `POST /sessions` → `SessionMeta` (201); `GET /sessions` → list; `GET /sessions/{id}` → `Session` (404 if unknown)
  - `POST /sessions/{id}/steps` body `StepRequest` → `Step` (202), 409 when busy
  - `POST /sessions/{id}/steps/manual` body `ManualStepRequest` → `Step` (202), 409 when busy
  - `GET /sessions/{id}/status` → `SessionStatus`
  - `POST /sessions/{id}/interrupt` → `{"ok": true}`
  - `POST /sessions/{id}/query` body `QuerySpec` → `QueryResult`; 400 on `QueryError` or `RpcFailure`, 503 on `KernelDead`
  - `GET /sessions/{id}/datasets` → `list[DatasetMeta]`
  - `POST /sessions/{id}/restart` → `ReplayReport`
  - Static files mounted at `/` from `static_dir` when it exists (Stage 3 fills it); otherwise `GET /` returns a plain text hint.
  - Auth: a dependency that reads `Authorization: Bearer <token>` and compares with `secrets.compare_digest`; 401 otherwise.

- [ ] **Step 1: Write the failing tests**

`tests/server/test_app.py`:

```python
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, ToolCall
from quarry.config import QuarryConfig
from quarry.server.app import create_app

TOKEN = "t0k3n"


def py(call_id: str, code: str) -> AssistantTurn:
    return AssistantTurn(text="", tool_calls=[ToolCall(id=call_id, name="run_python", input={"code": code})], stop="tool_use")


def end(text: str = "done") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], stop="end")


def make_client(tmp_path: Path, turns: list[AssistantTurn]) -> TestClient:
    config = QuarryConfig(root=tmp_path)
    app = create_app(config=config, token=TOKEN, provider_factory=lambda _cfg: FakeProvider(turns))
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def wait_idle(client: TestClient, sid: str, timeout: float = 30.0) -> dict:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status = client.get(f"/sessions/{sid}/status").json()
        if status["running_step"] is None:
            return status
        time.sleep(0.05)
    raise AssertionError("step did not finish")


def test_auth_required(tmp_path: Path):
    client = make_client(tmp_path, [])
    assert client.get("/healthz").status_code == 200
    bare = TestClient(client.app)
    assert bare.get("/sessions").status_code == 401
    assert bare.get("/sessions", headers={"Authorization": "Bearer wrong"}).status_code == 401


def test_prompt_step_end_to_end(tmp_path: Path):
    with make_client(tmp_path, [py("c1", "df = pl.DataFrame({'a': [3, 1, 2]})"), end("loaded")]) as client:
        sid = client.post("/sessions", json={"title": "t"}).json()["id"]
        created = client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        assert created.status_code == 202
        assert created.json()["status"] == "running"
        status = wait_idle(client, sid)
        assert status["kernel"]["status"] == "idle" and status["last_error"] is None
        session = client.get(f"/sessions/{sid}").json()
        step = session["steps"][0]
        assert step["status"] == "ok" and step["note"] == "loaded" and step["writes"] == ["df"]
        assert step["kind"] == "prompt" and step["transcript"] is not None
        rows = client.post(f"/sessions/{sid}/query", json={"dataset": "df", "sort": [{"col": "a"}]}).json()["rows"]
        assert rows == [{"a": 1}, {"a": 2}, {"a": 3}]
        assert client.get(f"/sessions/{sid}/datasets").json()[0]["name"] == "df"


def test_second_step_while_running_is_409(tmp_path: Path):
    with make_client(tmp_path, [py("c1", "import time\ntime.sleep(1.5)\nx = 1"), end()]) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        assert client.post(f"/sessions/{sid}/steps", json={"prompt": "slow"}).status_code == 202
        assert client.post(f"/sessions/{sid}/steps", json={"prompt": "again"}).status_code == 409
        wait_idle(client, sid)
        assert client.get(f"/sessions/{sid}").json()["steps"][0]["status"] == "ok"


def test_manual_step_and_bad_query(tmp_path: Path):
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        assert client.post(f"/sessions/{sid}/steps/manual", json={"code": "df = pl.DataFrame({'a': [1]})"}).status_code == 202
        wait_idle(client, sid)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["kind"] == "manual" and step["status"] == "ok" and step["transcript"] is None
        assert client.post(f"/sessions/{sid}/query", json={"dataset": "df", "filters": [{"col": "zz", "op": "eq", "value": 1}]}).status_code == 400
        assert client.post(f"/sessions/{sid}/query", json={"dataset": "nope"}).status_code == 400


def test_kernel_death_then_restart_replays(tmp_path: Path):
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
        wait_idle(client, sid)
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "import os\nos._exit(2)\n"})
        status = wait_idle(client, sid)
        assert status["kernel"]["status"] == "dead"
        steps = client.get(f"/sessions/{sid}").json()["steps"]
        assert steps[1]["status"] == "error" and "kernel" in steps[1]["error"]["message"].lower()
        report = client.post(f"/sessions/{sid}/restart").json()
        assert report["failed_step"] is None
        assert report["replayed"] == 1  # only the ok step is replayed; the crashing step is skipped
        assert client.get(f"/sessions/{sid}/status").json()["kernel"]["status"] == "idle"


def test_sessions_survive_server_restart(tmp_path: Path):
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={"title": "keep"}).json()["id"]
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
        wait_idle(client, sid)
    with make_client(tmp_path, []) as again:
        session = again.get(f"/sessions/{sid}").json()
        assert session["meta"]["title"] == "keep" and len(session["steps"]) == 1
        assert again.get(f"/sessions/{sid}/status").json()["kernel"]["status"] == "starting"
        assert again.get("/sessions/missing").status_code == 404


def test_interrupt_running_step(tmp_path: Path):
    with make_client(tmp_path, [py("c1", "import time\nwhile True:\n    time.sleep(0.01)\n"), end()]) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "spin"})
        time.sleep(0.8)
        assert client.post(f"/sessions/{sid}/interrupt").json() == {"ok": True}
        wait_idle(client, sid)
        assert client.get(f"/sessions/{sid}").json()["steps"][0]["status"] == "interrupted"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/server/test_app.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Write service.py**

`src/quarry/server/service.py`:

```python
"""Session operations: one running step per session, executed on a background thread."""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from pydantic import BaseModel

from quarry.agent.anthropic_provider import AnthropicProvider
from quarry.agent.context import SystemContext, build_summary, build_system, enabled_libraries
from quarry.agent.loop import run_agent_step, step_lineage
from quarry.agent.openai_provider import OpenAIProvider
from quarry.agent.tools import ToolExecutor
from quarry.agent.transpile import Transpiler
from quarry.agent.types import Provider
from quarry.components.library import ComponentLibrary
from quarry.config import QuarryConfig
from quarry.data.loaders import describe_loaders, load_loaders
from quarry.data.parquet import scan_layout
from quarry.kernel.client import KernelDead, KernelClient
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import ExecError, ExecResult, QueryResult
from quarry.query.spec import QuerySpec
from quarry.server.kernels import KernelManager, ReplayReport
from quarry.server.models import KernelStatus, ProviderInfo, Session, SessionMeta, Step, StepKind, View, new_id, now_iso
from quarry.server.store import SessionStore

ProviderFactory = Callable[[QuarryConfig], Provider]


def provider_from_config(config: QuarryConfig) -> Provider:
    if config.provider.name == "openai":
        return OpenAIProvider.from_config(config)
    return AnthropicProvider.from_config(config)


class SessionBusy(Exception):
    pass


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
        self._running: dict[str, Step] = {}
        self._last_error: dict[str, str] = {}
        self._lock = threading.Lock()
        self._system = build_system(self._system_context())

    def create(self, title: str) -> SessionMeta:
        info = ProviderInfo(name=self._config.provider.name, model=self._config.provider.model)
        return self._store.create(title=title, provider=info)

    def list(self) -> list[SessionMeta]:
        return self._store.list()

    def get(self, session_id: str) -> Session:
        session = self._store.get(session_id)
        running = self._running.get(session_id)
        if running is not None:
            session.steps.append(running)
        return session

    def start_prompt(self, session_id: str, prompt: str) -> Step:
        step = self._begin(session_id, kind="prompt", prompt=prompt, code="")
        threading.Thread(target=self._run_prompt, args=(session_id, step, prompt), daemon=True).start()
        return step

    def start_manual(self, session_id: str, code: str) -> Step:
        step = self._begin(session_id, kind="manual", prompt=None, code=code)
        threading.Thread(target=self._run_manual, args=(session_id, step), daemon=True).start()
        return step

    def status(self, session_id: str) -> SessionStatus:
        self._store.get(session_id)
        running = self._running.get(session_id)
        return SessionStatus(
            session_id=session_id,
            running_step=running.id if running else None,
            kernel=self._kernels.status(session_id),
            last_error=self._last_error.get(session_id),
        )

    def interrupt(self, session_id: str) -> None:
        self._kernels.get(session_id).interrupt()

    def query(self, session_id: str, spec: QuerySpec) -> QueryResult:
        self._store.get(session_id)
        return self._kernels.get(session_id).query(spec)

    def datasets(self, session_id: str) -> list[DatasetMeta]:
        self._store.get(session_id)
        return self._kernels.get(session_id).list_datasets()

    def restart(self, session_id: str) -> ReplayReport:
        steps = [s for s in self._store.get(session_id).steps if s.status == "ok" and s.code]
        return self._kernels.restart(session_id, steps)

    def shutdown(self) -> None:
        self._kernels.close_all()

    def _begin(self, session_id: str, *, kind: StepKind, prompt: str | None, code: str) -> Step:
        with self._lock:
            if session_id in self._running:
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
            self._running[session_id] = step
            self._kernels.mark_running(session_id, True)
            return step

    def _run_prompt(self, session_id: str, step: Step, prompt: str) -> None:
        started = time.monotonic()
        try:
            kernel = self._kernels.get(session_id)
            tools = ToolExecutor(kernel=kernel, library=self._library, transpiler=self._transpiler)
            summary = build_summary(self._store.get(session_id).steps, _safe_datasets(kernel))
            outcome = run_agent_step(
                prompt=prompt, system=self._system, summary=summary, provider=self._provider_factory(self._config), tools=tools
            )
            lineage = step_lineage(outcome.exec_results)
            done = step.model_copy(
                update={
                    "status": outcome.status,
                    "note": outcome.note,
                    "code": outcome.code,
                    "error": ExecError(type="StepError", message=outcome.error_message, traceback="") if outcome.error_message else None,
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
            done = _kernel_death(step, exc, started)
        self._finish(session_id, done)

    def _run_manual(self, session_id: str, step: Step) -> None:
        started = time.monotonic()
        try:
            result = self._kernels.get(session_id).execute(step.code)
            done = _apply_exec(step, result, started)
        except KernelDead as exc:
            done = _kernel_death(step, exc, started)
        self._finish(session_id, done)

    def _finish(self, session_id: str, step: Step) -> None:
        self._store.append_step(session_id, step)
        with self._lock:
            self._running.pop(session_id, None)
            self._kernels.mark_running(session_id, False)
            if step.error is not None:
                self._last_error[session_id] = step.error.message
            else:
                self._last_error.pop(session_id, None)

    def _system_context(self) -> SystemContext:
        registry = load_loaders(self._config.root / "loaders.toml")
        root = self._config.data.parquet_root
        return SystemContext(
            loaders=describe_loaders(registry),
            layout=scan_layout(root) if root is not None else [],
            enabled_libraries=enabled_libraries(self._config),
        )


def _apply_exec(step: Step, result: ExecResult, started: float) -> Step:
    return step.model_copy(
        update={
            "status": result.status,
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


def _kernel_death(step: Step, exc: KernelDead, started: float) -> Step:
    return step.model_copy(
        update={
            "status": "error",
            "error": ExecError(type="KernelDead", message=f"kernel died: {exc}", traceback=""),
            "duration_ms": int((time.monotonic() - started) * 1000),
        }
    )


def _safe_datasets(kernel: KernelClient) -> list[DatasetMeta]:
    try:
        return kernel.list_datasets()
    except KernelDead:
        return []
```

Prompt-step lineage comes from `step_lineage` over the kernel's per-call `ExecResult`s, so a self-rebinding like `df = df.filter(...)` records both a read and a write of `df` (the dependency graph in Stage 4 needs that read edge), while a name written by call one and read by call two stays internal to the step.

- [ ] **Step 4: Write app.py**

`src/quarry/server/app.py`:

```python
"""FastAPI application: loopback, bearer token, sessions and steps."""

from __future__ import annotations

import secrets
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Response
from fastapi.responses import PlainTextResponse
from fastapi.staticfiles import StaticFiles

from quarry.agent.transpile import default_transpiler
from quarry.components.library import ComponentLibrary, builtin_root
from quarry.config import QuarryConfig
from quarry.kernel.client import KernelDead, RpcFailure
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import QueryResult
from quarry.query.spec import QueryError, QuerySpec
from quarry.server.kernels import KernelManager, ReplayReport
from quarry.server.models import Session, SessionMeta, Step
from quarry.server.service import (
    CreateSessionRequest,
    ManualStepRequest,
    ProviderFactory,
    SessionBusy,
    SessionService,
    SessionStatus,
    StepRequest,
    provider_from_config,
)
from quarry.server.store import SessionStore


def create_app(
    *,
    config: QuarryConfig,
    token: str,
    provider_factory: ProviderFactory = provider_from_config,
    static_dir: Path | None = None,
) -> FastAPI:
    static = static_dir or Path(__file__).parent.parent / "static"
    roots = [builtin_root(), config.root / "components"]
    if config.libraries.team_components is not None:
        roots.append(config.libraries.team_components)
    service = SessionService(
        config=config,
        store=SessionStore(config.root),
        kernels=KernelManager(config.root),
        provider_factory=provider_factory,
        library=ComponentLibrary(roots),
        transpiler=default_transpiler(static),
    )
    app = FastAPI(title="Quarry", docs_url=None, redoc_url=None)
    app.state.service = service

    def authed(authorization: Annotated[str | None, Header()] = None) -> None:
        expected = f"Bearer {token}"
        if authorization is None or not secrets.compare_digest(authorization, expected):
            raise HTTPException(status_code=401, detail="missing or invalid token")

    Auth = Annotated[None, Depends(authed)]

    def session_or_404(session_id: str) -> Session:
        try:
            return service.get(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such session") from exc

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @app.post("/sessions", status_code=201)
    def create_session(body: CreateSessionRequest, _: Auth) -> SessionMeta:
        return service.create(body.title)

    @app.get("/sessions")
    def list_sessions(_: Auth) -> list[SessionMeta]:
        return service.list()

    @app.get("/sessions/{session_id}")
    def get_session(session_id: str, _: Auth) -> Session:
        return session_or_404(session_id)

    @app.post("/sessions/{session_id}/steps", status_code=202)
    def post_step(session_id: str, body: StepRequest, _: Auth) -> Step:
        session_or_404(session_id)
        try:
            return service.start_prompt(session_id, body.prompt)
        except SessionBusy as exc:
            raise HTTPException(status_code=409, detail="a step is already running") from exc

    @app.post("/sessions/{session_id}/steps/manual", status_code=202)
    def post_manual(session_id: str, body: ManualStepRequest, _: Auth) -> Step:
        session_or_404(session_id)
        try:
            return service.start_manual(session_id, body.code)
        except SessionBusy as exc:
            raise HTTPException(status_code=409, detail="a step is already running") from exc

    @app.get("/sessions/{session_id}/status")
    def get_status(session_id: str, _: Auth) -> SessionStatus:
        session_or_404(session_id)
        return service.status(session_id)

    @app.post("/sessions/{session_id}/interrupt")
    def interrupt(session_id: str, _: Auth) -> dict[str, bool]:
        session_or_404(session_id)
        service.interrupt(session_id)
        return {"ok": True}

    @app.post("/sessions/{session_id}/query")
    def query(session_id: str, spec: QuerySpec, _: Auth) -> QueryResult:
        session_or_404(session_id)
        try:
            return service.query(session_id, spec)
        except (QueryError, RpcFailure) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except KernelDead as exc:
            raise HTTPException(status_code=503, detail="kernel is not running") from exc

    @app.get("/sessions/{session_id}/datasets")
    def datasets(session_id: str, _: Auth) -> list[DatasetMeta]:
        session_or_404(session_id)
        try:
            return service.datasets(session_id)
        except KernelDead as exc:
            raise HTTPException(status_code=503, detail="kernel is not running") from exc

    @app.post("/sessions/{session_id}/restart")
    def restart(session_id: str, _: Auth) -> ReplayReport:
        session_or_404(session_id)
        return service.restart(session_id)

    @app.on_event("shutdown")
    def _shutdown() -> None:
        service.shutdown()

    if (static / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(static), html=True), name="static")
    else:

        @app.get("/", response_class=PlainTextResponse)
        def root() -> str:
            return "Quarry server is running. The web UI is not built yet; use the API with your bearer token."

    return app
```

If the installed FastAPI rejects `@app.on_event` (removed in newer versions), use a lifespan context: `@asynccontextmanager async def lifespan(app): yield; service.shutdown()` and pass `lifespan=lifespan` to `FastAPI(...)`. Response models are inferred from return annotations; `DatasetMeta` and `QueryResult` serialize with `by_alias` because FastAPI uses `model_dump(by_alias=True)` for response models; if `schema_` appears in the JSON instead of `schema`, set `response_model_by_alias=True` on those two routes.

- [ ] **Step 5: Run tests, format, commit**

Run: `uv run pytest tests/server/test_app.py -v` → 7 passed. The `TestClient` is used as a context manager so FastAPI's shutdown hook closes kernels; the two tests that construct `make_client` without `with` only exercise auth and do not spawn kernels.

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/server tests/server
git commit -m "feat: session service and FastAPI app with bearer auth, steps, query, restart"
```

---

### Task 11: CLI `quarry serve`

**Files:**

- Create: `src/quarry/cli.py`
- Modify: `pyproject.toml` (script entry)
- Test: `tests/test_cli.py`

**Interfaces:**

- Produces: `def main(argv: list[str] | None = None) -> int`; `quarry serve [--port N] [--root PATH] [--host-hint NAME]`; prints to stdout the token banner from `def banner(*, port: int, token: str, host_hint: str) -> str`:

```
Quarry is running on 127.0.0.1:<port>

1. On your desktop, open a tunnel:
   ssh -L <port>:127.0.0.1:<port> <host_hint>
2. Then open:
   http://127.0.0.1:<port>/#token=<token>

Token (keep private): <token>
```

`--host-hint` defaults to `socket.gethostname()`. `def free_port() -> int` binds port 0 on loopback and returns the assigned port. `def new_token() -> str` = `secrets.token_urlsafe(32)`. `serve` calls `uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")`.

- [ ] **Step 1: Write the failing tests**

`tests/test_cli.py`:

```python
from quarry.cli import banner, free_port, main, new_token


def test_banner_contains_tunnel_and_url():
    text = banner(port=4321, token="abc", host_hint="devbox")
    assert "ssh -L 4321:127.0.0.1:4321 devbox" in text
    assert "http://127.0.0.1:4321/#token=abc" in text


def test_free_port_is_usable():
    port = free_port()
    assert 1024 < port < 65536


def test_token_is_long_and_url_safe():
    token = new_token()
    assert len(token) >= 40 and all(c.isalnum() or c in "-_" for c in token)


def test_main_without_command_prints_usage(capsys):
    assert main([]) == 2
    assert "serve" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Write the implementation**

`src/quarry/cli.py`:

```python
"""Command line entry: `quarry serve`."""

from __future__ import annotations

import argparse
import secrets
import socket
import sys
from pathlib import Path

import uvicorn

from quarry.config import load_config
from quarry.server.app import create_app


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="quarry")
    sub = parser.add_subparsers(dest="command")
    serve = sub.add_parser("serve", help="start the Quarry server on loopback")
    serve.add_argument("--port", type=int, default=None)
    serve.add_argument("--root", type=Path, default=Path("~/.quarry"))
    serve.add_argument("--host-hint", default=socket.gethostname())
    args = parser.parse_args(argv)
    if args.command != "serve":
        parser.print_usage(sys.stderr)
        return 2
    return run_serve(port=args.port or free_port(), root=args.root.expanduser(), host_hint=args.host_hint)


def run_serve(*, port: int, root: Path, host_hint: str) -> int:
    root.mkdir(parents=True, exist_ok=True)
    token = new_token()
    app = create_app(config=load_config(root), token=token)
    print(banner(port=port, token=token, host_hint=host_hint), flush=True)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")
    return 0


def banner(*, port: int, token: str, host_hint: str) -> str:
    return (
        f"Quarry is running on 127.0.0.1:{port}\n\n"
        "1. On your desktop, open a tunnel:\n"
        f"   ssh -L {port}:127.0.0.1:{port} {host_hint}\n"
        "2. Then open:\n"
        f"   http://127.0.0.1:{port}/#token={token}\n\n"
        f"Token (keep private): {token}\n"
    )


def free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        port: int = sock.getsockname()[1]
    return port


def new_token() -> str:
    return secrets.token_urlsafe(32)


if __name__ == "__main__":
    raise SystemExit(main())
```

Add to `pyproject.toml`:

```toml
[project.scripts]
quarry = "quarry.cli:main"
```

- [ ] **Step 4: Run tests, build, smoke the CLI, commit**

Run: `uv sync && uv run pytest tests/test_cli.py -v` → 4 passed.
Run: `uv build` → wheel builds; confirm `guide.md` is inside with `unzip -l dist/*.whl | grep guide.md`.
Run: `uv run quarry serve --root /tmp/quarry-smoke --port 8765 &` then `curl -s http://127.0.0.1:8765/healthz` → `{"ok":true}`; kill the server.

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/cli.py pyproject.toml uv.lock tests/test_cli.py
git commit -m "feat: quarry serve command with token banner and loopback bind"
```

---

### Task 12: Live provider smoke tests and curl walkthrough

**Files:**

- Test: `tests/agent/test_live_providers.py`
- Modify: `README.md`

**Interfaces:**

- Produces: two tests skipped unless `QUARRY_ANTHROPIC_API_KEY` / `QUARRY_OPENAI_API_KEY` are set, each asking the real model for one `run_python` call and asserting a dataset appears. A README section showing the curl flow.

- [ ] **Step 1: Write the gated tests**

`tests/agent/test_live_providers.py`:

```python
import os
from pathlib import Path

import pytest

from quarry.agent.anthropic_provider import AnthropicProvider
from quarry.agent.loop import run_agent_step, step_lineage
from quarry.agent.openai_provider import OpenAIProvider
from quarry.agent.tools import ToolExecutor
from quarry.agent.transpile import NoopTranspiler
from quarry.components.library import ComponentLibrary
from quarry.config import QuarryConfig
from quarry.kernel.client import KernelClient

PROMPT = "Create a polars DataFrame named `demo` with columns ticker (AAPL, MSFT) and px (1.0, 2.0). Then stop."


def _run(provider, tmp_path: Path) -> None:
    kernel = KernelClient.spawn(tmp_path)
    try:
        tools = ToolExecutor(kernel=kernel, library=ComponentLibrary([]), transpiler=NoopTranspiler())
        out = run_agent_step(prompt=PROMPT, system="You run Python via run_python. polars is pl.", summary="", provider=provider, tools=tools)
        assert out.status == "ok", out.error_message
        assert any(m.name == "demo" for m in kernel.list_datasets())
    finally:
        kernel.close()


@pytest.mark.skipif(not os.environ.get("QUARRY_ANTHROPIC_API_KEY"), reason="no Anthropic key")
def test_anthropic_live(tmp_path: Path):
    _run(AnthropicProvider.from_config(QuarryConfig(root=tmp_path)), tmp_path)


@pytest.mark.skipif(not os.environ.get("QUARRY_OPENAI_API_KEY"), reason="no OpenAI key")
def test_openai_live(tmp_path: Path):
    cfg = QuarryConfig.model_validate({"root": tmp_path, "provider": {"name": "openai", "model": "gpt-5"}})
    _run(OpenAIProvider.from_config(cfg), tmp_path)
```

- [ ] **Step 2: Run the suite with and without a key**

Run: `uv run pytest -q` → the two live tests report `s` (skipped), everything else passes.
If a key is available: `QUARRY_ANTHROPIC_API_KEY=... uv run pytest tests/agent/test_live_providers.py -v` → passes. Report the result either way; do not claim the live test passed if it was skipped.

- [ ] **Step 3: Document the curl flow**

Append to `README.md`:

````markdown
## Driving the server from curl (Stage 2)

```bash
export QUARRY_ANTHROPIC_API_KEY=...   # or QUARRY_OPENAI_API_KEY with provider.name = "openai" in config.toml
quarry serve --root ~/.quarry          # prints the port and token
T="Bearer <token>"; U=http://127.0.0.1:<port>
SID=$(curl -s -X POST $U/sessions -H "Authorization: $T" -H 'Content-Type: application/json' -d '{"title":"demo"}' | jq -r .id)
curl -s -X POST $U/sessions/$SID/steps -H "Authorization: $T" -H 'Content-Type: application/json' -d '{"prompt":"load the parquet cache prices for 2024 and show the first rows"}'
curl -s $U/sessions/$SID/status -H "Authorization: $T"          # poll until running_step is null
curl -s $U/sessions/$SID -H "Authorization: $T" | jq '.steps[-1] | {status, note, writes}'
curl -s -X POST $U/sessions/$SID/query -H "Authorization: $T" -H 'Content-Type: application/json' -d '{"dataset":"prices","limit":5}'
```

Server-side refusal fallbacks are enabled by default on Anthropic requests.
````

- [ ] **Step 4: Full verification and commit**

```bash
uv run pytest -q
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add tests/agent/test_live_providers.py README.md
git commit -m "test: gated live provider smoke tests; document curl flow"
```

---

## Self-review notes

- Spec coverage: section 4 request flow (Task 10), section 5 Session/Step/View (Task 6), section 6 restart-and-replay (Tasks 9, 10), section 8 provider interface, loop, five tools, context, library guide (Tasks 2 to 8), section 11 sessions layout (Task 6), section 12 loopback plus bearer token (Tasks 10, 11), section 13 provider errors, kernel crash, repair-once, transpile error (Tasks 3, 8, 9, 10), section 14 fake provider and live smoke (Tasks 2, 12). The browser-side mount error and "fix this" repair step belong to Stage 3.
- `search_components` ships working against an empty builtin directory; Stage 3 adds manifests and the `transpile-check.mjs` bundle.
- Prompt-step lineage is the fold of per-call `ExecResult`s (`step_lineage`, Task 8); manual steps take lineage straight from one `ExecResult`.
- `initial_state` is a JSON string in the tool schemas because strict mode on both providers rejects open nested objects.
- Anthropic requests enable server-side refusal fallbacks (`fallbacks="default"`); the README says so.
- Model default moved to `claude-opus-5-5` in both the config and the spec (Task 1).
