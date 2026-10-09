import os
import stat
import time
from pathlib import Path

import pytest

from quarry.agent.fake import FakeProvider
from quarry.agent.transpile import NoopTranspiler
from quarry.agent.types import AssistantTurn, Provider, ToolCall
from quarry.components.library import ComponentLibrary, builtin_root
from quarry.config import ConfigError, QuarryConfig
from quarry.projects.store import ProjectStore
from quarry.query.spec import Json
from quarry.server.kernels import KernelManager, SessionBusy
from quarry.server.projects import ProjectService, SaveDatasetRequest, SaveViewRequest
from quarry.server.service import SessionService
from quarry.server.store import SessionStore

PRICES = "prices = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03'], 'px': [1.0, 2.0]})"
TIDY_OK = "import polars as pl\n" + PRICES + "\n"
TIDY_BAD = "import polars as pl\nprices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})\n"


def py(call_id: str, code: str) -> AssistantTurn:
    return AssistantTurn(
        text="",
        tool_calls=[ToolCall(id=call_id, name="run_python", input={"code": code})],
        stop="tool_use",
    )


def render(call_id: str) -> AssistantTurn:
    call = ToolCall(
        id=call_id,
        name="render_view",
        input={
            "component_id": "data-table",
            "datasets": ["prices"],
            "initial_state": '{"limit": 5}',
        },
    )
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def end(text: str = "done") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], stop="end")


def build(tmp_path: Path, provider: FakeProvider) -> tuple[SessionService, ProjectService]:
    config = QuarryConfig(root=tmp_path)
    sessions = SessionService(
        config=config,
        store=SessionStore(tmp_path),
        kernels=KernelManager(tmp_path),
        provider_factory=lambda _cfg: provider,
        library=ComponentLibrary([builtin_root()]),
        transpiler=NoopTranspiler(),
    )
    projects = ProjectService(
        config=config,
        store=ProjectStore(tmp_path),
        sessions=sessions,
        provider_factory=lambda _cfg: provider,
    )
    return sessions, projects


def wait_idle(sessions: SessionService, sid: str) -> None:
    deadline = time.monotonic() + 30
    while sessions.status(sid).running_step is not None:
        assert time.monotonic() < deadline
        time.sleep(0.05)


def run_prices(sessions: SessionService) -> tuple[str, str]:
    sid = sessions.create("t").id
    step = sessions.start_prompt(sid, "load prices")
    wait_idle(sessions, sid)
    return sid, step.id


def test_save_live_dataset_validated(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", PRICES), end(), end(TIDY_OK)])
    sessions, projects = build(tmp_path, provider)
    sid, _ = run_prices(sessions)
    slug = projects.create("Momentum", "").slug
    meta = projects.save_dataset(
        slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="live")
    )
    assert meta.validated and meta.rows == 2 and meta.mode == "live"
    base = tmp_path / "projects" / slug / "datasets" / "prices"
    assert (base / "recipe.py").read_text() == TIDY_OK
    assert "# step 1: load prices" in (base / "recipe.raw.py").read_text()
    assert not (base / "data.parquet").exists()
    sessions.shutdown()


def test_bad_tidy_falls_back_to_validated_raw(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", PRICES), end(), end(TIDY_BAD)])
    sessions, projects = build(tmp_path, provider)
    sid, _ = run_prices(sessions)
    slug = projects.create("p", "").slug
    meta = projects.save_dataset(
        slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="pinned")
    )
    assert meta.validated and meta.validation_error is None
    base = tmp_path / "projects" / slug / "datasets" / "prices"
    assert (base / "recipe.py").read_text() == (base / "recipe.raw.py").read_text()
    assert (base / "data.parquet").exists()
    sessions.shutdown()


def test_pinned_save_is_private(tmp_path: Path) -> None:
    # The kernel inherits the umask when it spawns, so it is set before the first step.
    previous = os.umask(0o022)
    try:
        provider = FakeProvider([py("c1", PRICES), end(), end(TIDY_OK)])
        sessions, projects = build(tmp_path, provider)
        sid, _ = run_prices(sessions)
        slug = projects.create("p", "").slug
        projects.save_dataset(
            slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="pinned")
        )
        sessions.shutdown()
    finally:
        os.umask(previous)
    base = tmp_path / "projects" / slug / "datasets" / "prices"
    assert stat.S_IMODE(base.stat().st_mode) == 0o700
    assert stat.S_IMODE((base / "data.parquet").stat().st_mode) == 0o600


def test_unreproducible_recipe_saved_unvalidated(tmp_path: Path) -> None:
    mark = tmp_path / "mark"
    code = (
        f"import pathlib\nm = pathlib.Path({str(mark)!r})\n"
        "n = 1 if m.exists() else 2\nm.touch()\n"
        "prices = pl.DataFrame({'px': [1.0] * n})"
    )
    provider = FakeProvider([py("c1", code), end(), end(TIDY_BAD)])
    sessions, projects = build(tmp_path, provider)
    sid, _ = run_prices(sessions)
    slug = projects.create("p", "").slug
    meta = projects.save_dataset(
        slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="pinned")
    )
    assert not meta.validated
    assert meta.validation_error is not None and "rows" in meta.validation_error
    base = tmp_path / "projects" / slug / "datasets" / "prices"
    assert (base / "recipe.py").read_text() == (base / "recipe.raw.py").read_text()
    assert (base / "data.parquet").exists()
    sessions.shutdown()


