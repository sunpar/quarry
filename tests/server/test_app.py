import os
import re
import signal
import threading
import time
from collections.abc import Callable, Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import BaseRoute

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, Message, Provider, ToolCall, ToolDef
from quarry.config import ConfigError, DataConfig, QuarryConfig
from quarry.kernel.client import KernelClient
from quarry.kernel.executor import ExecResult
from quarry.server import service as service_module
from quarry.server.app import create_app
from quarry.server.kernels import ReplayReport
from quarry.server.models import Step
from quarry.server.service import ProviderFactory
from quarry.server.store import SessionStore

TOKEN = "t0k3n"
RESTARTED = "stopped by a restart"


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
    config: QuarryConfig | None = None,
) -> TestClient:
    config = config or QuarryConfig(root=tmp_path)
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


def wait_kernel(client: TestClient, sid: str, status: str, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if client.get(f"/sessions/{sid}/status").json()["kernel"]["status"] == status:
            return
        time.sleep(0.05)
    raise AssertionError(f"kernel never reached {status!r}")


def hang(flag: Path) -> str:
    """Code that creates `flag` once it runs, then sleeps longer than any test waits."""
    return f"open({str(flag)!r}, 'w').close()\nimport time\ntime.sleep(60)\n"


def wait_for_file(path: Path, timeout: float = 30.0) -> None:
    deadline = time.monotonic() + timeout
    while not path.exists():
        if time.monotonic() > deadline:
            raise AssertionError(f"{path} never appeared")
        time.sleep(0.02)


def dataset_names(client: TestClient, sid: str) -> list[str]:
    return [d["name"] for d in client.get(f"/sessions/{sid}/datasets").json()]


def start_restart(client: TestClient, sid: str) -> Callable[[], ReplayReport]:
    """Restart on a daemon thread; the returned call waits up to 30 s for its report. It goes
    through the service, not the route: a restart that never wakes then fails the test, where a
    stuck request would hang TestClient's exit."""
    service = client.app.state.service
    reports: list[ReplayReport] = []
    thread = threading.Thread(target=lambda: reports.append(service.restart(sid)), daemon=True)
    thread.start()

    def report() -> ReplayReport:
        thread.join(30)
        assert not thread.is_alive(), "the restart never woke from its wait for the step"
        return reports[0]

    return report


class GatedProvider(FakeProvider):
    """A FakeProvider whose first call sets `waiting`, then waits for `release`."""

    def __init__(self, turns: list[AssistantTurn]) -> None:
        super().__init__(turns)
        self.waiting = threading.Event()
        self.release = threading.Event()

    def complete(
        self, *, system: str, messages: list[Message], tools: list[ToolDef]
    ) -> AssistantTurn:
        if not self.calls:
            self.waiting.set()
            assert self.release.wait(30)
        return super().complete(system=system, messages=messages, tools=tools)


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


def test_finished_steps_carry_their_own_id_as_dataset_origin(tmp_path: Path) -> None:
    turns = [py("c1", "df = pl.DataFrame({'a': [1]})"), end()]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        wait_idle(client, sid)
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "other = df.select('a')"})
        wait_idle(client, sid)
        failing = {"code": "late = df.select('a')\n1/0"}
        client.post(f"/sessions/{sid}/steps/manual", json=failing)
        wait_idle(client, sid)
        steps = client.get(f"/sessions/{sid}").json()["steps"]
        assert [s["kind"] for s in steps] == ["prompt", "manual", "manual"]
        assert steps[2]["status"] == "error" and steps[2]["writes"] == ["late"]
        for s in steps:
            assert [d["origin_step"] for d in s["datasets"]] == [s["id"]]
        # What is saved carries it too, not just the response.
        saved = SessionStore(tmp_path).get(sid).steps
        assert [d.origin_step for s in saved for d in s.datasets] == [s.id for s in saved]


