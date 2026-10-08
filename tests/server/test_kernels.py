from collections.abc import Iterator
from pathlib import Path

import pytest

from quarry.kernel.client import KernelDead
from quarry.server.kernels import KernelManager
from quarry.server.models import Step, now_iso


def step(i: int, code: str) -> Step:
    return Step(
        id=f"s{i}",
        index=i,
        kind="manual",
        prompt=None,
        code=code,
        status="ok",
        error=None,
        created_at=now_iso(),
    )


@pytest.fixture
def manager(tmp_path: Path) -> Iterator[KernelManager]:
    m = KernelManager(tmp_path)
    yield m
    m.close_all()


def test_get_spawns_once_and_status(manager: KernelManager) -> None:
    assert manager.status("s").status == "starting"
    assert manager.status("s").pid is None
    a = manager.get("s")
    assert manager.get("s") is a
    assert manager.status("s").status == "idle"
    assert isinstance(manager.status("s").pid, int)
    manager.mark_running("s", True)
    assert manager.status("s").status == "running"
    manager.mark_running("s", False)


def test_dead_kernel_is_detected_and_respawned(manager: KernelManager) -> None:
    a = manager.get("s")
    with pytest.raises(KernelDead):
        a.execute("import os\nos._exit(1)\n")
    assert manager.status("s").status == "dead"
    b = manager.get("s")
    assert b is not a and b.execute("x = 1").status == "ok"


def test_restart_replays_in_order_and_stops_on_failure(manager: KernelManager) -> None:
    k = manager.get("s")
    k.execute("x = 1")
    steps = [step(0, "a = 1"), step(1, "b = a + 1"), step(2, "c = zzz"), step(3, "d = 1")]
    report = manager.restart("s", steps)
    assert report.replayed == 2
    assert report.failed_step == 2
    assert report.error is not None and "NameError" in report.error
    fresh = manager.get("s")
    assert fresh is not k
    assert fresh.execute("print(b)").stdout_tail.strip() == "2"
    assert fresh.execute("print(d)").status == "error"


def test_restart_counts_replayed_steps_not_indices(manager: KernelManager) -> None:
    # Task 10 replays only ok steps, so indices can have gaps.
    report = manager.restart("s", [step(0, "a = 1"), step(2, "c = zzz")])
    assert report.replayed == 1
    assert report.failed_step == 2


def test_restart_reports_a_kernel_that_dies_during_replay(manager: KernelManager) -> None:
    report = manager.restart("s", [step(0, "a = 1"), step(1, "import os\nos._exit(1)\n")])
    assert report.replayed == 1
    assert report.failed_step == 1
    assert report.error is not None and "kernel died" in report.error
