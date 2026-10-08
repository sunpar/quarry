from types import SimpleNamespace

import anthropic
import httpx2 as httpx
import pytest

from quarry.agent.anthropic_provider import (
    AnthropicProvider,
    from_api_response,
    to_api_messages,
    to_api_tools,
)
from quarry.agent.types import Message, ProviderError, ToolCall, ToolDef, ToolResult


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://x"))


def test_to_api_messages_shapes() -> None:
    msgs = [
        Message(role="user", text="load it"),
        Message(
            role="assistant",
            text="ok",
            tool_calls=[ToolCall(id="c1", name="run_python", input={"code": "x=1"})],
        ),
        Message(role="user", tool_results=[ToolResult(call_id="c1", content="{}", is_error=True)]),
    ]
    api = to_api_messages(msgs)
    assert api[0] == {"role": "user", "content": "load it"}
    assert api[1]["role"] == "assistant"
    assert api[1]["content"][0] == {"type": "text", "text": "ok"}
    assert api[1]["content"][1] == {
        "type": "tool_use",
        "id": "c1",
        "name": "run_python",
        "input": {"code": "x=1"},
    }
    assert api[2]["content"][0] == {
        "type": "tool_result",
        "tool_use_id": "c1",
        "content": "{}",
        "is_error": True,
    }


def test_to_api_tools_are_strict() -> None:
    tools = [
        ToolDef(
            name="t",
            description="d",
            input_schema={
                "type": "object",
                "properties": {"a": {"type": "string"}},
                "required": ["a"],
            },
        )
    ]
    api = to_api_tools(tools)
    assert api[0]["strict"] is True
    assert api[0]["input_schema"]["additionalProperties"] is False


def test_from_api_response_tool_use() -> None:
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


def test_from_api_response_refusal() -> None:
    response = SimpleNamespace(
        stop_reason="refusal",
        stop_details=SimpleNamespace(type="refusal", category="cyber", explanation="declined"),
        content=[],
    )
    turn = from_api_response(response)
    assert turn.stop == "refusal"
    assert turn.refusal_reason == "declined"


def test_complete_passes_required_parameters() -> None:
    captured: dict[str, object] = {}

    def create(**kwargs: object) -> object:
        captured.update(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn",
            stop_details=None,
            content=[SimpleNamespace(type="text", text="done")],
        )

    provider = AnthropicProvider(model="claude-opus-5-5", create=create)
    turn = provider.complete(system="sys", messages=[Message(role="user", text="q")], tools=[])
    assert turn.stop == "end" and turn.text == "done"
    assert captured["model"] == "claude-opus-5-5"
    assert captured["max_tokens"] == 16000
    assert captured["output_config"] == {"effort": "high"}
    assert captured["betas"] == ["server-side-fallback-2026-07-01"]
    assert captured["fallbacks"] == "default"
    assert captured["system"] == [
        {"type": "text", "text": "sys", "cache_control": {"type": "ephemeral"}}
    ]
    assert "thinking" not in captured
    assert "tool_choice" not in captured


def test_complete_maps_sdk_errors() -> None:
    def rate_limited(**kwargs: object) -> object:
        raise anthropic.RateLimitError("slow down", response=_response(429), body=None)

    with pytest.raises(ProviderError) as info:
        AnthropicProvider(model="m", create=rate_limited).complete(
            system="s", messages=[], tools=[]
        )
    assert info.value.retryable is True

    def bad_request(**kwargs: object) -> object:
        raise anthropic.BadRequestError("nope", response=_response(400), body=None)

    with pytest.raises(ProviderError) as info2:
        AnthropicProvider(model="m", create=bad_request).complete(system="s", messages=[], tools=[])
    assert info2.value.retryable is False
