import threading
import time
from pathlib import Path
from typing import Literal, cast

import httpx
import pytest
import uvicorn
from fastapi.testclient import TestClient

from quarry.agent.fake import FakeProvider
from quarry.agent.loop import StepOutcome
from quarry.agent.runtime import ApiRuntime
from quarry.agent.tools import ToolExecutor
from quarry.agent.types import AssistantTurn, ProviderError
from quarry.config import ProviderConfig, QuarryConfig
from quarry.kernel.datasets import DatasetMeta
from quarry.server.app import QuarryServer, create_app
from quarry.server.projects import ProjectService, SaveDatasetRequest
from quarry.server.service import SessionService, runtime_from_config
from tests.server.test_app import PRICES, TIDY, TOKEN, app_of, end, py, service_of, wait_idle


class ScriptRuntime(ApiRuntime):
    def __init__(self, turns: list[AssistantTurn]) -> None:
        super().__init__(FakeProvider(turns))
        self.tidying = threading.Event()
        self.block_tidy = False
        self.cancelled = threading.Event()

    def complete_text(self, *, system: str, prompt: str, cancel: threading.Event) -> AssistantTurn:
        self.tidying.set()
        if self.block_tidy:
            assert cancel.wait(10), "tidy cancellation never arrived"
            self.cancelled.set()
            raise ProviderError("cancelled", retryable=False)
        return super().complete_text(system=system, prompt=prompt, cancel=cancel)


def runtime_client(tmp_path: Path, runtime: ScriptRuntime) -> TestClient:
    app = create_app(
        config=QuarryConfig(root=tmp_path, provider=ProviderConfig(name="codex", model="test")),
        token=TOKEN,
        runtime_factory=lambda _config: runtime,
    )
    client = TestClient(app)
    client.headers.update({"Authorization": f"Bearer {TOKEN}"})
    return client


def test_runtime_prompt_and_recipe_save_need_no_api_key(tmp_path: Path) -> None:
    runtime = ScriptRuntime([py("p", PRICES), end("loaded"), end(TIDY)])
    with runtime_client(tmp_path, runtime) as client:
        sid = client.post("/sessions", json={"title": "subscription"}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "load prices"})
        wait_idle(client, sid)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["status"] == "ok" and step["note"] == "loaded"
        assert step["provider"] == {"name": "codex", "model": "test"}
        assert step["runs"] == [{"code": PRICES, "status": "ok"}]
        projects = app_of(client).state.projects
        assert isinstance(projects, ProjectService)
        slug = projects.create("prices", "").slug
        saved = projects.save_dataset(
            slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="live")
        )
        assert saved.validated and saved.rows == 1
        assert (
            tmp_path / "projects" / slug / "datasets" / "prices" / "recipe.py"
        ).read_text() == TIDY


def test_step_records_model_reported_by_runtime(tmp_path: Path) -> None:
    class ResolvedRuntime(ScriptRuntime):
        def run_step(
            self,
            *,
            prompt: str,
            system: str,
            summary: str,
            tools: ToolExecutor,
            cancel: threading.Event,
        ) -> StepOutcome:
            outcome = super().run_step(
                prompt=prompt, system=system, summary=summary, tools=tools, cancel=cancel
            )
            return outcome.model_copy(update={"model": "resolved-model"})

    with runtime_client(tmp_path, ResolvedRuntime([end()])) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps", json={"prompt": "hello"})
        wait_idle(client, sid)
        step = client.get(f"/sessions/{sid}").json()["steps"][0]
        assert step["provider"] == {"name": "codex", "model": "resolved-model"}


def test_shutdown_cancels_tidy_after_session_hold_releases(tmp_path: Path) -> None:
    runtime = ScriptRuntime([py("p", PRICES), end("loaded"), end("later step")])
    runtime.block_tidy = True
    with runtime_client(tmp_path, runtime) as client:
        sessions = service_of(client)
        sid = sessions.create("subscription").id
        sessions.start_prompt(sid, "load prices")
        wait_idle(client, sid)
        projects = app_of(client).state.projects
        assert isinstance(projects, ProjectService)
        slug = projects.create("prices", "").slug
        errors: list[BaseException] = []

        def save() -> None:
            try:
                projects.save_dataset(
                    slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="live")
                )
            except BaseException as exc:
                errors.append(exc)

        worker = threading.Thread(target=save)
        worker.start()
        assert runtime.tidying.wait(10)
        assert not sessions.status(sid).busy
        later = sessions.start_prompt(sid, "continue")
        projects.shutdown()
        wait_idle(client, sid)
        assert sessions.step(sid, later.id).status == "ok"
        worker.join(10)
        assert not worker.is_alive() and not errors
        assert projects.get(slug).datasets[0].validated


