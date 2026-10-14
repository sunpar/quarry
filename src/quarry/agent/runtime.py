"""Runtime operations shared by API providers and native subscription adapters."""

from __future__ import annotations

import threading
from typing import Protocol

from quarry.agent.loop import StepOutcome, run_agent_step
from quarry.agent.tools import ToolExecutor
from quarry.agent.types import AssistantTurn, Message, Provider, ProviderError


class AgentRuntime(Protocol):
    def run_step(
        self,
        *,
        prompt: str,
        system: str,
        summary: str,
        tools: ToolExecutor,
        cancel: threading.Event,
    ) -> StepOutcome: ...

    def complete_text(
        self, *, system: str, prompt: str, cancel: threading.Event
    ) -> AssistantTurn: ...


class ApiRuntime:
    def __init__(self, provider: Provider) -> None:
        self._provider = provider

    def run_step(
        self,
        *,
        prompt: str,
        system: str,
        summary: str,
        tools: ToolExecutor,
        cancel: threading.Event,
    ) -> StepOutcome:
        return run_agent_step(
            prompt=prompt,
            system=system,
            summary=summary,
            provider=self._provider,
            tools=tools,
            cancel=cancel,
        )

    def complete_text(self, *, system: str, prompt: str, cancel: threading.Event) -> AssistantTurn:
        if cancel.is_set():
            raise ProviderError("interrupted by researcher", retryable=False)
        turn = self._provider.complete(
            system=system, messages=[Message(role="user", text=prompt)], tools=[]
        )
        if cancel.is_set():
            raise ProviderError("interrupted by researcher", retryable=False)
        return turn
