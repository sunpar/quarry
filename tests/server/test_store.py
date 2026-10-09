import os
import stat
from collections.abc import Iterator
from pathlib import Path

import pytest

from quarry.agent.tools import PendingView
from quarry.server.models import ProviderInfo, Step, StepStatus, View, now_iso
from quarry.server.store import SessionStore
from tests.fixtures import umask


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
    with pytest.raises(KeyError):  # a request's session id is one path segment
        store.get(f"../sessions/{a.id}")


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


def record_fsyncs(monkeypatch: pytest.MonkeyPatch) -> list[os.stat_result]:
    """Each file `os.fsync` is given from now on, as `fstat` saw it."""
    synced: list[os.stat_result] = []
    fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        synced.append(os.fstat(fd))
        fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    return synced


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@pytest.fixture
def umask_022() -> Iterator[None]:
    """A typical umask, under which default modes (0o755, 0o644) would let others read."""
    with umask(0o022):
        yield


@pytest.mark.usefixtures("umask_022")
def test_session_files_are_private(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    store.append_step(meta.id, step(0))
    session_dir = tmp_path / "sessions" / meta.id
    for directory in [tmp_path / "sessions", session_dir, session_dir / "steps"]:
        assert mode(directory) == 0o700, directory
    for file in [session_dir / "session.json", session_dir / "steps" / "0000.json"]:
        assert mode(file) == 0o600, file
    assert sorted(p.name for p in session_dir.rglob("*") if p.is_file()) == [
        "0000.json",
        "session.json",
    ]


@pytest.mark.usefixtures("umask_022")
def test_existing_sessions_directory_keeps_its_mode(tmp_path: Path) -> None:
    sessions = tmp_path / "sessions"
    sessions.mkdir(mode=0o755)
    SessionStore(tmp_path).create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    assert mode(sessions) == 0o755


def test_write_syncs_the_file_before_replace_and_the_directory_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    steps_dir = tmp_path / "sessions" / meta.id / "steps"
    synced = record_fsyncs(monkeypatch)
    replaced_after: list[int] = []  # how many fsyncs came before each replace
    replace = Path.replace

    def recording_replace(self: Path, target: Path) -> Path:
        replaced_after.append(len(synced))
        return replace(self, target)

    def no_chmod(*_: object, **__: object) -> None:
        raise AssertionError("the temp file is created private, not narrowed afterwards")

    monkeypatch.setattr(Path, "replace", recording_replace)
    monkeypatch.setattr(os, "chmod", no_chmod)
    monkeypatch.setattr(os, "fchmod", no_chmod)
    # Under umask 0 the mode the file is created with is the mode it has: a wider default
    # (0o666) would show here.
    with umask(0):
        store.append_step(meta.id, step(0))
    temp_info, dir_info = synced
    assert replaced_after == [1]  # the file is synced before the rename, the directory after
    assert stat.S_ISREG(temp_info.st_mode) and stat.S_IMODE(temp_info.st_mode) == 0o600
    assert os.path.samestat(dir_info, steps_dir.stat())


def test_failed_write_leaves_sessions_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    store.append_step(meta.id, step(0))

    def disk_full(fd: int) -> None:
        raise OSError("disk full")

    with monkeypatch.context() as patch:
        patch.setattr(os, "fsync", disk_full)
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


def test_steps_come_back_in_index_order_past_four_digits(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    meta = store.create(title="t", provider=ProviderInfo(name="openai", model="gpt"))
    for index in (10000, 1001, 9999):
        store.append_step(meta.id, step(index))
    # By name, 10000.json sorts before 1001.json.
    assert [s.index for s in store.get(meta.id).steps] == [1001, 9999, 10000]


def test_create_syncs_the_directories_that_gained_an_entry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    synced = record_fsyncs(monkeypatch)
    meta = SessionStore(tmp_path).create(
        title="t", provider=ProviderInfo(name="openai", model="gpt")
    )
    # A new directory is durable only once the directory holding its entry is synced.
    for parent in (tmp_path, tmp_path / "sessions", tmp_path / "sessions" / meta.id):
        assert any(os.path.samestat(s, parent.stat()) for s in synced), parent
