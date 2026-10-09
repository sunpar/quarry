from pathlib import Path

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, ToolCall
from tests.server.test_app import end, make_client, py, wait_idle

PRICES = "prices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})"
TIDY = "import polars as pl\n" + PRICES + "\n"


def render(call_id: str) -> AssistantTurn:
    call = ToolCall(
        id=call_id,
        name="render_view",
        input={"component_id": "data-table", "datasets": ["prices"], "initial_state": "{}"},
    )
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def test_project_crud_and_save_flow(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", PRICES), render("c2"), end(), end(TIDY)])
    client = make_client(tmp_path, [], provider_factory=lambda _cfg: provider)
    created = client.post("/projects", json={"name": "Momentum", "description": "d"})
    assert created.status_code == 201 and created.json()["slug"] == "momentum"
    assert [p["slug"] for p in client.get("/projects").json()] == ["momentum"]
    assert client.get("/projects/nope").status_code == 404

    sid = client.post("/sessions", json={}).json()["id"]
    step_id = client.post(f"/sessions/{sid}/steps", json={"prompt": "load"}).json()["id"]
    wait_idle(client, sid)
    body = {"session_id": sid, "step_id": step_id, "name": "table", "mode": "live"}
    saved = client.post("/projects/momentum/views", json=body)
    assert saved.status_code == 200 and saved.json()["datasets"] == ["prices"]
    project = client.get("/projects/momentum").json()
    assert project["datasets"][0]["validated"] is True
    assert project["views"][0]["name"] == "table"

    bad = client.post("/projects/momentum/views", json={**body, "name": "Bad Name"})
    assert bad.status_code == 400
    missing = client.post(
        "/projects/momentum/datasets", json={"session_id": sid, "dataset": "nope", "mode": "live"}
    )
    assert missing.status_code == 404

    cards = [{"view": "table", "x": 0, "y": 0, "w": 6, "h": 8}]
    assert client.put("/projects/momentum/canvas", json=cards).json()["canvas"] == cards
    view = client.get("/projects/momentum/views/table").json()
    assert view["meta"]["name"] == "table" and "export default" in view["source"]
    assert view["state"] == {} and view["queries"] == []
    assert client.get("/projects/momentum/views/nope").status_code == 404


def test_save_while_running_is_409(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", "import time; time.sleep(3)"), end()])
    client = make_client(tmp_path, [], provider_factory=lambda _cfg: provider)
    client.post("/projects", json={"name": "p"})
    sid = client.post("/sessions", json={}).json()["id"]
    client.post(f"/sessions/{sid}/steps", json={"prompt": "slow"})
    body = {"session_id": sid, "dataset": "x", "mode": "live"}
    assert client.post("/projects/p/datasets", json=body).status_code == 409
    client.post(f"/sessions/{sid}/interrupt")
    wait_idle(client, sid)