def test_datasets_origin_is_the_latest_step_that_wrote_the_name(tmp_path: Path) -> None:
    turns = [py("c1", "df = pl.DataFrame({'a': [1]})"), end()]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        wait_idle(client, sid)
        for code in ["other = df.select('a')", "df = pl.DataFrame({'a': [2]})", "n = df.height"]:
            client.post(f"/sessions/{sid}/steps/manual", json={"code": code})
            wait_idle(client, sid)
        # No step wrote this one.
        client.app.state.service._kernels.get(sid).execute("orphan = pl.DataFrame({'a': [3]})")
        ids = [s["id"] for s in client.get(f"/sessions/{sid}").json()["steps"]]
        origins = {
            d["name"]: d["origin_step"] for d in client.get(f"/sessions/{sid}/datasets").json()
        }
        assert origins == {"df": ids[2], "other": ids[1], "orphan": None}


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


def test_kernel_threads_config_caps_polars_in_session_kernels(tmp_path: Path) -> None:
    config = QuarryConfig(root=tmp_path, data=DataConfig(kernel_threads=2))
    with make_client(tmp_path, [], config=config) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        manual = {"code": "print(pl.thread_pool_size())"}
        assert client.post(f"/sessions/{sid}/steps/manual", json=manual).status_code == 202
        wait_idle(client, sid)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["stdout_tail"].strip() == "2"


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
        # A dead kernel stays dead: reads fail instead of starting an empty one.
        assert client.get(f"/sessions/{sid}/datasets").status_code == 503
        assert client.post(f"/sessions/{sid}/interrupt").status_code == 503
        assert client.get(f"/sessions/{sid}/status").json()["kernel"]["status"] == "dead"
        report = client.post(f"/sessions/{sid}/restart").json()
        # The crashing step has no runs, since the kernel died before answering.
        assert report == {"replayed": 2, "failed_step": None, "error": None}
        assert client.get(f"/sessions/{sid}/status").json()["kernel"]["status"] == "idle"
        assert dataset_names(client, sid) == []


def test_restart_kills_a_hung_manual_step_and_replays(tmp_path: Path) -> None:
    started = tmp_path / "started"
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(
            f"/sessions/{sid}/steps/manual", json={"code": "base = pl.DataFrame({'a': [1]})"}
        )
        wait_idle(client, sid)
        client.post(f"/sessions/{sid}/steps/manual", json={"code": hang(started)})
        wait_for_file(started)
        began = time.monotonic()
        report = client.post(f"/sessions/{sid}/restart").json()
        assert time.monotonic() - began < 30  # the step sleeps for 60 seconds
        assert report == {"replayed": 2, "failed_step": None, "error": None}
        steps = client.get(f"/sessions/{sid}").json()["steps"]
        assert [s["status"] for s in steps] == ["ok", "interrupted"]
        assert steps[1]["error"]["message"] == RESTARTED and steps[1]["runs"] == []
        assert dataset_names(client, sid) == ["base"]
        assert client.get(f"/sessions/{sid}/status").json()["kernel"]["status"] == "idle"


def test_restart_kills_a_hung_prompt_step_and_replays_its_runs(tmp_path: Path) -> None:
    started = tmp_path / "started"
    load = "df = base.with_columns(b=pl.lit(2))"
    turns = [py("c1", load), py("c2", hang(started)), end()]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(
            f"/sessions/{sid}/steps/manual", json={"code": "base = pl.DataFrame({'a': [1]})"}
        )
        wait_idle(client, sid)
        client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        wait_for_file(started)
        began = time.monotonic()
        report = client.post(f"/sessions/{sid}/restart").json()
        assert time.monotonic() - began < 30  # the step sleeps for 60 seconds
        assert report == {"replayed": 2, "failed_step": None, "error": None}
        step = client.get(f"/sessions/{sid}").json()["steps"][1]
        assert step["status"] == "interrupted" and step["error"]["message"] == RESTARTED
        # The run the kill cut short is not kept; the one before it is, and was replayed.
        assert step["runs"] == [{"code": load, "status": "ok"}]
        assert dataset_names(client, sid) == ["base", "df"]


