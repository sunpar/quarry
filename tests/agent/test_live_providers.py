import os
import threading
from pathlib import Path

import pytest

from quarry.agent.anthropic_provider import AnthropicProvider
from quarry.agent.loop import run_agent_step
from quarry.agent.openai_provider import OpenAIProvider
from quarry.agent.tools import ToolExecutor
from quarry.agent.transpile import NoopTranspiler
from quarry.agent.types import Provider
from quarry.components.library import ComponentLibrary
from quarry.config import QuarryConfig
from quarry.kernel.client import KernelClient

PROMPT = (
    "Create a polars DataFrame named `demo` with columns ticker (AAPL, MSFT) "
    "and px (1.0, 2.0). Then stop."
)


def _run(provider: Provider, tmp_path: Path) -> None:
    kernel = KernelClient.spawn(tmp_path)
    try:
        tools = ToolExecutor(
            kernel=kernel, library=ComponentLibrary([]), transpiler=NoopTranspiler()
        )
        out = run_agent_step(
            prompt=PROMPT,
            system="You run Python via run_python. polars is pl.",
            summary="",
            provider=provider,
            tools=tools,
            cancel=threading.Event(),
        )
        assert out.status == "ok", out.error_message
        assert any(m.name == "demo" for m in kernel.list_datasets())
    finally:
        kernel.close()


@pytest.mark.skipif(not os.environ.get("QUARRY_ANTHROPIC_API_KEY"), reason="no Anthropic key")
def test_anthropic_live(tmp_path: Path) -> None:
    _run(AnthropicProvider.from_config(QuarryConfig(root=tmp_path)), tmp_path)


@pytest.mark.skipif(not os.environ.get("QUARRY_OPENAI_API_KEY"), reason="no OpenAI key")
def test_openai_live(tmp_path: Path) -> None:
    cfg = QuarryConfig.model_validate(
        {"root": tmp_path, "provider": {"name": "openai", "model": "gpt-5"}}
    )
    _run(OpenAIProvider.from_config(cfg), tmp_path)