def test_save_without_a_provider_skips_the_tidy(tmp_path: Path) -> None:
    sessions, _ = build(tmp_path, FakeProvider([]))

    def no_key(_cfg: QuarryConfig) -> Provider:
        raise ConfigError("no key")

    projects = ProjectService(
        config=QuarryConfig(root=tmp_path),
        store=ProjectStore(tmp_path),
        sessions=sessions,
        provider_factory=no_key,
    )
    sid = sessions.create("t").id
    sessions.start_manual(sid, PRICES)
    wait_idle(sessions, sid)
    slug = projects.create("p", "").slug
    meta = projects.save_dataset(
        slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="pinned")
    )
    assert meta.validated and meta.validation_error is None
    base = tmp_path / "projects" / slug / "datasets" / "prices"
    assert (base / "recipe.py").read_text() == (base / "recipe.raw.py").read_text()
    sessions.shutdown()


def test_save_rejected_while_step_runs(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", "import time; time.sleep(3)"), end(), end(TIDY_OK)])
    sessions, projects = build(tmp_path, provider)
    sid = sessions.create("t").id
    sessions.start_prompt(sid, "slow")
    slug = projects.create("p", "").slug
    with pytest.raises(SessionBusy):
        projects.save_dataset(
            slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="live")
        )
    sessions.interrupt(sid)
    wait_idle(sessions, sid)
    sessions.shutdown()


def test_save_refused_until_a_reopened_session_replays(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", PRICES), render("c2"), end()])
    sessions, _ = build(tmp_path, provider)
    sid, step_id = run_prices(sessions)
    sessions.shutdown()
    # A fresh service over the same root is the server after a restart: steps, no kernel.
    sessions, projects = build(tmp_path, FakeProvider([end(TIDY_OK)]))
    slug = projects.create("p", "").slug
    with pytest.raises(ValueError, match="restart the session"):
        projects.save_dataset(
            slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="live")
        )
    with pytest.raises(ValueError, match="restart the session"):
        projects.save_view(
            slug, SaveViewRequest(session_id=sid, step_id=step_id, name="table", mode="live")
        )
    assert sessions.status(sid).kernel.status == "starting"  # the refusal spawned no kernel
    assert sessions.restart(sid).failed_step is None
    meta = projects.save_dataset(
        slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="live")
    )
    assert meta.validated
    sessions.shutdown()


def test_save_view_saves_missing_datasets_first(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", PRICES), render("c2"), end(), end(TIDY_OK)])
    sessions, projects = build(tmp_path, provider)
    sid, step_id = run_prices(sessions)
    slug = projects.create("p", "").slug
    meta = projects.save_view(
        slug, SaveViewRequest(session_id=sid, step_id=step_id, name="table", mode="live")
    )
    assert meta.datasets == ["prices"] and meta.component_id == "data-table"
    project = projects.get(slug)
    assert [d.name for d in project.datasets] == ["prices"]
    saved = ProjectStore(tmp_path).read_view(slug, "table")
    assert "export default" in saved.source and saved.state == {"limit": 5}
    assert saved.queries == []
    sessions.shutdown()


def test_save_view_keeps_the_latest_snapshot(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", PRICES), render("c2"), end(), end(TIDY_OK)])
    sessions, projects = build(tmp_path, provider)
    sid, step_id = run_prices(sessions)
    queries: list[dict[str, Json]] = [{"dataset": "prices", "limit": 9}]
    sessions.record_snapshot(sid, step_id, {"limit": 3}, [])
    sessions.record_snapshot(sid, step_id, {"limit": 9}, queries)
    slug = projects.create("p", "").slug
    projects.save_view(
        slug, SaveViewRequest(session_id=sid, step_id=step_id, name="table", mode="live")
    )
    saved = ProjectStore(tmp_path).read_view(slug, "table")
    assert saved.state == {"limit": 9} and saved.queries == queries
    sessions.shutdown()


def test_hold_refuses_steps_and_restarts(tmp_path: Path) -> None:
    sessions, _ = build(tmp_path, FakeProvider([]))
    sid = sessions.create("t").id
    with sessions.hold(sid):
        with pytest.raises(SessionBusy):
            sessions.start_manual(sid, "x = 1")
        with pytest.raises(SessionBusy):
            sessions.restart(sid)
        with pytest.raises(SessionBusy), sessions.hold(sid):
            pass
    sessions.start_manual(sid, "x = 1")
    wait_idle(sessions, sid)
    sessions.shutdown()
