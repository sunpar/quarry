import json
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from quarry.agent.openai_provider import (
    OpenAIProvider,
    from_openai_response,
    to_openai_messages,
    to_openai_tools,
)
from quarry.agent.types import Message, ProviderError, ToolCall, ToolDef, ToolResult


def _response(status: int) -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("POST", "https://x"))


def test_to_openai_messages_shapes() -> None:
    msgs = [
        Message(role="user", text="load it"),
        Message(
            role="assistant",
            text="ok",
            tool_calls=[ToolCall(id="c1", name="run_python", input={"code": "x=1"})],
        ),
        Message(role="user", tool_results=[ToolResult(call_id="c1", content="{}", is_error=True)]),
    ]
    call = {"name": "run_python", "arguments": json.dumps({"code": "x=1"})}
    assert to_openai_messages("sys", msgs) == [
        {"role": "system", "content": "sys"},
        {"role": "user", "content": "load it"},
        {
            "role": "assistant",
            "content": "ok",
            "tool_calls": [{"id": "c1", "type": "function", "function": call}],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "{}"},
    ]


def test_to_openai_tools() -> None:
    tools = [
        ToolDef(
            name="t",
            description="d",
            input_schema={"type": "object", "properties": {}, "required": []},
        )
    ]
    schema = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
    assert to_openai_tools(tools) == [
        {
            "type": "function",
            "function": {"name": "t", "description": "d", "parameters": schema, "strict": True},
        }
    ]


def test_from_openai_response_tool_calls() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="c1",
                            function=SimpleNamespace(
                                name="run_python", arguments='{"code": "x=1"}'
                            ),
                        )
                    ],
                ),
            )
        ]
    )
    turn = from_openai_response(response)
    assert turn.stop == "tool_use"
    assert turn.tool_calls == [ToolCall(id="c1", name="run_python", input={"code": "x=1"})]


def test_from_openai_response_length_and_refusal() -> None:
    length = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(content="partial", tool_calls=None),
            )
        ]
    )
    assert from_openai_response(length).stop == "max_tokens"
    refusal = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="stop",
                message=SimpleNamespace(content=None, tool_calls=None, refusal="no"),
            )
        ]
    )
    turn = from_openai_response(refusal)
    assert turn.stop == "refusal" and turn.refusal_reason == "no"
    filtered = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="content_filter",
                message=SimpleNamespace(content=None, tool_calls=None),
            )
        ]
    )
    blocked = from_openai_response(filtered)
    assert blocked.stop == "refusal"
    assert blocked.refusal_reason == "response blocked by content filter"


def test_from_openai_response_truncated_tool_call_is_max_tokens() -> None:
    response = SimpleNamespace(
        choices=[
            SimpleNamespace(
                finish_reason="length",
                message=SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="c1",
                            function=SimpleNamespace(name="run_python", arguments='{"code": "x='),
                        )
                    ],
                ),
            )
        ]
    )
    turn = from_openai_response(response)
    assert turn.stop == "max_tokens"
    assert turn.tool_calls == []


def test_complete_maps_errors() -> None:
    def rate_limited(**kwargs: object) -> object:
        raise openai.RateLimitError("slow", response=_response(429), body=None)

    with pytest.raises(ProviderError) as info:
        OpenAIProvider(model="gpt", create=rate_limited).complete(system="s", messages=[], tools=[])
    assert info.value.retryable is True