def test_tidy_after_shutdown_uses_raw_recipe(tmp_path: Path) -> None:
    runtime = ScriptRuntime([])
    with runtime_client(tmp_path, runtime) as client:
        projects = app_of(client).state.projects
        assert isinstance(projects, ProjectService)
        projects.shutdown()
        assert projects._tidy("prices = 1", "prices") is None
        assert not runtime.tidying.is_set()


def test_app_lifespan_cancels_active_recipe_request(tmp_path: Path) -> None:
    runtime = ScriptRuntime([])
    runtime.block_tidy = True
    results: list[str | None] = []
    with runtime_client(tmp_path, runtime) as client:
        projects = app_of(client).state.projects
        assert isinstance(projects, ProjectService)
        worker = threading.Thread(target=lambda: results.append(projects._tidy("x = 1", "x")))
        worker.start()
        assert runtime.tidying.wait(10)
    worker.join(10)
    assert not worker.is_alive() and results == [None]


@pytest.mark.parametrize("blocked_phase", ["tidy", "kernel"])
def test_server_shutdown_cancels_tidy_before_draining_http_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, blocked_phase: str
) -> None:
    runtime = ScriptRuntime([py("p", PRICES), end("loaded"), end(TIDY)])
    runtime.block_tidy = blocked_phase == "tidy"
    app = create_app(
        config=QuarryConfig(root=tmp_path, provider=ProviderConfig(name="codex", model="test")),
        token=TOKEN,
        runtime_factory=lambda _config: runtime,
    )
    server = QuarryServer(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    listener = server.config.bind_socket()
    server_thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]})
    server_thread.start()
    responses: list[httpx.Response] = []
    errors: list[BaseException] = []
    request_thread: threading.Thread | None = None
    describing = threading.Event()
    release_describe = threading.Event()
    projects_stopped = threading.Event()
    stop_projects = app.state.projects.shutdown

    def stop_and_signal() -> None:
        stop_projects()
        projects_stopped.set()

    monkeypatch.setattr(app.state.projects, "shutdown", stop_and_signal)
    try:
        deadline = time.monotonic() + 10
        while not server.started:
            assert time.monotonic() < deadline, "server did not start"
            time.sleep(0.01)
        with httpx.Client(
            base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
            headers={"Authorization": f"Bearer {TOKEN}"},
            timeout=10,
            trust_env=False,
        ) as client:
            sid = client.post("/sessions", json={"title": "shutdown"}).json()["id"]
            client.post(f"/sessions/{sid}/steps", json={"prompt": "load prices"})
            deadline = time.monotonic() + 10
            while client.get(f"/sessions/{sid}/status").json()["busy"]:
                assert time.monotonic() < deadline, "prompt did not finish"
                time.sleep(0.01)
            slug = client.post("/projects", json={"name": "prices"}).json()["slug"]
            if blocked_phase == "kernel":
                with cast(SessionService, app.state.service).hold(sid) as kernel:
                    describe = kernel.describe

                def blocked_describe(name: str) -> DatasetMeta:
                    describing.set()
                    assert release_describe.wait(10), "save kernel hold was never released"
                    return describe(name)

                monkeypatch.setattr(kernel, "describe", blocked_describe)

            def save() -> None:
                try:
                    responses.append(
                        client.post(
                            f"/projects/{slug}/datasets",
                            json={"session_id": sid, "dataset": "prices", "mode": "live"},
                        )
                    )
                except BaseException as exc:
                    errors.append(exc)

            request_thread = threading.Thread(target=save)
            request_thread.start()
            entered = runtime.tidying if blocked_phase == "tidy" else describing
            assert entered.wait(10), "save did not enter its blocked phase"
            server.should_exit = True
            if blocked_phase == "tidy":
                assert runtime.cancelled.wait(3), "shutdown waited for HTTP before cancelling tidy"
            else:
                assert projects_stopped.wait(3), "shutdown did not begin request drain"
                assert not any(listener.is_serving() for listener in server.servers)
                assert kernel.is_alive(), "shutdown closed a kernel held by an HTTP save"
                release_describe.set()
            request_thread.join(10)
            server_thread.join(10)
            assert not request_thread.is_alive() and not server_thread.is_alive()
            assert not errors and responses[0].status_code == 200
            assert responses[0].json()["validated"]
            assert (tmp_path / "projects" / slug / "datasets" / "prices" / "recipe.py").exists()
    finally:
        release_describe.set()
        app.state.projects.shutdown()
        server.should_exit = True
        if request_thread is not None:
            request_thread.join(10)
        server_thread.join(10)
        listener.close()


@pytest.mark.parametrize("name", ["codex", "claude-code"])
def test_runtime_factory_selects_subscription_backend(
    tmp_path: Path, name: Literal["codex", "claude-code"]
) -> None:
    runtime = runtime_from_config(
        QuarryConfig(root=tmp_path, provider=ProviderConfig(name=name, model="test"))
    )
    assert type(runtime).__name__ == ("CodexRuntime" if name == "codex" else "ClaudeRuntime")
