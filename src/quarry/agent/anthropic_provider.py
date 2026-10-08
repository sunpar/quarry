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
    "model_context_window_exceeded": "max_tokens",
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

    def complete(
        self, *, system: str, messages: list[Message], tools: list[ToolDef]
    ) -> AssistantTurn:
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
        except (
            anthropic.RateLimitError,
            anthropic.InternalServerError,
            anthropic.APIConnectionError,
        ) as exc:
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
            blocks += [
                {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input}
                for c in m.tool_calls
            ]
            out.append({"role": "assistant", "content": blocks})
        elif m.tool_results:
            out.append(
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": r.call_id,
                            "content": r.content,
                            "is_error": r.is_error,
                        }
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
        refusal = str(
            getattr(details, "explanation", None) or "request declined by safety classifier"
        )
    return AssistantTurn(
        text="".join(text_parts), tool_calls=calls, stop=stop, refusal_reason=refusal
    )