@pytest.mark.parametrize("warm", [False, True], ids=["no-kernel-yet", "kernel-running"])
def test_restart_before_a_step_reaches_its_kernel_stops_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, warm: bool
) -> None:
    started = tmp_path / "started"
    with make_client(tmp_path, []) as client:
        kernels = client.app.state.service._kernels
        sid = client.post("/sessions", json={}).json()["id"]
        if warm:
            client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
            wait_idle(client, sid)
        get, kill = kernels.get, kernels.kill
        in_get, killed = threading.Event(), threading.Event()

        # The step thread gets its kernel only after the restart's kill, found one or not.
        def get_after_kill(session_id: str) -> KernelClient:
            in_get.set()
            assert killed.wait(30)
            return get(session_id)

        def kill_and_signal(session_id: str) -> None:
            kill(session_id)
            killed.set()

        monkeypatch.setattr(kernels, "get", get_after_kill)
        monkeypatch.setattr(kernels, "kill", kill_and_signal)
        client.post(f"/sessions/{sid}/steps/manual", json={"code": hang(started)})
        assert in_get.wait(30)
        report = start_restart(client, sid)
        assert report().failed_step is None
        step = client.get(f"/sessions/{sid}").json()["steps"][-1]
        assert step["status"] == "interrupted" and step["error"]["message"] == RESTARTED
        assert not started.exists()  # its code never ran, on the old kernel or a new one


def test_restart_stops_a_step_waiting_on_the_model(tmp_path: Path) -> None:
    provider = GatedProvider([py("c1", "x = 1"), end()])
    with make_client(tmp_path, [], provider_factory=lambda _cfg: provider) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "go"})
        assert provider.waiting.wait(30)
        report = start_restart(client, sid)
        wait_kernel(client, sid, "dead")  # the restart cancelled the step and killed its kernel
        # The restart waits on the model for its step; it holds the session meanwhile.
        assert client.post(f"/sessions/{sid}/restart").status_code == 409
        assert client.post(f"/sessions/{sid}/steps", json={"prompt": "x"}).status_code == 409
        provider.release.set()
        assert report() == ReplayReport(replayed=1, failed_step=None, error=None)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["status"] == "interrupted" and step["error"]["message"] == RESTARTED
        assert step["runs"] == [] and len(provider.calls) == 1


def test_restart_never_relabels_a_step_that_ended_on_its_own(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    apply_exec = service_module._apply_exec
    ran, finish = threading.Event(), threading.Event()

    # The step's code has run and it is ok; it waits here, not yet saved, while a restart comes.
    def apply_after_restart(step: Step, result: ExecResult, started: float) -> Step:
        ran.set()
        assert finish.wait(30)
        return apply_exec(step, result, started)

    monkeypatch.setattr(service_module, "_apply_exec", apply_after_restart)
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
        assert ran.wait(30)
        report = start_restart(client, sid)
        wait_kernel(client, sid, "dead")  # the restart has claimed the session and killed it
        finish.set()
        assert report().failed_step is None
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["status"] == "ok" and step["error"] is None
        assert client.get(f"/sessions/{sid}/status").json()["last_error"] is None


def test_restart_refuses_steps_and_restarts_while_it_replays(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    with make_client(tmp_path, []) as client:
        kernels = client.app.state.service._kernels
        replay = kernels.restart
        replaying, finish = threading.Event(), threading.Event()

        def gated_replay(session_id: str, steps: list[Step]) -> ReplayReport:
            replaying.set()
            assert finish.wait(30)
            return replay(session_id, steps)

        monkeypatch.setattr(kernels, "restart", gated_replay)
        sid = client.post("/sessions", json={}).json()["id"]
        codes: list[int] = []
        restart = threading.Thread(
            target=lambda: codes.append(client.post(f"/sessions/{sid}/restart").status_code)
        )
        restart.start()
        assert replaying.wait(30)
        assert client.post(f"/sessions/{sid}/restart").status_code == 409
        manual = {"code": "a = 1"}
        assert client.post(f"/sessions/{sid}/steps/manual", json=manual).status_code == 409
        # A half-replayed namespace is not the session's.
        assert client.post(f"/sessions/{sid}/query", json={"dataset": "df"}).status_code == 409
        assert client.get(f"/sessions/{sid}/datasets").status_code == 409
        assert client.post(f"/sessions/{sid}/interrupt").status_code == 409
        finish.set()
        restart.join(30)
        assert codes == [200]
        assert client.post(f"/sessions/{sid}/steps/manual", json=manual).status_code == 202
        wait_idle(client, sid)


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
        wait_kernel(client, sid, "running")
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
        assert dataset_names(client, sid) == ["df"]


def test_restart_restores_what_failed_blocks_left_behind(tmp_path: Path) -> None:
    turns = [py("c1", "df = pl.DataFrame({'a': [1]})\n1/0"), py("c2", "n = df.height"), end()]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        wait_idle(client, sid)
        for code in ["m = n + 1\n1/0", "k = m"]:
            client.post(f"/sessions/{sid}/steps/manual", json={"code": code})
            wait_idle(client, sid)
        steps = client.get(f"/sessions/{sid}").json()["steps"]
        assert [s["status"] for s in steps] == ["ok", "error", "ok"]
        report = client.post(f"/sessions/{sid}/restart").json()
        assert report == {"replayed": 3, "failed_step": None, "error": None}
        assert dataset_names(client, sid) == ["df"]


def test_restart_replays_ok_code_of_a_prompt_step_the_kernel_died_in(tmp_path: Path) -> None:
    turns = [py("c1", "df = pl.DataFrame({'a': [1]})"), py("c2", "import os\nos._exit(2)\n")]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        assert wait_idle(client, sid)["kernel"]["status"] == "dead"
        report = client.post(f"/sessions/{sid}/restart").json()
        assert report["failed_step"] is None and report["replayed"] == 1
        assert dataset_names(client, sid) == ["df"]


def test_interrupt_cancels_a_step_waiting_on_the_model(tmp_path: Path) -> None:
    provider = GatedProvider([py("c1", "x = 1"), end()])
    with make_client(tmp_path, [], provider_factory=lambda _cfg: provider) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "go"})
        assert provider.waiting.wait(30)
        # The kernel runs nothing, so only the cancel stops the step.
        assert client.post(f"/sessions/{sid}/interrupt").json() == {"ok": True}
        provider.release.set()
        wait_idle(client, sid)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["status"] == "interrupted"
        assert step["error"]["message"] == "interrupted by researcher"
        assert step["runs"] == [] and len(provider.calls) == 1


