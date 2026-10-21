import json
from types import SimpleNamespace

import httpx2 as httpx
import openai
import pytest

from quarry.agent.openai_provider import (
    CreateFn,
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


def test_complete_passes_required_parameters() -> None:
    captured: dict[str, object] = {}

    def create(**kwargs: object) -> object:
        captured.update(kwargs)
        message = SimpleNamespace(content="done", tool_calls=None)
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason="stop", message=message)])

    messages = [Message(role="user", text="q")]
    turn = OpenAIProvider(model="gpt", create=create).complete(
        system="sys", messages=messages, tools=[]
    )
    assert turn.stop == "end" and turn.text == "done"
    assert captured == {
        "model": "gpt",
        "messages": to_openai_messages("sys", messages),
        "max_completion_tokens": 16000,
    }
    captured.clear()
    tool = ToolDef(name="t", description="d", input_schema={"type": "object", "properties": {}})
    OpenAIProvider(model="gpt", create=create).complete(system="s", messages=[], tools=[tool])
    assert captured == {
        "model": "gpt",
        "messages": to_openai_messages("s", []),
        "max_completion_tokens": 16000,
        "tools": to_openai_tools([tool]),
    }


def test_complete_maps_errors() -> None:
    def rate_limited(**kwargs: object) -> object:
        raise openai.RateLimitError("slow", response=_response(429), body=None)

    with pytest.raises(ProviderError) as info:
        OpenAIProvider(model="gpt", create=rate_limited).complete(system="s", messages=[], tools=[])
    assert info.value.retryable is True

    def malformed(**kwargs: object) -> object:
        raise openai.APIResponseValidationError(response=_response(200), body=None)

    with pytest.raises(ProviderError) as info2:
        OpenAIProvider(model="gpt", create=malformed).complete(system="s", messages=[], tools=[])
    assert info2.value.retryable is False


def _called(call_id: str | None, name: str | None, arguments: str) -> SimpleNamespace:
    call = SimpleNamespace(id=call_id, function=SimpleNamespace(name=name, arguments=arguments))
    message = SimpleNamespace(content=None, tool_calls=[call])
    return SimpleNamespace(choices=[SimpleNamespace(finish_reason="tool_calls", message=message)])


@pytest.mark.parametrize(
    "create",
    [
        lambda **kwargs: "<html>oops</html>",
        lambda **kwargs: SimpleNamespace(choices=None),
        lambda **kwargs: SimpleNamespace(choices=[]),
        lambda **kwargs: SimpleNamespace(choices={}),
        lambda **kwargs: _called(None, "run_python", "{}"),
        lambda **kwargs: _called("c1", None, "{}"),
        lambda **kwargs: _called("c1", "run_python", "[" * 100000),
        lambda **kwargs: SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason="stop", message=SimpleNamespace(content=["x"], tool_calls=None)
                )
            ]
        ),
        lambda **kwargs: json.loads("<html>oops</html>"),
        lambda **kwargs: json.loads("[" * 100000),
        lambda **kwargs: json.loads(b"\xff"),
    ],
    ids=[
        "html",
        "missing fields",
        "no choices",
        "choices object",
        "no id",
        "no name",
        "arguments too deep",
        "content list",
        "not json",
        "too deep",
        "not utf-8",
    ],
)
def test_complete_maps_malformed_responses(create: CreateFn) -> None:
    with pytest.raises(ProviderError) as info:
        OpenAIProvider(model="gpt", create=create).complete(system="s", messages=[], tools=[])
    assert info.value.retryable is False


def test_complete_lets_client_errors_through() -> None:
    def streaming_required(**kwargs: object) -> object:
        raise ValueError("Streaming is required for operations that may take longer than 10 min")

    with pytest.raises(ValueError, match="Streaming is required"):
        OpenAIProvider(model="gpt", create=streaming_required).complete(
            system="s", messages=[], tools=[]
        )

    def renamed_keyword(**kwargs: object) -> object:
        raise TypeError("create() got an unexpected keyword argument 'max_completion_tokens'")

    with pytest.raises(TypeError, match="unexpected keyword argument"):
        OpenAIProvider(model="gpt", create=renamed_keyword).complete(
            system="s", messages=[], tools=[]
        )
