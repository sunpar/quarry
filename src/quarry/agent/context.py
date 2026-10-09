"""System prompt and per-step session summary for the agent."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final

from pydantic import BaseModel, Field

from quarry.config import QuarryConfig
from quarry.data.parquet import PartitionLayout
from quarry.kernel.datasets import DatasetMeta
from quarry.server.models import Step

GUIDE_PATH: Final = Path(__file__).parent / "guide.md"
ALWAYS_ON: Final[list[str]] = [
    "lightweight-charts",
    "plotly",
    "echarts",
    "recharts",
    "perspective",
    "ag-grid",
    "tanstack-table",
    "d3",
]

CONTRACT: Final = """\
You are Quarry, a data exploration agent for a quant researcher. You work in a persistent
Python kernel through the run_python tool. polars is `pl`, duckdb is `duckdb`. Every top-level
DataFrame, LazyFrame or DuckDB relation you assign becomes a named dataset the researcher can see.
Name variables well. Do computation in Python, never in view JavaScript.

After producing data, show it: call search_components and render_view for routine tables and
charts, or write_view with a TSX component when nothing in the library fits. A component's default
export is the component. It may import only these paths, and nothing else:
  react, @quarry/hooks, @/components/ui/button, @/components/ui/badge, @/components/ui/input,
  @/components/ui/select, @/components/ui/separator, @/components/ui/tabs,
  @/components/ui/tooltip, @/components/ui/textarea, @/components/ui/scroll-area,
  and the chart library packages listed below.
The hooks are exactly these, from "@quarry/hooks":

  Default export: a component receiving one prop, datasets: string[] (the names you passed,
  in order).
  useQuery(spec): {status:"loading"} | {status:"success", rows, schema, rowCount, truncated, arrow}
    | {status:"error", message}
    spec = {dataset, select?, filters?, group_by?, aggs?, pivot?, sort?, limit?, offset?, format?}
    arrow is an ArrayBuffer of Arrow IPC when spec.format is "arrow" (rows is then []), else null.
  useViewState(key, initial): [value, setValue]  (recorded; keys starting with "shared:" are linked)
  useDatasetSchema(name): Column[] | null

Push filtering, grouping and pivoting into the query spec so the researcher's manipulations can be
turned back into Python. Keep answers short; the researcher sees the data, not your prose."""

DATA_HELPERS: Final = (
    "sql(query) -> SQL Server as polars. pq(glob) -> DuckDB relation over the cache. "
    "sql_local(query) -> DuckDB over registered frames."
)


class SystemContext(BaseModel):
    loaders: str = ""
    loader_failures: str = ""
    layout: list[PartitionLayout] = Field(default_factory=list)
    enabled_libraries: list[str] = Field(default_factory=list)


def estimate_tokens(text: str) -> int:
    return len(text) // 4


def runtime_libraries(static_dir: Path) -> list[str] | None:
    """Library ids the built runtime bundle can resolve, or None when no build exists."""
    manifest = static_dir / "runtime-manifest.json"
    if not manifest.exists():
        return None
    data = json.loads(manifest.read_text())
    return [str(item) for item in data.get("libraries", [])]


def enabled_libraries(config: QuarryConfig, available: list[str] | None = None) -> list[str]:
    extra: list[str] = []
    if config.libraries.highcharts_license:
        extra.append("highcharts")
    if config.libraries.scichart_license:
        extra.append("scichart")
    wanted = [*ALWAYS_ON, *extra]
    if available is None:
        return wanted
    return [lib for lib in wanted if lib in available]


def build_system(ctx: SystemContext) -> str:
    sections = [CONTRACT, "# Chart and table libraries", _guide_for(ctx.enabled_libraries)]
    if ctx.loaders:
        sections += ["# Registered loaders (call as loaders.<name>)", ctx.loaders]
    if ctx.loader_failures:
        sections += ["# Loaders that failed to load (not callable)", ctx.loader_failures]
    if ctx.layout:
        lines = [f"- {entry.dataset}: {_partitioning(entry)}" for entry in ctx.layout]
        sections += ["# Parquet cache layout (use pq('<dataset>/**/*.parquet'))", "\n".join(lines)]
    sections += ["# Data helpers", DATA_HELPERS]
    return "\n\n".join(sections)


def build_summary(
    steps: list[Step],
    datasets: list[DatasetMeta],
    *,
    budget_tokens: int = 24000,
    keep_full: int = 8,
) -> str:
    # Datasets come first in the budget: the agent needs them to write code. Past it alone,
    # each keeps its column count, and describe_dataset lists the columns.
    ds_lines = [_dataset_line(d) for d in datasets]
    if estimate_tokens("\n".join(ds_lines)) > budget_tokens:
        ds_lines = [_dataset_line(d, columns=False) for d in datasets]
    room = budget_tokens - estimate_tokens("\n".join(ds_lines))
    blocks = [_full_block(s) for s in steps]
    if estimate_tokens("\n".join(blocks)) > room:
        cutoff = max(len(steps) - keep_full, 0)
        blocks = [_short_block(s) for s in steps[:cutoff]] + [
            _full_block(s) for s in steps[cutoff:]
        ]
    return "\n".join(["# Session so far", *blocks, "", "# Datasets in the kernel", *ds_lines])


def _partitioning(entry: PartitionLayout) -> str:
    return f"partitioned by {', '.join(entry.keys)}" if entry.keys else "not partitioned"


def _dataset_line(d: DatasetMeta, *, columns: bool = True) -> str:
    rows = d.rows if d.rows is not None else "?"
    if columns:
        detail = ", ".join(f"{c.name}: {c.dtype}" for c in d.schema_)
    else:
        detail = f"{len(d.schema_)} columns"
    return f"- {d.name} ({d.backing}, {rows} rows): {detail}"


def _full_block(s: Step) -> str:
    head = f"## Step {s.index} ({s.kind}, {s.status})"
    prompt = f"Prompt: {s.prompt}" if s.prompt else ""
    return "\n".join(x for x in [head, prompt, "```python", s.code, "```"] if x)


def _short_block(s: Step) -> str:
    head = f"## Step {s.index} ({s.kind}, {s.status})"
    return f"{head} Prompt: {s.prompt or ''} Wrote: {', '.join(s.writes) or 'nothing'}"


def _guide_for(enabled: list[str]) -> str:
    text = GUIDE_PATH.read_text(encoding="utf-8")
    sections = [f"## {part.strip()}" for part in text.split("## ")[1:]]
    wanted = {f"## {name}" for name in enabled}
    return "\n\n".join(sec for sec in sections if sec.split("\n", 1)[0] in wanted)