def test_interrupt_cancels_a_step_waiting_on_the_model_after_its_kernel_died(
    tmp_path: Path,
) -> None:
    provider = GatedProvider([py("c1", "x = 1"), end()])
    with make_client(tmp_path, [], provider_factory=lambda _cfg: provider) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "go"})
        assert provider.waiting.wait(30)
        os.kill(client.get(f"/sessions/{sid}/status").json()["kernel"]["pid"], signal.SIGKILL)
        wait_kernel(client, sid, "dead")
        # Still 503 for the dead kernel, but the step is cancelled before the next tool call.
        assert client.post(f"/sessions/{sid}/interrupt").status_code == 503
        provider.release.set()
        wait_idle(client, sid)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["status"] == "interrupted"
        assert step["error"]["message"] == "interrupted by researcher"
        assert len(provider.calls) == 1


def test_crashed_prompt_step_keeps_its_runs_and_lineage(tmp_path: Path) -> None:
    load = "df = pl.DataFrame({'a': [1]})"

    def origins() -> dict[str, str | None]:
        listed = client.get(f"/sessions/{sid}/datasets").json()
        return {d["name"]: d["origin_step"] for d in listed}

    # Out of turns, the provider raises on its second call, as a bug in an adapter would.
    with make_client(tmp_path, [py("c1", load)]) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "load"})
        wait_idle(client, sid)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["status"] == "error" and step["error"]["type"] == "AssertionError"
        assert step["runs"] == [{"code": load, "status": "ok"}]
        assert step["writes"] == ["df"] and [d["name"] for d in step["datasets"]] == ["df"]
        assert origins() == {"df": step["id"]}
        report = client.post(f"/sessions/{sid}/restart").json()
        assert report == {"replayed": 1, "failed_step": None, "error": None}
        assert origins() == {"df": step["id"]}


