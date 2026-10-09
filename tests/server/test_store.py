from pathlib import Path
from typing import Any

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


def test_torn_write_leaves_sessions_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    store.append_step(meta.id, step(0))
    write_text = Path.write_text

    def torn(self: Path, data: str, *args: Any, **kwargs: Any) -> int:
        write_text(self, data[: len(data) // 2])
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(Path, "write_text", torn)
        with pytest.raises(OSError, match="disk full"):
            store.append_step(meta.id, step(1))
        with pytest.raises(OSError, match="disk full"):
            store.create(title="torn", provider=ProviderInfo(name="openai", model="gpt"))
    assert [s.index for s in store.get(meta.id).steps] == [0]
    assert store.next_index(meta.id) == 1
    assert [m.id for m in store.list()] == [meta.id]


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


def test_update_step_rewrites_in_place(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="fake", model="m"))
    first = step(0)
    store.append_step(meta.id, first)
    store.update_step(meta.id, first.model_copy(update={"note": "changed"}))
    assert store.get(meta.id).steps[0].note == "changed"
    assert store.next_index(meta.id) == 1
    with pytest.raises(KeyError):
        store.update_step(meta.id, step(5))
