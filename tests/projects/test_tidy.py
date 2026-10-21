import threading

import pytest

from quarry.agent.fake import FakeProvider
from quarry.agent.runtime import ApiRuntime
from quarry.agent.types import AssistantTurn, Message, Provider, ProviderError, ToolDef
from quarry.projects.tidy import TIDY_SYSTEM, strip_fences
from quarry.projects.tidy import tidy_recipe as run_tidy
from tests.projects.test_export import UNPARSABLE
from tests.server.test_app import end


def tidy_recipe(provider: Provider, raw: str, dataset: str) -> str | None:
    return run_tidy(ApiRuntime(provider), raw, dataset, cancel=threading.Event())


def test_strip_fences() -> None:
    assert strip_fences("```python\nx = 1\n```") == "x = 1\n"
    assert strip_fences("x = 1") == "x = 1\n"


def test_tidy_sends_raw_and_returns_code() -> None:
    provider = FakeProvider([end("```python\nimport polars as pl\nprices = pl.DataFrame()\n```")])
    out = tidy_recipe(provider, "x = 1\nprices = pl.DataFrame()\n", "prices")
    assert out == "import polars as pl\nprices = pl.DataFrame()\n"
    system, messages, tools = provider.calls[0]
    assert system == TIDY_SYSTEM
    assert tools == []
    assert messages[-1].role == "user" and "prices" in messages[-1].text


def test_tidy_returns_none_on_failure_or_garbage() -> None:
    class Failing:
        def complete(
            self, *, system: str, messages: list[Message], tools: list[ToolDef]
        ) -> AssistantTurn:
            raise ProviderError("down", retryable=False)

    assert tidy_recipe(Failing(), "x = 1", "x") is None
    assert tidy_recipe(FakeProvider([end("")]), "x = 1", "x") is None
    assert tidy_recipe(FakeProvider([end("def (")]), "x = 1", "x") is None
    assert tidy_recipe(FakeProvider([end("y = 2")]), "x = 1", "x") is None


@pytest.mark.parametrize("reply", UNPARSABLE)
def test_tidy_rejects_a_reply_too_deep_to_parse(reply: str) -> None:
    assert tidy_recipe(FakeProvider([end(reply)]), "x = 1", "x") is None


def test_tidy_rejects_a_name_bound_only_inside_a_function() -> None:
    local = end("def f():\n    prices = 1\n")
    assert tidy_recipe(FakeProvider([local]), "prices = 1", "prices") is None


def test_tidy_rejects_a_reply_that_did_not_end() -> None:
    cut = AssistantTurn(text="prices = pl.DataFrame()", tool_calls=[], stop="max_tokens")
    assert tidy_recipe(FakeProvider([cut]), "prices = pl.DataFrame()", "prices") is None
