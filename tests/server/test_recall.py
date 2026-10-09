import time
from pathlib import Path

from fastapi.testclient import TestClient

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn
from tests.server.test_app import (
    PRICES,
    TIDY,
    dataset_names,
    end,
    hang,
    make_client,
    py,
    view_turn,
    wait_for_file,
    wait_idle,
)


def saved_project(tmp_path: Path, mode: str, *later: AssistantTurn) -> tuple[TestClient, str]:
    provider = FakeProvider(
        [
            py("c1", PRICES),
            view_turn("c2", datasets=["prices"], initial_state='{"limit": 7}'),
            end(),
            end(TIDY),
            *later,
        ]
    )
    client = make_client(tmp_path, [], provider_factory=lambda _cfg: provider)
    client.post("/projects", json={"name": "p"})
    sid = client.post("/sessions", json={}).json()["id"]
    step_id = client.post(f"/sessions/{sid}/steps", json={"prompt": "load"}).json()["id"]
    wait_idle(client, sid)
    body = {"session_id": sid, "step_id": step_id, "name": "table", "mode": mode}
    assert client.post("/projects/p/views", json=body).status_code == 200
    return client, sid


def test_recall_live_dataset_into_new_session(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "live")
    sid = client.post("/sessions", json={}).json()["id"]
    body = {"project": "p", "kind": "dataset", "name": "prices"}
    step = client.post(f"/sessions/{sid}/recall", json=body)
    assert step.status_code == 202 and step.json()["kind"] == "recall"
    wait_idle(client, sid)
    done = client.get(f"/sessions/{sid}").json()["steps"][0]
    assert done["status"] == "ok" and done["writes"] == ["prices"]
    assert done["code"] == TIDY and done["runs"][0]["status"] == "ok"
    assert dataset_names(client, sid) == ["prices"]


def test_recall_pinned_reads_parquet(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "pinned")
    sid = client.post("/sessions", json={}).json()["id"]
    body = {"project": "p", "kind": "dataset", "name": "prices"}
    client.post(f"/sessions/{sid}/recall", json=body)
    wait_idle(client, sid)
    done = client.get(f"/sessions/{sid}").json()["steps"][0]
    assert "pl.read_parquet(" in done["code"] and "data.parquet" in done["code"]
    assert done["status"] == "ok" and done["datasets"][0]["rows"] == 1


def test_recall_view_mounts_with_saved_state(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "live")
    sid = client.post("/sessions", json={}).json()["id"]
    body = {"project": "p", "kind": "view", "name": "table"}
    client.post(f"/sessions/{sid}/recall", json=body)
    wait_idle(client, sid)
    done = client.get(f"/sessions/{sid}").json()["steps"][0]
    assert done["status"] == "ok" and done["writes"] == ["prices"]
    assert done["view"]["initial_state"] == {"limit": 7}
    assert done["view"]["datasets"] == ["prices"] and "export default" in done["view"]["source"]
    again = client.post(f"/sessions/{sid}/recall", json=body)
    wait_idle(client, sid)
    second = client.get(f"/sessions/{sid}").json()["steps"][1]
    assert again.status_code == 202 and second["writes"] == [] and second["view"] is not None


def test_restart_replays_a_recall_step(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "live")
    sid = client.post("/sessions", json={}).json()["id"]
    body = {"project": "p", "kind": "dataset", "name": "prices"}
    client.post(f"/sessions/{sid}/recall", json=body)
    wait_idle(client, sid)
    report = client.post(f"/sessions/{sid}/restart").json()
    assert report["failed_step"] is None and report["replayed"] == 1
    assert dataset_names(client, sid) == ["prices"]


def test_recall_unknown_is_404(tmp_path: Path) -> None:
    client, sid = saved_project(tmp_path, "live")
    body = {"project": "p", "kind": "dataset", "name": "nope"}
    assert client.post(f"/sessions/{sid}/recall", json=body).status_code == 404
    body = {"project": "zzz", "kind": "view", "name": "table"}
    assert client.post(f"/sessions/{sid}/recall", json=body).status_code == 404


def test_recall_view_while_running_is_409(tmp_path: Path) -> None:
    flag = tmp_path / "running"
    client, _ = saved_project(tmp_path, "live", py("c3", hang(flag)), end())
    sid = client.post("/sessions", json={}).json()["id"]
    client.post(f"/sessions/{sid}/steps", json={"prompt": "slow"})
    wait_for_file(flag)  # the kernel is executing, so it answers nothing until the step ends
    body = {"project": "p", "kind": "view", "name": "table"}
    started = time.monotonic()
    assert client.post(f"/sessions/{sid}/recall", json=body).status_code == 409
    assert time.monotonic() - started < 2.0
    client.post(f"/sessions/{sid}/interrupt")
    wait_idle(client, sid)


def test_recall_into_unknown_session_is_404(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "live")
    body = {"project": "p", "kind": "dataset", "name": "prices"}
    assert client.post("/sessions/nosuchsession/recall", json=body).status_code == 404
    # The session is checked before the project, so the 404 names the session.
    both_unknown = client.post("/sessions/nosuchsession/recall", json={**body, "project": "zzz"})
    assert both_unknown.status_code == 404 and "nosuchsession" in both_unknown.json()["detail"]
