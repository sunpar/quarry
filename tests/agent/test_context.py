from pathlib import Path

from quarry.agent.context import (
    SystemContext,
    build_summary,
    build_system,
    enabled_libraries,
    estimate_tokens,
)
from quarry.config import QuarryConfig
from quarry.data.parquet import PartitionLayout
from quarry.kernel.datasets import Column, DatasetMeta
from quarry.server.models import Step, now_iso


def test_estimate_tokens() -> None:
    assert estimate_tokens("a" * 400) == 100


def test_enabled_libraries(tmp_path: Path) -> None:
    base = enabled_libraries(QuarryConfig(root=tmp_path))
    assert "plotly" in base and "highcharts" not in base
    cfg = QuarryConfig.model_validate({"root": tmp_path, "libraries": {"highcharts_license": "k"}})
    assert "highcharts" in enabled_libraries(cfg)


def test_build_system_is_deterministic_and_filtered() -> None:
    ctx = SystemContext(
        loaders="loaders.x: x() -- d",
        layout=[PartitionLayout(dataset="prices", keys=["year"])],
        enabled_libraries=["plotly", "ag-grid"],
    )
    a = build_system(ctx)
    b = build_system(ctx)
    assert a == b
    assert "useQuery" in a and "useViewState" in a and "useDatasetSchema" in a
    assert "## plotly" in a and "## ag-grid" in a
    assert "## highcharts" not in a and "## recharts" not in a
    assert "loaders.x" in a and "prices" in a and "year" in a
    assert "failed to load" not in a


def test_build_system_lists_loaders_that_failed() -> None:
    ctx = SystemContext(loader_failures="daily: ModuleNotFoundError: no module named 'firm'")
    assert "# Loaders that failed to load" in build_system(ctx)
    assert "daily: ModuleNotFoundError" in build_system(ctx)


def step(i: int, prompt: str, code: str, writes: list[str]) -> Step:
    return Step(
        id=f"s{i}",
        index=i,
        kind="prompt",
        prompt=prompt,
        code=code,
        status="ok",
        error=None,
        writes=writes,
        created_at=now_iso(),
    )


def test_build_summary_full_when_under_budget() -> None:
    steps = [step(0, "load", "a = 1", ["a"]), step(1, "filter", "b = a", ["b"])]
    ds = [
        DatasetMeta(
            name="b",
            backing="polars",
            schema=[Column(name="x", dtype="Int64")],
            rows=3,
            preview=[],
        )
    ]
    text = build_summary(steps, ds)
    assert "load" in text and "a = 1" in text and "b = a" in text
    assert "b (polars, 3 rows): x: Int64" in text


def test_build_summary_collapses_old_steps_over_budget() -> None:
    steps = [step(i, f"prompt {i}", "x" * 4000, [f"d{i}"]) for i in range(12)]
    text = build_summary(steps, [], budget_tokens=5000, keep_full=8)
    assert "prompt 0" in text and "d0" in text
    assert text.count("x" * 4000) == 8
