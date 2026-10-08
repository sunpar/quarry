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
    def complete(
        self, *, system: str, messages: list[Message], tools: list[ToolDef]
    ) -> AssistantTurn: ...
