from pathlib import Path

from quarry.agent.fake import FakeProvider
from tests.server.test_app import PRICES, TIDY, end, make_client, py, view_turn, wait_idle
from tests.server.test_recall import saved_project


def test_project_crud_and_save_flow(tmp_path: Path) -> None:
    provider = FakeProvider(
        [py("c1", PRICES), view_turn("c2", datasets=["prices"]), end(), end(TIDY)]
    )
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


def test_canvas_rejects_a_view_twice(tmp_path: Path) -> None:
    client = make_client(tmp_path, [])
    client.post("/projects", json={"name": "p"})
    card = {"view": "table", "x": 0, "y": 0, "w": 6, "h": 8}
    assert client.put("/projects/p/canvas", json=[card, {**card, "y": 8}]).status_code == 400
    assert client.get("/projects/p").json()["meta"]["canvas"] == []


def test_export_routes(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "live")
    nb = client.get("/projects/p/export.ipynb")
    assert nb.status_code == 200
    assert nb.headers["content-disposition"] == 'attachment; filename="p.ipynb"'
    assert nb.json()["nbformat"] == 4 and any(c["cell_type"] == "code" for c in nb.json()["cells"])
    script = client.get("/projects/p/datasets/prices/recipe.py")
    assert script.status_code == 200 and script.headers["content-type"].startswith("text/x-python")
    assert script.headers["content-disposition"] == 'attachment; filename="prices.py"'
    assert "prices = " in script.text
    assert client.get("/projects/p/datasets/nope/recipe.py").status_code == 404
    assert client.get("/projects/nope/export.ipynb").status_code == 404
    assert client.get("/projects/nope/datasets/prices/recipe.py").status_code == 404
