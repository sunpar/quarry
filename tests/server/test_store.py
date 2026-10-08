from pathlib import Path

import pytest

from quarry.agent.tools import PendingView
from quarry.server.models import ProviderInfo, Step, StepStatus, View, now_iso
from quarry.server.store import SessionStore


def step(index: int, status: StepStatus = "ok") -> Step:
    return Step(
        id=f"s{index}",
        index=index,
        kind="prompt",
        prompt="p",
        code="x = 1",
        status=status,
        error=None,
        created_at=now_iso(),
    )


def test_create_list_get(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    a = store.create(
        title="first", provider=ProviderInfo(name="anthropic", model="claude-opus-5-5")
    )
    b = store.create(
        title="second", provider=ProviderInfo(name="anthropic", model="claude-opus-5-5")
    )
    assert [m.id for m in store.list()] == [b.id, a.id]
    assert store.get(a.id).meta.title == "first"
    assert store.get(a.id).steps == []
    with pytest.raises(KeyError):
        store.get("missing")


def test_append_and_reload_steps(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    assert store.next_index(meta.id) == 0
    store.append_step(meta.id, step(0))
    store.append_step(meta.id, step(1))
    assert store.next_index(meta.id) == 2
    reloaded = SessionStore(tmp_path).get(meta.id)
    assert [s.index for s in reloaded.steps] == [0, 1]
    assert (tmp_path / "sessions" / meta.id / "steps" / "0001.json").exists()


def test_running_step_is_rejected(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    with pytest.raises(ValueError, match="running"):
        store.append_step(meta.id, step(0, status="running"))


def test_view_from_pending_hashes_source() -> None:
    pending = PendingView(
        component_id="inline",
        source="export default () => null",
        initial_state={"a": 1},
        datasets=["df"],
    )
    view = View.from_pending(pending)
    assert len(view.content_hash) == 64
    assert view.initial_state == {"a": 1} and view.datasets == ["df"] and view.snapshots == []
