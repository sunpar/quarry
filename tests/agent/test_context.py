from pathlib import Path

from quarry.agent.context import (
    SystemContext,
    _guide_for,
    build_summary,
    build_system,
    enabled_libraries,
    estimate_tokens,
    runtime_libraries,
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
    key_only = {"highcharts_license": "k"}
    cfg = QuarryConfig.model_validate({"root": tmp_path, "libraries": key_only})
    assert "highcharts" not in enabled_libraries(cfg)
    install = tmp_path / "highcharts"
    install.mkdir()
    (install / "highstock.js").write_text("// stub")
    libraries = {**key_only, "highcharts_path": str(install)}
    cfg = QuarryConfig.model_validate({"root": tmp_path, "libraries": libraries})
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
    assert "datasets: string[]" in a
    assert "@/components/ui/textarea" in a
    assert "failed to load" not in a


def test_guide_names_the_runtime_modules() -> None:
    assert "@quarry/perspective" in _guide_for(["perspective"])
    highcharts = _guide_for(["highcharts"])
    assert "@quarry/highcharts" in highcharts and "highcharts-react-official" not in highcharts


def test_build_system_renders_partitioned_and_unpartitioned_datasets() -> None:
    ctx = SystemContext(
        layout=[
            PartitionLayout(dataset="prices", keys=["year", "month"]),
            PartitionLayout(dataset="flat", keys=[]),
        ]
    )
    system = build_system(ctx)
    assert "- prices: partitioned by year, month\n- flat: not partitioned\n" in system


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


def test_runtime_libraries_reads_manifest(tmp_path: Path) -> None:
    assert runtime_libraries(tmp_path) is None
    (tmp_path / "runtime-manifest.json").write_text('{"libraries": ["ag-grid"]}')
    assert runtime_libraries(tmp_path) == ["ag-grid"]


def test_enabled_libraries_gated_by_runtime(tmp_path: Path) -> None:
    config = QuarryConfig(root=tmp_path)
    assert enabled_libraries(config, ["ag-grid", "lightweight-charts"]) == [
        "lightweight-charts",
        "ag-grid",
    ]
    assert enabled_libraries(config, None) == enabled_libraries(config)


def wide(name: str, columns: int) -> DatasetMeta:
    schema = [Column(name=f"c{i}", dtype="Int64") for i in range(columns)]
    return DatasetMeta(name=name, backing="polars", schema=schema, rows=1, preview=[])


def test_build_summary_counts_datasets_in_the_budget() -> None:
    steps = [step(i, f"prompt {i}", "x" * 400, [f"d{i}"]) for i in range(12)]
    # The steps alone fit in 2000 tokens; with the dataset's schema they do not.
    text = build_summary(steps, [wide("w", 400)], budget_tokens=2000, keep_full=8)
    assert text.count("x" * 400) == 8 and "c399: Int64" in text


def test_build_summary_drops_columns_when_datasets_alone_overflow() -> None:
    text = build_summary([], [wide("w", 400)], budget_tokens=500)
    assert "- w (polars, 1 rows): 400 columns" in text and "c399" not in text
