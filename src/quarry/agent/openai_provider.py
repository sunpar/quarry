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
FINISH_MAP: Final[dict[str, StopReason]] = {
    "stop": "end",
    "tool_calls": "tool_use",
    "length": "max_tokens",
}


class OpenAIProvider:
    def __init__(self, *, model: str, create: CreateFn) -> None:
        self._model = model
        self._create = create

    @classmethod
    def from_config(cls, config: QuarryConfig) -> OpenAIProvider:
        client = openai.OpenAI(api_key=api_key(config), max_retries=2)
        return cls(model=config.provider.model, create=client.chat.completions.create)

    def complete(
        self, *, system: str, messages: list[Message], tools: list[ToolDef]
    ) -> AssistantTurn:
        kwargs: dict[str, object] = {
            "model": self._model,
            "messages": to_openai_messages(system, messages),
            "max_completion_tokens": MAX_TOKENS,
        }
        if tools:
            kwargs["tools"] = to_openai_tools(tools)
        try:
            response = self._create(**kwargs)
        except (
            openai.RateLimitError,
            openai.InternalServerError,
            openai.APIConnectionError,
        ) as exc:
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
                    {
                        "id": c.id,
                        "type": "function",
                        "function": {"name": c.name, "arguments": json.dumps(c.input)},
                    }
                    for c in m.tool_calls
                ]
            out.append(entry)
        elif m.tool_results:
            out += [
                {"role": "tool", "tool_call_id": r.call_id, "content": r.content}
                for r in m.tool_results
            ]
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
        ToolCall(
            id=str(c.id), name=str(c.function.name), input=json.loads(c.function.arguments or "{}")
        )
        for c in (message.tool_calls or [])
    ]
    stop = FINISH_MAP.get(str(choice.finish_reason), "end")
    return AssistantTurn(text=str(message.content or ""), tool_calls=calls, stop=stop)
