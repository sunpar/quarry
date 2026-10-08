import pytest

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, Message, ToolCall, ToolDef, ToolResult


def test_message_defaults() -> None:
    m = Message(role="user", text="hi")
    assert m.tool_calls == [] and m.tool_results == []


def test_assistant_turn_as_message() -> None:
    turn = AssistantTurn(
        text="running",
        tool_calls=[ToolCall(id="c1", name="run_python", input={"code": "x = 1"})],
        stop="tool_use",
    )
    msg = turn.as_message()
    assert msg.role == "assistant"
    assert msg.text == "running"
    assert msg.tool_calls[0].name == "run_python"


def test_round_trip_json() -> None:
    msg = Message(
        role="user",
        tool_results=[ToolResult(call_id="c1", content="{}", is_error=True)],
    )
    assert Message.model_validate_json(msg.model_dump_json()) == msg


def test_fake_provider_replays_and_records() -> None:
    turns = [AssistantTurn(text="a", tool_calls=[], stop="end")]
    fake = FakeProvider(turns)
    tools = [ToolDef(name="t", description="d", input_schema={"type": "object", "properties": {}})]
    out = fake.complete(system="sys", messages=[Message(role="user", text="q")], tools=tools)
    assert out.text == "a"
    assert fake.calls[0][0] == "sys"
    assert fake.calls[0][1][0].text == "q"
    with pytest.raises(AssertionError, match="exhausted"):
        fake.complete(system="sys", messages=[], tools=tools)
