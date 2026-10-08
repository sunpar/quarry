import re
import time
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import BaseRoute

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, Provider, ToolCall
from quarry.config import ConfigError, QuarryConfig
from quarry.server.app import create_app
from quarry.server.service import ProviderFactory

TOKEN = "t0k3n"


def py(call_id: str, code: str) -> AssistantTurn:
    return AssistantTurn(
        text="",
        tool_calls=[ToolCall(id=call_id, name="run_python", input={"code": code})],
        stop="tool_use",
    )


def end(text: str = "done") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], stop="end")


def make_client(
    tmp_path: Path,
    turns: list[AssistantTurn],
    *,
    provider_factory: ProviderFactory | None = None,
) -> TestClient:
    config = QuarryConfig(root=tmp_path)
    factory = provider_factory or (lambda _cfg: FakeProvider(turns))
    app = create_app(config=config, token=TOKEN, provider_factory=factory)
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def wait_idle(client: TestClient, sid: str, timeout: float = 30.0) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        status: dict[str, Any] = client.get(f"/sessions/{sid}/status").json()
        if status["running_step"] is None:
            return status
        time.sleep(0.05)
    raise AssertionError("step did not finish")


def wait_kernel_running(client: TestClient, sid: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        kernel = client.get(f"/sessions/{sid}/status").json()["kernel"]
        if kernel["status"] == "running" and kernel["pid"] is not None:
            return
        time.sleep(0.05)
    raise AssertionError("kernel never started running the step")


def api_routes(routes: list[BaseRoute]) -> Iterator[APIRoute]:
    for route in routes:
        if isinstance(route, APIRoute):
            yield route
        # FastAPI 0.14x keeps an included router as one entry instead of copying its routes.
        nested = getattr(route, "original_router", None)
        if nested is not None:
            yield from api_routes(nested.routes)


def test_auth_required(tmp_path: Path) -> None:
    client = make_client(tmp_path, [])
    assert client.get("/healthz").status_code == 200
    bare = TestClient(client.app)
    assert bare.get("/sessions").status_code == 401
    wrong = {"Authorization": "Bearer wrong"}
    assert bare.get("/sessions", headers=wrong).status_code == 401
    assert bare.get("/openapi.json").status_code == 404
    # A route registered outside the authed router would answer here without a token.
    checked: list[str] = []
    for route in api_routes(client.app.routes):
        if route.path in {"/healthz", "/"}:
            continue
        path = re.sub(r"\{[^}]+\}", "x", route.path)
        for method in route.methods:
            assert bare.request(method, path).status_code == 401, f"{method} {route.path}"
        checked.append(route.path)
    assert "/sessions/{session_id}/restart" in checked  # the authed router's routes were walked


def test_prompt_step_end_to_end(tmp_path: Path) -> None:
    turns = [py("c1", "df = pl.DataFrame({'a': [3, 1, 2]})"), end("loaded")]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={"title": "t"}).json()["id"]
        created = client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        assert created.status_code == 202
        assert created.json()["status"] == "running"
        status = wait_idle(client, sid)
        assert status["kernel"]["status"] == "idle" and status["last_error"] is None
        session = client.get(f"/sessions/{sid}").json()
        step = session["steps"][0]
        assert step["status"] == "ok" and step["note"] == "loaded" and step["writes"] == ["df"]
        assert step["kind"] == "prompt" and step["transcript"] is not None
        spec = {"dataset": "df", "sort": [{"col": "a"}]}
        result = client.post(f"/sessions/{sid}/query", json=spec).json()
        assert result["rows"] == [{"a": 1}, {"a": 2}, {"a": 3}]
        assert result["schema"] == [{"name": "a", "dtype": "Int64"}]
        datasets = client.get(f"/sessions/{sid}/datasets").json()
        assert datasets[0]["name"] == "df"
        assert "schema" in datasets[0] and "schema_" not in datasets[0]


def test_second_step_while_running_is_409(tmp_path: Path) -> None:
    turns = [py("c1", "import time\ntime.sleep(1.5)\nx = 1"), end()]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        assert client.post(f"/sessions/{sid}/steps", json={"prompt": "slow"}).status_code == 202
        assert client.post(f"/sessions/{sid}/steps", json={"prompt": "again"}).status_code == 409
        wait_idle(client, sid)
        assert client.get(f"/sessions/{sid}").json()["steps"][0]["status"] == "ok"


