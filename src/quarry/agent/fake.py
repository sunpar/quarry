"""Scripted provider for tests."""

from __future__ import annotations

from quarry.agent.types import AssistantTurn, Message, ToolDef


class FakeProvider:
    def __init__(self, turns: list[AssistantTurn]) -> None:
        self._turns = list(turns)
        self.calls: list[tuple[str, list[Message], list[ToolDef]]] = []

    def complete(
        self, *, system: str, messages: list[Message], tools: list[ToolDef]
    ) -> AssistantTurn:
        self.calls.append((system, list(messages), list(tools)))
        if not self._turns:
            raise AssertionError("FakeProvider exhausted")
        return self._turns.pop(0)