def test_interrupt_when_idle_reports_nothing_interrupted(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
        wait_idle(client, sid)
        assert client.post(f"/sessions/{sid}/interrupt").json() == {"ok": False}


def test_save_failure_frees_the_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    escaped: list[threading.ExceptHookArgs] = []
    monkeypatch.setattr(threading, "excepthook", escaped.append)
    with make_client(tmp_path, []) as client:
        store = client.app.state.service._store
        save = store.append_step
        failures = [OSError("disk full")]

        def save_fails_once(session_id: str, step: Step) -> None:
            if failures:
                raise failures.pop()
            save(session_id, step)

        monkeypatch.setattr(store, "append_step", save_fails_once)
        sid = client.post("/sessions", json={}).json()["id"]
        first = client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
        assert first.status_code == 202
        status = wait_idle(client, sid, timeout=5)
        assert status["last_error"] == "failed to save step: disk full"
        second = client.post(f"/sessions/{sid}/steps/manual", json={"code": "b = 2"})
        assert second.status_code == 202
        assert wait_idle(client, sid)["last_error"] is None
        assert [s["code"] for s in client.get(f"/sessions/{sid}").json()["steps"]] == ["b = 2"]
    # The save error still escapes the step thread rather than being swallowed.
    assert [type(e.exc_value) for e in escaped] == [OSError]


def test_thread_start_failure_frees_the_session(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    class NoThread:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> None:
            raise RuntimeError("can't start new thread")

    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        with monkeypatch.context() as patch:
            patch.setattr(
                service_module, "threading", SimpleNamespace(Thread=NoThread, Event=threading.Event)
            )
            with pytest.raises(RuntimeError, match="can't start new thread"):
                client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
        status = client.get(f"/sessions/{sid}/status").json()
        assert status["running_step"] is None
        assert status["last_error"] == "failed to start step: can't start new thread"
        assert (
            client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"}).status_code == 202
        )
        wait_idle(client, sid)


class Unprintable(Exception):
    def __str__(self) -> str:
        raise RuntimeError("no text")


def test_unprintable_exception_still_fails_the_step(tmp_path: Path) -> None:
    def factory(_cfg: QuarryConfig) -> Provider:
        raise Unprintable()

    with make_client(tmp_path, [], provider_factory=factory) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "go"})
        assert wait_idle(client, sid)["last_error"] == "<unprintable Unprintable>"
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["status"] == "error" and step["error"]["type"] == "Unprintable"
        assert client.post(f"/sessions/{sid}/steps", json={"prompt": "again"}).status_code == 202
        wait_idle(client, sid)


def test_shutdown_saves_the_step_it_stops(tmp_path: Path) -> None:
    started = tmp_path / "started"
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps/manual", json={"code": hang(started)})
        wait_for_file(started)
        began = time.monotonic()
    assert time.monotonic() - began < 30  # the step sleeps for 60 seconds
    [step] = SessionStore(tmp_path).get(sid).steps
    assert step.status == "interrupted"


def test_prompt_step_keeps_the_output_of_its_runs(tmp_path: Path) -> None:
    turns = [py("c1", "print('one')"), py("c2", "import sys\nprint('two', file=sys.stderr)"), end()]
    with make_client(tmp_path, turns) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "go"})
        wait_idle(client, sid)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["stdout_tail"] == "one\n" and step["stderr_tail"] == "two\n"


def test_prompt_steps_record_the_model_they_called(tmp_path: Path) -> None:
    with make_client(tmp_path, [end()]) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "go"})
        wait_idle(client, sid)
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "a = 1"})
        wait_idle(client, sid)
        prompt, manual = client.get(f"/sessions/{sid}").json()["steps"]
    # The session records the model it began with; a config change later shows per step.
    assert prompt["provider"] == {"name": "anthropic", "model": "claude-opus-5-5"}
    assert manual["provider"] is None


def test_a_prompt_sees_loaders_added_while_the_server_runs(tmp_path: Path) -> None:
    provider = FakeProvider([end(), end()])
    loader = (
        '[[loader]]\nname = "daily"\ndescription = "d"\n'
        'import = "tests.data.fake_firmlib:load_daily"\nsignature = "daily(tickers)"\n'
    )
    with make_client(tmp_path, [], provider_factory=lambda _cfg: provider) as client:
        first = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{first}/steps", json={"prompt": "go"})
        wait_idle(client, first)
        (tmp_path / "loaders.toml").write_text(loader)  # added while the server runs
        second = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{second}/steps", json={"prompt": "go"})
        wait_idle(client, second)
    assert "daily(tickers)" not in provider.calls[0][0]
    assert "daily(tickers)" in provider.calls[1][0]