def test_manual_step_and_bad_query(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        manual = {"code": "df = pl.DataFrame({'a': [1]})"}
        assert client.post(f"/sessions/{sid}/steps/manual", json=manual).status_code == 202
        wait_idle(client, sid)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["kind"] == "manual" and step["status"] == "ok" and step["transcript"] is None
        bad_column = {"dataset": "df", "filters": [{"col": "zz", "op": "eq", "value": 1}]}
        assert client.post(f"/sessions/{sid}/query", json=bad_column).status_code == 400
        assert client.post(f"/sessions/{sid}/query", json={"dataset": "nope"}).status_code == 400


def test_query_spec_validation_is_400(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        rejected = client.post(f"/sessions/{sid}/query", json={"dataset": "df", "limit": 0})
        assert rejected.status_code == 400
        assert "limit" in rejected.json()["detail"]


def test_kernel_death_then_restart_replays(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
        wait_idle(client, sid)
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "import os\nos._exit(2)\n"})
        status = wait_idle(client, sid)
        assert status["kernel"]["status"] == "dead"
        steps = client.get(f"/sessions/{sid}").json()["steps"]
        assert steps[1]["status"] == "error" and "kernel" in steps[1]["error"]["message"].lower()
        report = client.post(f"/sessions/{sid}/restart").json()
        assert report["failed_step"] is None
        # only the ok step is replayed; the crashing step is skipped
        assert report["replayed"] == 1
        assert client.get(f"/sessions/{sid}/status").json()["kernel"]["status"] == "idle"


def test_restart_while_step_runs_is_409(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        slow = {"code": "import time\ntime.sleep(1.5)\nx = 1"}
        assert client.post(f"/sessions/{sid}/steps/manual", json=slow).status_code == 202
        assert client.post(f"/sessions/{sid}/restart").status_code == 409
        wait_idle(client, sid)
        assert client.get(f"/sessions/{sid}").json()["steps"][0]["status"] == "ok"


def test_provider_failure_ends_step_and_frees_session(tmp_path: Path) -> None:
    def no_key(_cfg: QuarryConfig) -> Provider:
        raise ConfigError("No API key")

    with make_client(tmp_path, [], provider_factory=no_key) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        assert client.post(f"/sessions/{sid}/steps", json={"prompt": "go"}).status_code == 202
        status = wait_idle(client, sid)
        assert status["last_error"] is not None and "No API key" in status["last_error"]
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["status"] == "error" and "No API key" in step["error"]["message"]
        assert step["error"]["type"] == "ConfigError"
        assert client.post(f"/sessions/{sid}/steps", json={"prompt": "again"}).status_code == 202
        wait_idle(client, sid)


def test_sessions_survive_server_restart(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={"title": "keep"}).json()["id"]
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
        wait_idle(client, sid)
    with make_client(tmp_path, []) as again:
        session = again.get(f"/sessions/{sid}").json()
        assert session["meta"]["title"] == "keep" and len(session["steps"]) == 1
        assert again.get(f"/sessions/{sid}/status").json()["kernel"]["status"] == "starting"
        assert again.get("/sessions/missing").status_code == 404


def test_interrupt_running_step(tmp_path: Path) -> None:
    turns = [py("c1", "import time\nwhile True:\n    time.sleep(0.01)\n"), end()]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "spin"})
        wait_kernel_running(client, sid)
        time.sleep(0.3)  # the kernel exists; give the step a beat to start executing
        assert client.post(f"/sessions/{sid}/interrupt").json() == {"ok": True}
        wait_idle(client, sid)
        assert client.get(f"/sessions/{sid}").json()["steps"][0]["status"] == "interrupted"


def test_restart_replays_ok_code_of_a_failed_prompt_step(tmp_path: Path) -> None:
    load = "df = pl.DataFrame({'a': [1]})"
    turns = [py("c1", load), py("c2", "1/0"), py("c3", "1/0"), end()]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        wait_idle(client, sid)
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "n = df.height"})
        wait_idle(client, sid)
        steps = client.get(f"/sessions/{sid}").json()["steps"]
        assert [s["status"] for s in steps] == ["error", "ok"] and steps[0]["code"] == load
        report = client.post(f"/sessions/{sid}/restart").json()
        assert report["failed_step"] is None and report["replayed"] == 2
        assert [d["name"] for d in client.get(f"/sessions/{sid}/datasets").json()] == ["df"]


def test_restart_replays_ok_code_of_a_prompt_step_the_kernel_died_in(tmp_path: Path) -> None:
    turns = [py("c1", "df = pl.DataFrame({'a': [1]})"), py("c2", "import os\nos._exit(2)\n")]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        assert wait_idle(client, sid)["kernel"]["status"] == "dead"
        report = client.post(f"/sessions/{sid}/restart").json()
        assert report["failed_step"] is None and report["replayed"] == 1
        assert [d["name"] for d in client.get(f"/sessions/{sid}/datasets").json()] == ["df"]
