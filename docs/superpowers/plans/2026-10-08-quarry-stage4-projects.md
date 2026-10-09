# Quarry Stage 4: Projects and Canvas Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let a researcher keep what a session produced. A dataset is saved into a project as a self-contained Python recipe (walked from lineage, tidied by the model, validated in a scratch kernel, optionally pinned to parquet). A view is saved as its TSX plus state and the datasets it needs. Saved items recall into any session as real steps. Each project has a canvas: a snap-to-grid dashboard of saved views, draggable and resizable, whose cards cross-filter through `shared:` view-state keys.

**Architecture:** `quarry.projects` is a new package: on-disk project store (spec section 5 layout), a pure recipe walk over a session's steps, a tidy call through the existing `Provider` interface, and validation in a throwaway `KernelClient`. `quarry.server` gains a `ProjectService` that composes those with the session service (which lends its kernel while idle), plus project routes and a `recall` route that creates `recall` steps through the manual-run path so restart replays them. The host app gains a project browser in the rail, save dialogs, a snapshot scrubber, a `ViewHost` component shared by step views and canvas cards, a canvas page on `react-grid-layout`, and a host-side hub that fans `shared:` keys out across canvas cards. Export, CLI project commands, to-code and the remaining built-ins are Stage 5 and must not be pulled in here.

**Tech Stack:** Python 3.11+, pydantic 2, FastAPI, the Stage 1 kernel client and Stage 2 server as built on branch `claude/quarry-stage2-server-agent-66853b`; the Stage 3 web app as planned in `2026-10-08-quarry-stage3-first-ui.md` (React 19, TypeScript strict, React Query v5, shadcn 4 on Tailwind 4, vitest 5, Playwright through `pytest-playwright`); `react-grid-layout` 2.3 (ships its own types; do not install `@types/react-grid-layout`, which is for v1) and `react-resizable` 3.x for its handle CSS.

**Spec:** `docs/superpowers/specs/2026-10-08-quarry-design.md` (sections 5 Project and Step kinds, 6 lineage capture, 9 hooks and host app, 10 Projects, 11 persistence, 13 save validation failure, 14 testing Projects, 15 stage 4). Open items filed for Stage 4 in `docs/open-items.md` are addressed or explicitly deferred in the "Open items" section at the end.

## Global Constraints

- All Stage 1, 2 and 3 Global Constraints still apply (typed Python, ruff, mypy strict; TypeScript strict, no `any`, `interface` for props, files under 250 lines, prettier; bare Conventional Commit types, no attribution trailers).
- Stage 3 is unbuilt at the time of writing. Every "Consumes" line that names Stage 3 code (`ViewFrameContainer`, `HostBridge`, `ApiClient`, `keys`, `StepCard`, `SessionRail`, `App`) refers to the Stage 3 plan. Before Task 7, re-read the real Stage 3 branch; where it differs, code wins and this plan's TypeScript is adjusted, not the other way round.
- The Stage 2 branch's `Step` carries `runs: list[CodeRun]` and restart replays `runs`, not `code`. Every step Stage 4 creates fills `runs`.
- Project layout is exactly spec section 5: `projects/<slug>/project.json`, `datasets/<name>/{recipe.py,recipe.raw.py,meta.json,data.parquet}`, `views/<name>/{view.tsx,state.json,meta.json}`. Everything is plain text except the parquet file; writes are atomic through temp-and-replace.
- A dataset is saved while its session is idle. Saving takes the session busy exactly like restart does; a running step makes the save return 409, never wait.
- Validation compares the scratch kernel's `describe(name)` with the session kernel's `describe(name)` taken at save time: same column names and dtypes in the same order, same row count. `step.datasets` metas are not used for this; their `rows` can be `None`.
- A tidy failure (provider error, empty reply, non-parsing code) never fails a save: the raw concatenation is validated instead. A validation failure never fails a save either: `recipe.py` is the raw concatenation and `validated` is false, with the reason in `validation_error`.
- Recall code for a pinned dataset is generated at recall time from the absolute parquet path and is never stored. Recall into a session that already binds the name overwrites it; the UI says so before recalling.
- The canvas binds to the active session. Cards query through that session's kernel; a card whose datasets are absent shows a placeholder with "Load", which recalls the view (datasets then mount) as a step. There is no hidden project kernel.
- Only layout lives in `project.json`. A card's state during a visit is ephemeral; "Save view" again freezes a new state. `state.json` is the state at save time.
- Linked keys: the host fans out `shared:` keys only on the canvas, by sending `restore` with each other card's last known state merged with the shared values. No seeding on load; the first change wins. Inside a session, `shared:` keys stay private to their view.

## Review Focus

1. Tidy returns code that changes behaviour (drops a filter). Expected: validation fails on row count, `recipe.py` holds the raw concatenation, `validated` is false, the UI shows "unvalidated" with the reason. Pinned in Task 5 and Task 6.
2. The lineage includes a step with status `error` whose first run succeeded and wrote the dataset. Expected: that step's `ok` runs are in the recipe, the failed run is not. Pinned in Task 2.
3. Save dataset while a step is running. Expected: 409 immediately, nothing written, the step continues. Pinned in Task 6.
4. Recall a dataset into a session that already holds the name. Expected: the recall step runs, the name now refers to the recalled data, lineage records the write, and the UI warned first. Pinned in Task 7 and Task 9.
5. Two cards saved with different values for the same `shared:` key, canvas opened, one card changes the key. Expected: the other card receives `restore` with the new value merged into its own state; nothing fires before the first change. Pinned in Task 11.

---

### Task 1: Project models and store

**Files:**

- Create: `src/quarry/projects/__init__.py`, `src/quarry/projects/models.py`, `src/quarry/projects/store.py`
- Test: `tests/projects/__init__.py`, `tests/projects/test_store.py`

**Interfaces:**

- Produces: `CanvasCard {view, x, y, w, h}`, `ProjectMeta {slug, name, description, created_at, updated_at, canvas}`, `SavedDatasetMeta {name, description, backing, schema, rows, mode, saved_at, source_session, source_step, validated, validation_error}`, `SavedViewMeta {name, description, datasets, component_id, saved_at, source_session, source_step}`, `Project {meta, datasets, views}`, `SaveMode = Literal["live", "pinned"]`; `ProjectStore(root)` with `create`, `list`, `get`, `meta`, `set_canvas`, `write_dataset`, `read_recipe`, `parquet_path`, `write_view`, `read_view`; `slugify(name)`; `NAME_RE` for view names.
- Consumes: `_write_atomic` from `quarry.server.store` (move it to `quarry/projects/files.py` as `write_atomic` and import it from both places), `Column`, `Backing`, `Json`.

- [ ] **Step 1: Failing tests**

`tests/projects/test_store.py`:

```python
import json
from pathlib import Path

import pytest

from quarry.kernel.datasets import Column
from quarry.projects.models import CanvasCard, SavedDatasetMeta, SavedViewMeta
from quarry.projects.store import ProjectStore, slugify


def dataset_meta(name: str = "prices") -> SavedDatasetMeta:
    return SavedDatasetMeta(
        name=name,
        description="daily closes",
        backing="polars",
        schema=[Column(name="ts", dtype="Date"), Column(name="px", dtype="Float64")],
        rows=3,
        mode="live",
        saved_at="2026-10-08T00:00:00+00:00",
        source_session="s1",
        source_step="st1",
        validated=True,
    )


def view_meta(name: str = "closes") -> SavedViewMeta:
    return SavedViewMeta(
        name=name,
        description="",
        datasets=["prices"],
        component_id="time-series",
        saved_at="2026-10-08T00:00:00+00:00",
        source_session="s1",
        source_step="st2",
    )


def test_slugify() -> None:
    assert slugify("Momentum Study 2024") == "momentum-study-2024"
    assert slugify("  --  ") == "project"


def test_create_list_get_dedupes_slug(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    a = store.create("Momentum", description="first")
    b = store.create("momentum")
    assert (a.slug, b.slug) == ("momentum", "momentum-2")
    assert [m.slug for m in store.list()] == ["momentum", "momentum-2"]
    project = store.get("momentum")
    assert project.meta.description == "first"
    assert project.datasets == [] and project.views == []
    with pytest.raises(KeyError):
        store.get("missing")


def test_write_and_read_dataset(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    store.create("p")
    store.write_dataset("p", dataset_meta(), recipe="prices = load()\n", raw="x = 1\nprices = load()\n")
    base = tmp_path / "projects" / "p" / "datasets" / "prices"
    assert (base / "recipe.py").read_text() == "prices = load()\n"
    assert (base / "recipe.raw.py").read_text() == "x = 1\nprices = load()\n"
    meta = json.loads((base / "meta.json").read_text())
    assert meta["schema"][0] == {"name": "ts", "dtype": "Date"}
    assert store.read_recipe("p", "prices") == "prices = load()\n"
    assert store.parquet_path("p", "prices") == base / "data.parquet"
    assert [d.name for d in store.get("p").datasets] == ["prices"]
    assert store.get("p").meta.updated_at >= store.get("p").meta.created_at


def test_write_and_read_view(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    store.create("p")
    store.write_view("p", view_meta(), source="export default () => null", state={"k": 1})
    meta, source, state = store.read_view("p", "closes")
    assert meta.component_id == "time-series"
    assert source == "export default () => null"
    assert state == {"k": 1}
    with pytest.raises(KeyError):
        store.read_view("p", "nope")
    with pytest.raises(ValueError):
        store.write_view("p", view_meta("Bad Name!"), source="", state={})


def test_set_canvas(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    store.create("p")
    cards = [CanvasCard(view="closes", x=0, y=0, w=6, h=8)]
    assert store.set_canvas("p", cards).canvas == cards
    assert store.meta("p").canvas == cards
```

Run: `uv run pytest tests/projects -q` — fails on imports.

- [ ] **Step 2: Models**

`src/quarry/projects/models.py`:

```python
"""Project records as persisted on disk (spec section 5, Project)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quarry.kernel.datasets import Column
from quarry.query.spec import Backing

SaveMode = Literal["live", "pinned"]


class CanvasCard(BaseModel):
    view: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)


class ProjectMeta(BaseModel):
    slug: str
    name: str
    description: str = ""
    created_at: str
    updated_at: str
    canvas: list[CanvasCard] = Field(default_factory=list)


class SavedDatasetMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    backing: Backing
    schema_: list[Column] = Field(alias="schema")
    rows: int | None
    mode: SaveMode
    saved_at: str
    source_session: str
    source_step: str
    validated: bool
    validation_error: str | None = None


class SavedViewMeta(BaseModel):
    name: str
    description: str = ""
    datasets: list[str]
    component_id: str
    saved_at: str
    source_session: str
    source_step: str


class Project(BaseModel):
    meta: ProjectMeta
    datasets: list[SavedDatasetMeta]
    views: list[SavedViewMeta]
```

- [ ] **Step 3: Atomic write helper**

Create `src/quarry/projects/files.py`:

```python
"""Atomic text writes shared by the session and project stores."""

from __future__ import annotations

from pathlib import Path


def write_atomic(path: Path, text: str) -> None:
    # A crash leaves at most a stray temp file, which no *.json or *.py glob matches.
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(f".{path.name}.tmp")
    temp.write_text(text)
    temp.replace(path)
```

In `src/quarry/server/store.py`, delete the private `_write_atomic` and `from quarry.projects.files import write_atomic`; rename the two call sites.

- [ ] **Step 4: Store**

`src/quarry/projects/store.py`:

```python
"""Projects on disk: one directory per project, datasets and views as subdirectories."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

from quarry.projects.files import write_atomic
from quarry.projects.models import CanvasCard, Project, ProjectMeta, SavedDatasetMeta, SavedViewMeta
from quarry.query.spec import Json

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")


def now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


class ProjectStore:
    def __init__(self, root: Path) -> None:
        self._dir = root / "projects"

    def create(self, name: str, description: str = "") -> ProjectMeta:
        base = slugify(name)
        slug, n = base, 1
        while (self._dir / slug).exists():
            n += 1
            slug = f"{base}-{n}"
        now = now_iso()
        meta = ProjectMeta(slug=slug, name=name, description=description, created_at=now, updated_at=now)
        self._write_meta(meta)
        return meta

    def list(self) -> list[ProjectMeta]:
        if not self._dir.is_dir():
            return []
        metas = [self._read_meta(p.name) for p in self._dir.iterdir() if (p / "project.json").exists()]
        return sorted(metas, key=lambda m: m.name.lower())

    def meta(self, slug: str) -> ProjectMeta:
        return self._read_meta(slug)

    def get(self, slug: str) -> Project:
        meta = self._read_meta(slug)
        datasets = [
            SavedDatasetMeta.model_validate_json((p / "meta.json").read_text())
            for p in sorted((self._project_dir(slug) / "datasets").glob("*/"))
            if (p / "meta.json").exists()
        ]
        views = [
            SavedViewMeta.model_validate_json((p / "meta.json").read_text())
            for p in sorted((self._project_dir(slug) / "views").glob("*/"))
            if (p / "meta.json").exists()
        ]
        return Project(meta=meta, datasets=datasets, views=views)

    def set_canvas(self, slug: str, cards: list[CanvasCard]) -> ProjectMeta:
        meta = self._read_meta(slug).model_copy(update={"canvas": cards})
        self._write_meta(meta)
        return meta

    def write_dataset(self, slug: str, meta: SavedDatasetMeta, *, recipe: str, raw: str) -> None:
        base = self._dataset_dir(slug, meta.name)
        write_atomic(base / "recipe.raw.py", raw)
        write_atomic(base / "recipe.py", recipe)
        write_atomic(base / "meta.json", meta.model_dump_json(by_alias=True, indent=2))
        self._touch(slug)

    def read_recipe(self, slug: str, name: str) -> str:
        path = self._dataset_dir(slug, name) / "recipe.py"
        if not path.exists():
            raise KeyError(name)
        return path.read_text()

    def parquet_path(self, slug: str, name: str) -> Path:
        return self._dataset_dir(slug, name) / "data.parquet"

    def write_view(self, slug: str, meta: SavedViewMeta, *, source: str, state: dict[str, Json]) -> None:
        if NAME_RE.match(meta.name) is None:
            raise ValueError("view names are lowercase letters, digits, '-' and '_', up to 64 chars")
        base = self._project_dir(slug) / "views" / meta.name
        write_atomic(base / "view.tsx", source)
        write_atomic(base / "state.json", json.dumps(state, indent=2))
        write_atomic(base / "meta.json", meta.model_dump_json(indent=2))
        self._touch(slug)

    def read_view(self, slug: str, name: str) -> tuple[SavedViewMeta, str, dict[str, Json]]:
        base = self._project_dir(slug) / "views" / name
        if not (base / "meta.json").exists():
            raise KeyError(name)
        meta = SavedViewMeta.model_validate_json((base / "meta.json").read_text())
        state: dict[str, Json] = json.loads((base / "state.json").read_text())
        return meta, (base / "view.tsx").read_text(), state

    def _dataset_dir(self, slug: str, name: str) -> Path:
        if not name.isidentifier():
            raise ValueError(f"{name!r} is not a dataset name")
        return self._project_dir(slug) / "datasets" / name

    def _project_dir(self, slug: str) -> Path:
        path = self._dir / slug
        if not (path / "project.json").exists():
            raise KeyError(slug)
        return path

    def _read_meta(self, slug: str) -> ProjectMeta:
        return ProjectMeta.model_validate_json((self._project_dir(slug) / "project.json").read_text())

    def _write_meta(self, meta: ProjectMeta) -> None:
        write_atomic(self._dir / meta.slug / "project.json", meta.model_dump_json(indent=2))

    def _touch(self, slug: str) -> None:
        self._write_meta(self._read_meta(slug).model_copy(update={"updated_at": now_iso()}))
```

`_write_meta` for a new project must not go through `_project_dir` (which requires the file to exist); it builds the path directly, as written.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/projects tests/server/test_store.py -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: add project models and on-disk project store"
```

---

### Task 2: Recipe walk over session lineage

**Files:**

- Create: `src/quarry/projects/recipe.py`
- Test: `tests/projects/test_recipe.py`

**Interfaces:**

- Produces: `recipe_steps(steps: list[Step], dataset: str) -> list[Step]` (the dependency closure in index order; `KeyError` when no step wrote the dataset) and `raw_recipe(steps: list[Step]) -> str` (the `ok` runs of those steps, each step under a `# step N: <prompt or kind>` comment).
- Consumes: `Step {index, kind, prompt, status, reads, writes, defines, runs}` and `CodeRun {code, status}` from the Stage 2 branch.

- [ ] **Step 1: Failing tests**

`tests/projects/test_recipe.py`:

```python
import pytest

from quarry.agent.tools import CodeRun
from quarry.projects.recipe import raw_recipe, recipe_steps
from quarry.server.models import Step, StepStatus


def step(
    index: int,
    code: str,
    *,
    reads: list[str] = [],
    writes: list[str] = [],
    defines: list[str] = [],
    status: StepStatus = "ok",
    runs: list[CodeRun] | None = None,
    prompt: str | None = None,
) -> Step:
    return Step(
        id=f"st{index}",
        index=index,
        kind="prompt" if prompt else "manual",
        prompt=prompt,
        code=code,
        runs=runs if runs is not None else [CodeRun(code=code, status=status)],
        status=status,
        error=None,
        reads=reads,
        writes=writes,
        defines=defines,
        created_at="2026-10-08T00:00:00+00:00",
    )


def test_walks_reads_and_helpers_in_index_order() -> None:
    steps = [
        step(0, "def clean(df): return df", defines=["clean"], prompt="helper"),
        step(1, "raw = pq('x')", writes=["raw"]),
        step(2, "other = pq('y')", writes=["other"]),
        step(3, "prices = clean(raw)", reads=["clean", "raw"], writes=["prices"]),
        step(4, "later = prices.head()", reads=["prices"], writes=["later"]),
    ]
    assert [s.index for s in recipe_steps(steps, "prices")] == [0, 1, 3]
    assert raw_recipe(recipe_steps(steps, "prices")) == (
        "# step 1: helper\ndef clean(df): return df\n\n"
        "# step 2: manual\nraw = pq('x')\n\n"
        "# step 4: manual\nprices = clean(raw)\n"
    )


def test_latest_writer_before_the_consumer_wins() -> None:
    steps = [
        step(0, "df = a()", writes=["df"]),
        step(1, "out = df.x()", reads=["df"], writes=["out"]),
        step(2, "df = b()", writes=["df"]),
    ]
    assert [s.index for s in recipe_steps(steps, "out")] == [0, 1]


def test_self_rebinding_keeps_the_earlier_writer() -> None:
    steps = [
        step(0, "df = a()", writes=["df"]),
        step(1, "df = df.filter()", reads=["df"], writes=["df"]),
    ]
    assert [s.index for s in recipe_steps(steps, "df")] == [0, 1]


def test_only_ok_runs_of_a_failed_step_are_kept() -> None:
    failed = step(
        1,
        "prices = pq('p')\nprices = prices.bad()",
        writes=["prices"],
        status="error",
        runs=[CodeRun(code="prices = pq('p')", status="ok"), CodeRun(code="prices = prices.bad()", status="error")],
    )
    text = raw_recipe(recipe_steps([failed], "prices"))
    assert "prices = pq('p')" in text
    assert "bad()" not in text


def test_unknown_dataset_and_unproduced_reads() -> None:
    steps = [step(0, "df = loaders.x()", reads=["loaders"], writes=["df"])]
    assert [s.index for s in recipe_steps(steps, "df")] == [0]
    with pytest.raises(KeyError):
        recipe_steps(steps, "nope")
```

- [ ] **Step 2: Implement**

`src/quarry/projects/recipe.py`:

```python
"""Walk a session's lineage backward from a dataset and concatenate the code that made it."""

from __future__ import annotations

from quarry.server.models import Step


def recipe_steps(steps: list[Step], dataset: str) -> list[Step]:
    """Every step the dataset depends on, in index order; KeyError if nothing wrote it."""
    ordered = sorted((s for s in steps if s.status != "running"), key=lambda s: s.index)
    root = _producer(ordered, dataset, before=len(ordered))
    if root is None:
        raise KeyError(dataset)
    chosen: dict[int, Step] = {}
    pending = [root]
    while pending:
        step = pending.pop()
        if step.index in chosen:
            continue
        chosen[step.index] = step
        position = ordered.index(step)
        for name in step.reads:
            producer = _producer(ordered, name, before=position)
            if producer is not None and producer.index not in chosen:
                pending.append(producer)
    return [chosen[i] for i in sorted(chosen)]


def raw_recipe(steps: list[Step]) -> str:
    blocks: list[str] = []
    for step in steps:
        code = "\n".join(run.code.rstrip("\n") for run in step.runs if run.status == "ok")
        if code == "":
            continue
        label = step.prompt if step.prompt else step.kind
        blocks.append(f"# step {step.index + 1}: {label}\n{code}\n")
    return "\n".join(blocks)


def _producer(ordered: list[Step], name: str, *, before: int) -> Step | None:
    """The latest step before position `before` that wrote or defined `name`."""
    for step in reversed(ordered[:before]):
        if name in step.writes or name in step.defines:
            return step
    return None
```

A prompt label can be multi-line; `raw_recipe` must keep the comment valid, so replace newlines: `label = (step.prompt or step.kind).replace("\n", " ")`.

- [ ] **Step 3: Verify and commit**

```bash
uv run pytest tests/projects -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: walk session lineage into a raw dataset recipe"
```

---

### Task 3: Tidy through the provider

**Files:**

- Create: `src/quarry/projects/tidy.py`
- Modify: `src/quarry/agent/anthropic_provider.py` (omit `tools` when empty)
- Test: `tests/projects/test_tidy.py`, `tests/agent/test_anthropic_provider.py` (one case)

**Interfaces:**

- Produces: `TIDY_SYSTEM: Final[str]`, `tidy_recipe(provider: Provider, raw: str, dataset: str) -> str | None` (`None` when the provider fails, replies empty, or the reply does not parse), `strip_fences(text) -> str`.
- Consumes: `Provider.complete(*, system, messages, tools)`, `Message`, `ProviderError`.

- [ ] **Step 1: Failing tests**

`tests/projects/test_tidy.py`:

````python
from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, Message, ProviderError, ToolDef
from quarry.projects.tidy import TIDY_SYSTEM, strip_fences, tidy_recipe


def end(text: str) -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], stop="end")


def test_strip_fences() -> None:
    assert strip_fences("```python\nx = 1\n```") == "x = 1\n"
    assert strip_fences("x = 1") == "x = 1\n"


def test_tidy_sends_raw_and_returns_code() -> None:
    provider = FakeProvider([end("```python\nimport polars as pl\nprices = pl.DataFrame()\n```")])
    out = tidy_recipe(provider, "x = 1\nprices = pl.DataFrame()\n", "prices")
    assert out == "import polars as pl\nprices = pl.DataFrame()\n"
    system, messages, tools = provider.calls[0]
    assert system == TIDY_SYSTEM
    assert tools == []
    assert messages[-1].role == "user" and "prices" in messages[-1].text


def test_tidy_returns_none_on_failure_or_garbage() -> None:
    class Failing:
        def complete(self, *, system: str, messages: list[Message], tools: list[ToolDef]) -> AssistantTurn:
            raise ProviderError("down", retryable=False)

    assert tidy_recipe(Failing(), "x = 1", "x") is None
    assert tidy_recipe(FakeProvider([end("")]), "x = 1", "x") is None
    assert tidy_recipe(FakeProvider([end("def (")]), "x = 1", "x") is None
    assert tidy_recipe(FakeProvider([end("y = 2")]), "x = 1", "x") is None
````

The last case: a reply that never binds the dataset name is rejected before validation spends a kernel on it.

Add to `tests/agent/test_anthropic_provider.py`, next to the existing request-shape test (follow its fake `create` pattern):

```python
def test_empty_tools_are_omitted() -> None:
    seen: dict[str, object] = {}

    def create(**kwargs: object) -> object:
        seen.update(kwargs)
        return SimpleNamespace(content=[SimpleNamespace(type="text", text="ok")], stop_reason="end_turn")

    provider = AnthropicProvider(model="m", create=create)
    provider.complete(system="s", messages=[Message(role="user", text="hi")], tools=[])
    assert "tools" not in seen
```

`SimpleNamespace` comes from `types`; match the fake response shape the existing tests in that file use, including how they build the provider.

- [ ] **Step 2: Implement**

`src/quarry/projects/tidy.py`:

````python
"""One provider call that turns a raw step concatenation into a self-contained recipe."""

from __future__ import annotations

import ast
import re
from typing import Final

from quarry.agent.types import Message, Provider, ProviderError

TIDY_SYSTEM: Final = """\
You tidy Python recipes for a quant researcher. You receive a script that concatenates the
notebook steps which produced one dataset, and that dataset's name. Return one self-contained
Python script that produces exactly the same dataset bound to that name.

Rules: remove loads, assignments, prints and plotting the dataset does not depend on; keep
every loader call, filter, join, aggregation and column expression unchanged in meaning; keep
the imports and helper functions the dataset needs; keep the data helpers sql, pq, sql_local
and loaders as they are; end with the dataset bound to its name. Reply with Python code only,
no fences and no prose."""

_FENCE = re.compile(r"^```[a-zA-Z]*\n(.*?)\n?```\s*$", re.DOTALL)


def strip_fences(text: str) -> str:
    match = _FENCE.match(text.strip())
    body = match.group(1) if match else text.strip()
    return body.rstrip("\n") + "\n"


def tidy_recipe(provider: Provider, raw: str, dataset: str) -> str | None:
    prompt = f"Dataset name: {dataset}\n\nScript:\n{raw}"
    try:
        turn = provider.complete(
            system=TIDY_SYSTEM, messages=[Message(role="user", text=prompt)], tools=[]
        )
    except ProviderError:
        return None
    code = strip_fences(turn.text)
    if code.strip() == "" or not _binds(code, dataset):
        return None
    return code


def _binds(code: str, name: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == name:
            return True
    return False
````

In `anthropic_provider.py`, build the kwargs so `tools` is only present when non-empty:

```python
            kwargs: dict[str, Any] = {}
            if tools:
                kwargs["tools"] = to_api_tools(tools)
            response = self._create(
                model=self._model,
                max_tokens=MAX_TOKENS,
                system=[{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
                messages=to_api_messages(messages),
                output_config={"effort": EFFORT},
                betas=[FALLBACK_BETA],
                fallbacks="default",
                **kwargs,
            )
```

(`from typing import Any` with the existing `ANN401` ignore; or type it as `dict[str, list[dict[str, Json]]]`, which is exact.)

- [ ] **Step 3: Verify and commit**

```bash
uv run pytest tests/projects tests/agent/test_anthropic_provider.py -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: tidy raw recipes through the provider"
```

---

### Task 4: Validation in a scratch kernel

**Files:**

- Create: `src/quarry/projects/validate.py`
- Test: `tests/projects/test_validate.py`

**Interfaces:**

- Produces: `Validation {ok: bool, error: str | None, meta: DatasetMeta | None}`, `validate_recipe(root: Path, recipe: str, name: str, expected: DatasetMeta, *, threads: int = 0) -> Validation`.
- Consumes: `KernelClient.spawn(root, threads=)`, `execute`, `describe`, `shutdown`, `close`, `KernelDead`, `RpcFailure`; `DatasetMeta.schema_` (alias `schema`) and `rows`.

- [ ] **Step 1: Failing tests**

`tests/projects/test_validate.py` (real kernel; the Stage 1 tests already spawn kernels this way, follow their `root` fixture if one exists):

```python
from pathlib import Path

from quarry.kernel.client import KernelClient
from quarry.kernel.datasets import DatasetMeta
from quarry.projects.validate import validate_recipe

RECIPE = "import polars as pl\nprices = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03'], 'px': [1.0, 2.0]})\n"


def expected_for(root: Path, code: str) -> DatasetMeta:
    kernel = KernelClient.spawn(root)
    try:
        kernel.execute(code)
        return kernel.describe("prices")
    finally:
        kernel.shutdown()
        kernel.close()


def test_matching_recipe_validates(tmp_path: Path) -> None:
    expected = expected_for(tmp_path, RECIPE)
    result = validate_recipe(tmp_path, RECIPE, "prices", expected)
    assert result.ok and result.error is None
    assert result.meta is not None and result.meta.rows == 2


def test_row_count_mismatch_fails(tmp_path: Path) -> None:
    expected = expected_for(tmp_path, RECIPE)
    fewer = "import polars as pl\nprices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})\n"
    result = validate_recipe(tmp_path, fewer, "prices", expected)
    assert not result.ok and result.error is not None and "rows" in result.error


def test_schema_mismatch_and_errors_fail(tmp_path: Path) -> None:
    expected = expected_for(tmp_path, RECIPE)
    renamed = RECIPE.replace("'px'", "'close'")
    assert "close" in (validate_recipe(tmp_path, renamed, "prices", expected).error or "")
    broken = "prices = undefined_name()\n"
    assert "NameError" in (validate_recipe(tmp_path, broken, "prices", expected).error or "")
    unbound = "x = 1\n"
    assert "prices" in (validate_recipe(tmp_path, unbound, "prices", expected).error or "")
```

- [ ] **Step 2: Implement**

`src/quarry/projects/validate.py`:

```python
"""Run a recipe in a throwaway kernel and compare what it produces with the live dataset."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel

from quarry.kernel.client import KernelClient, KernelDead, RpcFailure
from quarry.kernel.datasets import DatasetMeta


class Validation(BaseModel):
    ok: bool
    error: str | None
    meta: DatasetMeta | None


def validate_recipe(
    root: Path, recipe: str, name: str, expected: DatasetMeta, *, threads: int = 0
) -> Validation:
    try:
        kernel = KernelClient.spawn(root, threads=threads)
    except KernelDead as exc:
        return Validation(ok=False, error=f"scratch kernel failed to start: {exc}", meta=None)
    try:
        result = kernel.execute(recipe)
        if result.status != "ok":
            detail = result.error.traceback if result.error else result.status
            return Validation(ok=False, error=f"recipe failed: {detail}", meta=None)
        try:
            actual = kernel.describe(name)
        except RpcFailure as exc:
            return Validation(ok=False, error=f"recipe did not produce {name}: {exc}", meta=None)
    except KernelDead as exc:
        return Validation(ok=False, error=f"scratch kernel died: {exc}", meta=None)
    finally:
        kernel.shutdown()
        kernel.close()
    problem = _compare(expected, actual)
    return Validation(ok=problem is None, error=problem, meta=actual)


def _compare(expected: DatasetMeta, actual: DatasetMeta) -> str | None:
    want = [(c.name, c.dtype) for c in expected.schema_]
    got = [(c.name, c.dtype) for c in actual.schema_]
    if want != got:
        return f"schema differs: expected {want}, recipe produced {got}"
    if expected.rows is not None and actual.rows is not None and expected.rows != actual.rows:
        return f"rows differ: expected {expected.rows}, recipe produced {actual.rows}"
    return None
```

`shutdown()` then `close()` is the order the Stage 1 client expects; an open item notes `close()` may cut a clean exit short, which does not matter for a scratch kernel.

- [ ] **Step 3: Verify and commit**

```bash
uv run pytest tests/projects -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: validate recipes in a scratch kernel"
```

---

### Task 5: Project service: save dataset and save view

**Files:**

- Create: `src/quarry/server/projects.py`
- Modify: `src/quarry/server/service.py` (`hold` context manager)
- Test: `tests/server/test_projects_service.py`

**Interfaces:**

- Produces: `SaveDatasetRequest {session_id, dataset, mode, description=""}`, `SaveViewRequest {session_id, step_id, name, description="", mode}`, `ProjectService(config, store, sessions, provider_factory)` with `create(name, description)`, `list()`, `get(slug)`, `save_dataset(slug, req) -> SavedDatasetMeta`, `save_view(slug, req) -> SavedViewMeta`, `set_canvas(slug, cards) -> ProjectMeta`; `StepNotFound` reused from Stage 3's service additions (define it here if Stage 3 has not landed, in `service.py`, and import).
- Produces on `SessionService`: `hold(session_id)` context manager yielding the session's `KernelClient` while marking the session busy; raises `SessionBusy` when a step or replay is running.
- Consumes: Tasks 1 to 4; `SessionService.get`, `_running`, `_lock`, `_kernels`.

- [ ] **Step 1: Failing tests**

`tests/server/test_projects_service.py`:

```python
import time
from collections.abc import Callable
from pathlib import Path

import pytest

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, ToolCall
from quarry.components.library import ComponentLibrary, builtin_root
from quarry.config import QuarryConfig
from quarry.agent.transpile import NoopTranspiler
from quarry.projects.store import ProjectStore
from quarry.server.kernels import KernelManager
from quarry.server.projects import ProjectService, SaveDatasetRequest, SaveViewRequest
from quarry.server.service import SessionBusy, SessionService
from quarry.server.store import SessionStore

PRICES = "prices = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03'], 'px': [1.0, 2.0]})"
TIDY_OK = "import polars as pl\n" + PRICES + "\n"
TIDY_BAD = "import polars as pl\nprices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})\n"


def py(call_id: str, code: str) -> AssistantTurn:
    return AssistantTurn(
        text="", tool_calls=[ToolCall(id=call_id, name="run_python", input={"code": code})], stop="tool_use"
    )


def render(call_id: str) -> AssistantTurn:
    call = ToolCall(
        id=call_id, name="render_view",
        input={"component_id": "data-table", "datasets": ["prices"], "initial_state": '{"limit": 5}'},
    )
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def end(text: str = "done") -> AssistantTurn:
    return AssistantTurn(text=text, tool_calls=[], stop="end")


def build(tmp_path: Path, provider: FakeProvider) -> tuple[SessionService, ProjectService]:
    config = QuarryConfig(root=tmp_path)
    sessions = SessionService(
        config=config, store=SessionStore(tmp_path), kernels=KernelManager(tmp_path),
        provider_factory=lambda _cfg: provider, library=ComponentLibrary([builtin_root()]),
        transpiler=NoopTranspiler(),
    )
    projects = ProjectService(
        config=config, store=ProjectStore(tmp_path), sessions=sessions, provider_factory=lambda _cfg: provider
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
    meta = projects.save_dataset(slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="live"))
    assert meta.validated and meta.rows == 2 and meta.mode == "live"
    base = tmp_path / "projects" / slug / "datasets" / "prices"
    assert (base / "recipe.py").read_text() == TIDY_OK
    assert "# step 1: load prices" in (base / "recipe.raw.py").read_text()
    assert not (base / "data.parquet").exists()
    sessions.shutdown()


def test_bad_tidy_falls_back_to_raw_unvalidated(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", PRICES), end(), end(TIDY_BAD)])
    sessions, projects = build(tmp_path, provider)
    sid, _ = run_prices(sessions)
    slug = projects.create("p", "").slug
    meta = projects.save_dataset(slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="pinned"))
    assert not meta.validated
    assert meta.validation_error is not None and "rows" in meta.validation_error
    base = tmp_path / "projects" / slug / "datasets" / "prices"
    assert (base / "recipe.py").read_text() == (base / "recipe.raw.py").read_text()
    assert (base / "data.parquet").exists()
    sessions.shutdown()


def test_save_rejected_while_step_runs(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", "import time; time.sleep(3)"), end(), end(TIDY_OK)])
    sessions, projects = build(tmp_path, provider)
    sid = sessions.create("t").id
    sessions.start_prompt(sid, "slow")
    slug = projects.create("p", "").slug
    with pytest.raises(SessionBusy):
        projects.save_dataset(slug, SaveDatasetRequest(session_id=sid, dataset="prices", mode="live"))
    sessions.interrupt(sid)
    wait_idle(sessions, sid)
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
    _, source, state = ProjectStore(tmp_path).read_view(slug, "table")
    assert "export default" in source and state == {"limit": 5}
    sessions.shutdown()
```

- [ ] **Step 2: `hold` on the session service**

In `service.py` add `from contextlib import contextmanager` and `from collections.abc import Iterator`, then:

```python
    @contextmanager
    def _busy(self, session_id: str) -> Iterator[None]:
        """Mark the session busy with no running step; SessionBusy if it already is."""
        with self._lock:
            if session_id in self._running:
                raise SessionBusy(session_id)
            self._running[session_id] = None
            self._kernels.mark_running(session_id, True)
        try:
            yield
        finally:
            with self._lock:
                self._kernels.mark_running(session_id, False)
                self._running.pop(session_id, None)

    @contextmanager
    def hold(self, session_id: str) -> Iterator[KernelClient]:
        """Lend the idle session kernel to the caller; the session is busy meanwhile."""
        with self._busy(session_id):
            yield self._kernels.get(session_id)

    def restart(self, session_id: str) -> ReplayReport:
        with self._busy(session_id):
            return self._kernels.restart(session_id, self._store.get(session_id).steps)
```

`restart` keeps calling `self._kernels.restart` directly rather than `hold`, because `hold` goes through `_kernels.get`, which raises `KernelDead` for the dead kernel a restart exists to replace. Delete the old `restart` body; `_busy` is the one copy of the busy dance.

While a session is held, `status().running_step` is `None` (the busy marker is `None`), so the prompt box stays enabled during a save and a prompt submitted meanwhile gets 409 "a step is already running", which the Stage 3 host shows as the submit error. That is acceptable for Stage 4 and is recorded as a decision; a busy flag in `SessionStatus` is the Stage 5 fix if it confuses anyone.

- [ ] **Step 3: Project service**

`src/quarry/server/projects.py`:

```python
"""Save datasets and views into projects, and lay out their canvases."""

from __future__ import annotations

from pydantic import BaseModel

from quarry.config import QuarryConfig
from quarry.kernel.client import RpcFailure
from quarry.projects.models import CanvasCard, Project, ProjectMeta, SavedDatasetMeta, SavedViewMeta, SaveMode
from quarry.projects.recipe import raw_recipe, recipe_steps
from quarry.projects.store import NAME_RE, ProjectStore, now_iso
from quarry.projects.tidy import tidy_recipe
from quarry.projects.validate import validate_recipe
from quarry.query.spec import Json
from quarry.server.models import Step
from quarry.server.service import ProviderFactory, SessionService, StepNotFound


class SaveDatasetRequest(BaseModel):
    session_id: str
    dataset: str
    mode: SaveMode
    description: str = ""


class SaveViewRequest(BaseModel):
    session_id: str
    step_id: str
    name: str
    description: str = ""
    mode: SaveMode


class UnknownDataset(Exception):
    pass


class SavedView(BaseModel):
    meta: SavedViewMeta
    source: str
    state: dict[str, Json]


class ProjectService:
    def __init__(
        self,
        *,
        config: QuarryConfig,
        store: ProjectStore,
        sessions: SessionService,
        provider_factory: ProviderFactory,
    ) -> None:
        self._config = config
        self._store = store
        self._sessions = sessions
        self._provider_factory = provider_factory

    def create(self, name: str, description: str) -> ProjectMeta:
        return self._store.create(name, description)

    def list(self) -> list[ProjectMeta]:
        return self._store.list()

    def get(self, slug: str) -> Project:
        return self._store.get(slug)

    def set_canvas(self, slug: str, cards: list[CanvasCard]) -> ProjectMeta:
        return self._store.set_canvas(slug, cards)

    def view(self, slug: str, name: str) -> SavedView:
        meta, source, state = self._store.read_view(slug, name)
        return SavedView(meta=meta, source=source, state=state)

    def save_dataset(self, slug: str, req: SaveDatasetRequest) -> SavedDatasetMeta:
        self._store.meta(slug)  # KeyError for an unknown project before touching the session
        # Busy is checked before anything else so a running step answers 409, never 404.
        with self._sessions.hold(req.session_id) as kernel:
            steps = self._sessions.get(req.session_id).steps
            lineage = recipe_steps(steps, req.dataset)
            raw = raw_recipe(lineage)
            try:
                expected = kernel.describe(req.dataset)
            except RpcFailure as exc:
                raise UnknownDataset(req.dataset) from exc
            if req.mode == "pinned":
                kernel.snapshot(req.dataset, self._store.parquet_path(slug, req.dataset))
        tidied = tidy_recipe(self._provider_factory(self._config), raw, req.dataset)
        candidate = tidied if tidied is not None else raw
        result = validate_recipe(self._config.root, candidate, req.dataset, expected)
        if not result.ok and tidied is not None:
            result = validate_recipe(self._config.root, raw, req.dataset, expected)
            candidate = raw
        meta = SavedDatasetMeta(
            name=req.dataset,
            description=req.description,
            backing=expected.backing,
            schema=expected.schema_,
            rows=expected.rows,
            mode=req.mode,
            saved_at=now_iso(),
            source_session=req.session_id,
            source_step=lineage[-1].id,
            validated=result.ok,
            validation_error=result.error,
        )
        self._store.write_dataset(slug, meta, recipe=candidate if result.ok else raw, raw=raw)
        return meta

    def save_view(self, slug: str, req: SaveViewRequest) -> SavedViewMeta:
        if NAME_RE.match(req.name) is None:  # before any dataset save spends a kernel
            raise ValueError("view names are lowercase letters, digits, '-' and '_', up to 64 chars")
        step = self._find_step(req.session_id, req.step_id)
        if step.view is None:
            raise StepNotFound(req.step_id)
        saved = {d.name for d in self._store.get(slug).datasets}
        for name in step.view.datasets:
            if name not in saved:
                self.save_dataset(
                    slug, SaveDatasetRequest(session_id=req.session_id, dataset=name, mode=req.mode)
                )
        state = step.view.snapshots[-1].state if step.view.snapshots else step.view.initial_state
        meta = SavedViewMeta(
            name=req.name,
            description=req.description,
            datasets=step.view.datasets,
            component_id=step.view.component_id,
            saved_at=now_iso(),
            source_session=req.session_id,
            source_step=step.id,
        )
        self._store.write_view(slug, meta, source=step.view.source, state=state)
        return meta

    def _find_step(self, session_id: str, step_id: str) -> Step:
        for step in self._sessions.get(session_id).steps:
            if step.id == step_id:
                return step
        raise StepNotFound(step_id)
```

The tidied script is validated first; when it fails, the raw script is validated as the fallback so a bad tidy does not mark a correct raw recipe unvalidated. When both fail, `validation_error` carries the raw script's error and `recipe.py` is the raw script.

If Stage 3's `StepNotFound` does not exist yet on the branch, define `class StepNotFound(Exception)` in `service.py` as the Stage 3 plan does (Task 9 there).

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/server/test_projects_service.py tests/server/test_app.py -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: save datasets and views into projects"
```

---

### Task 6: Project routes

**Files:**

- Create: `src/quarry/server/project_routes.py`
- Modify: `src/quarry/server/app.py` (construct `ProjectService`, register routes)
- Test: `tests/server/test_project_routes.py`

**Interfaces:**

- Produces: `register_project_routes(api: APIRouter, projects: ProjectService, sessions: SessionService) -> None` adding `POST /projects` (201) body `{name, description}`, `GET /projects`, `GET /projects/{slug}` (404), `GET /projects/{slug}/views/{name}` → `SavedView {meta, source, state}` (404), `POST /projects/{slug}/datasets` body `SaveDatasetRequest` (404 unknown project, step or dataset; 409 session busy; 503 kernel dead), `POST /projects/{slug}/views` body `SaveViewRequest` (same codes, 400 bad view name), `PUT /projects/{slug}/canvas` body `list[CanvasCard]`.
- Consumes: Task 5; `create_app` from Stage 2 (`api` router with the auth dependency, `service` as the `SessionService`).

- [ ] **Step 1: Failing tests**

`tests/server/test_project_routes.py` (reuse `make_client`, `py`, `end`, `wait_idle` from `tests/server/test_app.py` by importing them):

```python
from pathlib import Path

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, ToolCall
from tests.server.test_app import end, make_client, py, wait_idle

PRICES = "prices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})"
TIDY = "import polars as pl\n" + PRICES + "\n"


def render(call_id: str) -> AssistantTurn:
    call = ToolCall(
        id=call_id, name="render_view",
        input={"component_id": "data-table", "datasets": ["prices"], "initial_state": "{}"},
    )
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def test_project_crud_and_save_flow(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", PRICES), render("c2"), end(), end(TIDY)])
    client = make_client(tmp_path, [], provider_factory=lambda _cfg: provider)
    created = client.post("/projects", json={"name": "Momentum", "description": "d"})
    assert created.status_code == 201 and created.json()["slug"] == "momentum"
    assert [p["slug"] for p in client.get("/projects").json()] == ["momentum"]
    assert client.get("/projects/nope").status_code == 404

    sid = client.post("/sessions", json={}).json()["id"]
    step_id = client.post(f"/sessions/{sid}/steps", json={"prompt": "load"}).json()["id"]
    wait_idle(client, sid)
    body = {"session_id": sid, "step_id": step_id, "name": "table", "mode": "live"}
    saved = client.post("/projects/momentum/views", json=body)
    assert saved.status_code == 200 and saved.json()["datasets"] == ["prices"]
    project = client.get("/projects/momentum").json()
    assert project["datasets"][0]["validated"] is True
    assert project["views"][0]["name"] == "table"

    bad = client.post("/projects/momentum/views", json={**body, "name": "Bad Name"})
    assert bad.status_code == 400
    missing = client.post(
        "/projects/momentum/datasets", json={"session_id": sid, "dataset": "nope", "mode": "live"}
    )
    assert missing.status_code == 404

    cards = [{"view": "table", "x": 0, "y": 0, "w": 6, "h": 8}]
    assert client.put("/projects/momentum/canvas", json=cards).json()["canvas"] == cards
    view = client.get("/projects/momentum/views/table").json()
    assert view["meta"]["name"] == "table" and "export default" in view["source"]
    assert view["state"] == {}
    assert client.get("/projects/momentum/views/nope").status_code == 404


def test_save_while_running_is_409(tmp_path: Path) -> None:
    provider = FakeProvider([py("c1", "import time; time.sleep(3)"), end()])
    client = make_client(tmp_path, [], provider_factory=lambda _cfg: provider)
    client.post("/projects", json={"name": "p"})
    sid = client.post("/sessions", json={}).json()["id"]
    client.post(f"/sessions/{sid}/steps", json={"prompt": "slow"})
    body = {"session_id": sid, "dataset": "x", "mode": "live"}
    assert client.post("/projects/p/datasets", json=body).status_code == 409
    client.post(f"/sessions/{sid}/interrupt")
    wait_idle(client, sid)
```

The 409 case must return before the sleeping step finishes; a hang here is the Review Focus 3 failure.

- [ ] **Step 2: Routes**

`src/quarry/server/project_routes.py`:

```python
"""Project routes: create and list projects, save datasets and views, lay out the canvas."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from quarry.kernel.client import KernelDead
from quarry.projects.models import CanvasCard, Project, ProjectMeta, SavedDatasetMeta, SavedViewMeta
from quarry.server.projects import (
    ProjectService,
    SaveDatasetRequest,
    SavedView,
    SaveViewRequest,
    UnknownDataset,
)
from quarry.server.service import SessionBusy, SessionService, StepNotFound

T = TypeVar("T")


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""


def register_project_routes(
    api: APIRouter, projects: ProjectService, sessions: SessionService
) -> None:
    @api.post("/projects", status_code=201)
    def create_project(body: CreateProjectRequest) -> ProjectMeta:
        if body.name.strip() == "":
            raise HTTPException(status_code=400, detail="a project needs a name")
        return projects.create(body.name.strip(), body.description)

    @api.get("/projects")
    def list_projects() -> list[ProjectMeta]:
        return projects.list()

    @api.get("/projects/{slug}")
    def get_project(slug: str) -> Project:
        return _found(lambda: projects.get(slug))

    @api.get("/projects/{slug}/views/{name}")
    def get_saved_view(slug: str, name: str) -> SavedView:
        return _found(lambda: projects.view(slug, name))

    @api.post("/projects/{slug}/datasets")
    def save_dataset(slug: str, body: SaveDatasetRequest) -> SavedDatasetMeta:
        return _saving(lambda: projects.save_dataset(slug, body))

    @api.post("/projects/{slug}/views")
    def save_view(slug: str, body: SaveViewRequest) -> SavedViewMeta:
        return _saving(lambda: projects.save_view(slug, body))

    @api.put("/projects/{slug}/canvas")
    def set_canvas(slug: str, body: list[CanvasCard]) -> ProjectMeta:
        return _found(lambda: projects.set_canvas(slug, body))


def _found(call: Callable[[], T]) -> T:
    try:
        return call()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"not found: {exc}") from exc


def _saving(call: Callable[[], T]) -> T:
    try:
        return _found(call)
    except (UnknownDataset, StepNotFound) as exc:
        raise HTTPException(status_code=404, detail=f"not found: {exc}") from exc
    except SessionBusy as exc:
        raise HTTPException(status_code=409, detail="a step is running; save when it finishes") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KernelDead as exc:
        raise HTTPException(status_code=503, detail="kernel is dead; restart the session") from exc
```

In `app.py`, after `service` is built:

```python
    projects = ProjectService(
        config=config,
        store=ProjectStore(config.root),
        sessions=service,
        provider_factory=provider_factory,
    )
    ...
    register_project_routes(api, projects, service)
    app.include_router(api)
```

- [ ] **Step 3: Verify and commit**

```bash
uv run pytest tests/server -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: add project routes"
```

---

### Task 7: Recall as a step

**Files:**

- Modify: `src/quarry/server/service.py` (`_begin(view=)`, `start_recall`), `src/quarry/server/projects.py` (`recall`), `src/quarry/server/project_routes.py` (route), `src/quarry/server/app.py`
- Test: `tests/server/test_recall.py`

**Interfaces:**

- Produces: `RecallRequest {project, kind: "dataset" | "view", name}`; `ProjectService.recall(session_id, req) -> Step`; `SessionService.start_recall(session_id, *, prompt, code, view: View | None) -> Step` (kind `recall`, runs through the manual path so `runs` is filled); `POST /sessions/{id}/recall` (202; 404 unknown project or item; 409 busy).
- Consumes: Task 6; `View`, `_begin`, `_start`, `_run_manual`.

- [ ] **Step 1: Failing tests**

`tests/server/test_recall.py`:

```python
from pathlib import Path

from quarry.agent.fake import FakeProvider
from quarry.agent.types import AssistantTurn, ToolCall
from tests.server.test_app import end, make_client, py, wait_idle

PRICES = "prices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})"
TIDY = "import polars as pl\n" + PRICES + "\n"


def render(call_id: str) -> AssistantTurn:
    call = ToolCall(
        id=call_id, name="render_view",
        input={"component_id": "data-table", "datasets": ["prices"], "initial_state": '{"limit": 7}'},
    )
    return AssistantTurn(text="", tool_calls=[call], stop="tool_use")


def saved_project(tmp_path: Path, mode: str) -> tuple[object, str]:
    provider = FakeProvider([py("c1", PRICES), render("c2"), end(), end(TIDY)])
    client = make_client(tmp_path, [], provider_factory=lambda _cfg: provider)
    client.post("/projects", json={"name": "p"})
    sid = client.post("/sessions", json={}).json()["id"]
    step_id = client.post(f"/sessions/{sid}/steps", json={"prompt": "load"}).json()["id"]
    wait_idle(client, sid)
    body = {"session_id": sid, "step_id": step_id, "name": "table", "mode": mode}
    assert client.post("/projects/p/views", json=body).status_code == 200
    return client, sid


def test_recall_live_dataset_into_new_session(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "live")
    sid = client.post("/sessions", json={}).json()["id"]
    body = {"project": "p", "kind": "dataset", "name": "prices"}
    step = client.post(f"/sessions/{sid}/recall", json=body)
    assert step.status_code == 202 and step.json()["kind"] == "recall"
    wait_idle(client, sid)
    done = client.get(f"/sessions/{sid}").json()["steps"][0]
    assert done["status"] == "ok" and done["writes"] == ["prices"]
    assert done["code"] == TIDY and done["runs"][0]["status"] == "ok"
    assert [d["name"] for d in client.get(f"/sessions/{sid}/datasets").json()] == ["prices"]


def test_recall_pinned_reads_parquet(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "pinned")
    sid = client.post("/sessions", json={}).json()["id"]
    client.post(f"/sessions/{sid}/recall", json={"project": "p", "kind": "dataset", "name": "prices"})
    wait_idle(client, sid)
    done = client.get(f"/sessions/{sid}").json()["steps"][0]
    assert "pl.read_parquet(" in done["code"] and "data.parquet" in done["code"]
    assert done["status"] == "ok" and done["datasets"][0]["rows"] == 1


def test_recall_view_mounts_with_saved_state(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "live")
    sid = client.post("/sessions", json={}).json()["id"]
    client.post(f"/sessions/{sid}/recall", json={"project": "p", "kind": "view", "name": "table"})
    wait_idle(client, sid)
    done = client.get(f"/sessions/{sid}").json()["steps"][0]
    assert done["status"] == "ok" and done["writes"] == ["prices"]
    assert done["view"]["initial_state"] == {"limit": 7}
    assert done["view"]["datasets"] == ["prices"] and "export default" in done["view"]["source"]
    again = client.post(f"/sessions/{sid}/recall", json={"project": "p", "kind": "view", "name": "table"})
    wait_idle(client, sid)
    second = client.get(f"/sessions/{sid}").json()["steps"][1]
    assert again.status_code == 202 and second["writes"] == [] and second["view"] is not None


def test_recall_unknown_is_404(tmp_path: Path) -> None:
    client, sid = saved_project(tmp_path, "live")
    body = {"project": "p", "kind": "dataset", "name": "nope"}
    assert client.post(f"/sessions/{sid}/recall", json=body).status_code == 404
    body = {"project": "zzz", "kind": "view", "name": "table"}
    assert client.post(f"/sessions/{sid}/recall", json=body).status_code == 404
```

- [ ] **Step 2: Session service**

In `service.py`, extend `_begin` with `view: View | None = None` and pass it into the `Step(...)` constructor, then add:

```python
    def start_recall(self, session_id: str, *, prompt: str, code: str, view: View | None) -> Step:
        step = self._begin(session_id, kind="recall", prompt=prompt, code=code, view=view)
        self._start(session_id, self._run_manual, (session_id, step))
        return step
```

`_run_manual` keeps `step.view` because `_apply_exec` uses `model_copy(update=...)` on the step it was given.

- [ ] **Step 3: Project service and route**

In `projects.py` (add `import hashlib`, `from typing import Literal` and `from quarry.server.models import Step, View`):

```python
class RecallRequest(BaseModel):
    project: str
    kind: Literal["dataset", "view"]
    name: str


    def recall(self, session_id: str, req: RecallRequest) -> Step:
        project = self._store.get(req.project)
        if req.kind == "dataset":
            code = self._dataset_code(project, req.name)
            return self._sessions.start_recall(
                session_id, prompt=f"Recall {req.name} from {project.meta.name}", code=code, view=None
            )
        meta, source, state = self._store.read_view(req.project, req.name)
        present = {d.name for d in self._sessions.datasets(session_id)}
        blocks = [
            f"# dataset {name}\n{self._dataset_code(project, name)}"
            for name in meta.datasets
            if name not in present
        ]
        code = "\n".join(blocks) if blocks else "# every dataset this view needs is already loaded\n"
        view = View(
            component_id=meta.component_id,
            content_hash=hashlib.sha256(source.encode("utf-8")).hexdigest(),
            source=source,
            initial_state=state,
            datasets=meta.datasets,
        )
        return self._sessions.start_recall(
            session_id, prompt=f"Recall view {req.name} from {project.meta.name}", code=code, view=view
        )

    def _dataset_code(self, project: Project, name: str) -> str:
        saved = next((d for d in project.datasets if d.name == name), None)
        if saved is None:
            raise KeyError(name)
        if saved.mode == "pinned":
            path = self._store.parquet_path(project.meta.slug, name)
            return f"import polars as pl\n{name} = pl.read_parquet({str(path)!r})\n"
        return self._store.read_recipe(project.meta.slug, name)
```

`self._sessions.datasets(session_id)` starts the kernel if needed and raises `KernelDead` when it is dead; the route maps that to 503.

In `project_routes.py`:

```python
    @api.post("/sessions/{session_id}/recall", status_code=202)
    def recall(session_id: str, body: RecallRequest) -> Step:
        _found(lambda: sessions.get(session_id))  # the session store raises KeyError
        return _saving(lambda: projects.recall(session_id, body))
```

`_saving` already maps `KeyError` to 404 and `SessionBusy` to 409. The explicit session check comes first because `_begin` does not look the session up and would otherwise fail inside the step thread.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/server -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: recall saved datasets and views as steps"
```

---

### Task 8: Host: project types, client, `ViewHost`, snapshot scrubber

**Files:**

- Modify: `web/src/shared/api-types.ts`, `web/src/host/api/client.ts`, `web/src/host/api/keys.ts`, `web/src/host/api/hooks.ts`, `web/src/host/containers/ViewFrameContainer.tsx`
- Create: `web/src/host/containers/ViewHost.tsx`, `web/src/host/components/SnapshotScrubber.tsx`
- Test: `web/src/host/api/client.test.ts` (extend), `web/src/host/containers/ViewHost.test.tsx`, `web/src/host/components/SnapshotScrubber.test.tsx`

**Interfaces:**

- Produces: TS `CanvasCard`, `ProjectMeta`, `SavedDatasetMeta`, `SavedViewMeta`, `Project`, `SavedView`, `SaveMode`, `SaveDatasetRequest`, `SaveViewRequest`, `RecallRequest`; `ApiClient.listProjects/createProject/getProject/getSavedView/saveDataset/saveView/setCanvas/recall`; `keys.projects()`, `keys.project(slug)`, `keys.savedView(slug, name)`; hooks `useProjects`, `useProject(slug)`, `useSavedView(slug, name)`, `useCreateProject`, `useSaveDataset()`, `useSaveView()`, `useSetCanvas()` (each taking the slug in its variables), `useRecall(sessionId)`; `ViewHost` props `{viewId, sessionId, source, initialState, datasets, ownDatasets, restoreState, hub?, title, onStateChanged?, onError?}`; `SnapshotScrubber {snapshots, onPick(state)}`.
- Consumes: Stage 3's `HostBridge`, `ViewFrame`, `useApi`, `keys`, `ViewFrameContainer` (re-read the real files first; this task refactors them).

- [ ] **Step 1: Types, client, keys, hooks**

Append to `web/src/shared/api-types.ts`:

```ts
export type SaveMode = "live" | "pinned";

export interface CanvasCard {
  view: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ProjectMeta {
  slug: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  canvas: CanvasCard[];
}

export interface SavedDatasetMeta {
  name: string;
  description: string;
  backing: "polars" | "polars_lazy" | "duckdb";
  schema: Column[];
  rows: number | null;
  mode: SaveMode;
  saved_at: string;
  source_session: string;
  source_step: string;
  validated: boolean;
  validation_error: string | null;
}

export interface SavedViewMeta {
  name: string;
  description: string;
  datasets: string[];
  component_id: string;
  saved_at: string;
  source_session: string;
  source_step: string;
}

export interface Project {
  meta: ProjectMeta;
  datasets: SavedDatasetMeta[];
  views: SavedViewMeta[];
}

export interface SaveDatasetRequest {
  session_id: string;
  dataset: string;
  mode: SaveMode;
  description?: string;
}

export interface SaveViewRequest {
  session_id: string;
  step_id: string;
  name: string;
  description?: string;
  mode: SaveMode;
}

export interface RecallRequest {
  project: string;
  kind: "dataset" | "view";
  name: string;
}

export interface SavedView {
  meta: SavedViewMeta;
  source: string;
  state: JsonObject;
}
```

`ApiClient` methods:

```ts
  listProjects(): Promise<ProjectMeta[]> {
    return this.request("GET", "/projects");
  }

  createProject(name: string, description = ""): Promise<ProjectMeta> {
    return this.request("POST", "/projects", { name, description });
  }

  getProject(slug: string): Promise<Project> {
    return this.request("GET", `/projects/${slug}`);
  }

  getSavedView(slug: string, name: string): Promise<SavedView> {
    return this.request("GET", `/projects/${slug}/views/${name}`);
  }

  saveDataset(slug: string, body: SaveDatasetRequest): Promise<SavedDatasetMeta> {
    return this.request("POST", `/projects/${slug}/datasets`, body);
  }

  saveView(slug: string, body: SaveViewRequest): Promise<SavedViewMeta> {
    return this.request("POST", `/projects/${slug}/views`, body);
  }

  setCanvas(slug: string, cards: CanvasCard[]): Promise<ProjectMeta> {
    return this.request("PUT", `/projects/${slug}/canvas`, cards);
  }

  recall(sessionId: string, body: RecallRequest): Promise<Step> {
    return this.request("POST", `/sessions/${sessionId}/recall`, body);
  }
```

Test additions in `client.test.ts`:

```ts
it("puts canvas cards as a bare array", async () => {
  const fetch = fakeFetch(200, {
    slug: "p",
    name: "p",
    description: "",
    created_at: "",
    updated_at: "",
    canvas: [],
  });
  const client = new ApiClient("tok", fetch);
  await client.setCanvas("p", [{ view: "v", x: 0, y: 0, w: 6, h: 8 }]);
  const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
  expect(url).toBe("/projects/p/canvas");
  expect(init.method).toBe("PUT");
  expect(init.body).toBe(
    JSON.stringify([{ view: "v", x: 0, y: 0, w: 6, h: 8 }]),
  );
});
```

`keys.ts` additions: `projects: () => ["projects"] as const`, `project: (slug: string) => ["projects", slug] as const`, `savedView: (slug: string, name: string) => ["projects", slug, "views", name] as const`.

`hooks.ts` additions:

```ts
export function useProjects() {
  const api = useApi();
  return useQuery({
    queryKey: keys.projects(),
    queryFn: () => api.listProjects(),
  });
}

export function useProject(slug: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.project(slug),
    queryFn: () => api.getProject(slug),
  });
}

export function useCreateProject() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.createProject(name),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.projects() }),
  });
}

export function useSavedView(slug: string, name: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.savedView(slug, name),
    queryFn: () => api.getSavedView(slug, name),
  });
}

// The project is chosen inside the save dialog, so the slug travels with the mutation.
export function useSaveDataset() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, body }: { slug: string; body: SaveDatasetRequest }) =>
      api.saveDataset(slug, body),
    onSuccess: (_meta, { slug }) =>
      qc.invalidateQueries({ queryKey: keys.project(slug) }),
  });
}

export function useSaveView() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, body }: { slug: string; body: SaveViewRequest }) =>
      api.saveView(slug, body),
    onSuccess: (_meta, { slug }) =>
      qc.invalidateQueries({ queryKey: keys.project(slug) }),
  });
}

export function useSetCanvas() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, cards }: { slug: string; cards: CanvasCard[] }) =>
      api.setCanvas(slug, cards),
    onSuccess: (meta, { slug }) => {
      qc.setQueryData(keys.project(slug), (old: Project | undefined) =>
        old ? { ...old, meta } : old,
      );
      void qc.invalidateQueries({ queryKey: keys.projects() });
    },
  });
}

export function useRecall(sessionId: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: RecallRequest) => api.recall(sessionId, body),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: keys.session(sessionId) }),
  });
}
```

- [ ] **Step 2: Failing tests for `ViewHost` and the scrubber**

`web/src/host/containers/ViewHost.test.tsx`:

```tsx
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { HostToRuntime } from "@/shared/bridge-types";
import type { JsonObject } from "@/shared/json";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { ViewHost } from "./ViewHost";

// Stable references: the mount effect keys on these, so the rerender below only touches restoreState.
const INITIAL: JsonObject = { a: 1 };
const DATASETS = ["df"];
const OWN: never[] = [];

function mount(restoreState: JsonObject | null, onStateChanged = vi.fn()) {
  const fetchImpl = vi.fn(async () => new Response("[]", { status: 200 }));
  const qc = new QueryClient();
  const posted: HostToRuntime[] = [];
  const view = render(
    <QueryClientProvider client={qc}>
      <ApiProvider client={new ApiClient("t", fetchImpl)}>
        <ViewHost
          viewId="v1"
          sessionId="s"
          source="export default () => null"
          initialState={INITIAL}
          datasets={DATASETS}
          ownDatasets={OWN}
          restoreState={restoreState}
          title="card"
          onStateChanged={onStateChanged}
          onError={() => undefined}
        />
      </ApiProvider>
    </QueryClientProvider>,
  );
  const iframe = screen.getByTitle("card") as HTMLIFrameElement;
  const win = iframe.contentWindow;
  if (win === null) throw new Error("no frame window");
  win.postMessage = (m: HostToRuntime) => posted.push(m);
  const send = (data: unknown) =>
    window.dispatchEvent(new MessageEvent("message", { data, source: win }));
  return {
    posted,
    send,
    onStateChanged,
    rerender: view.rerender,
    qc,
    fetchImpl,
  };
}

describe("ViewHost", () => {
  it("mounts after ready and forwards stateChanged", async () => {
    const { posted, send, onStateChanged } = mount(null);
    await act(async () => send({ type: "ready" }));
    expect(posted[0]).toMatchObject({
      type: "mount",
      viewId: "v1",
      datasets: ["df"],
      initialState: { a: 1 },
    });
    await act(async () =>
      send({
        type: "stateChanged",
        viewId: "v1",
        state: { a: 2 },
        queries: [],
      }),
    );
    expect(onStateChanged).toHaveBeenCalledWith({ a: 2 }, []);
  });

  it("sends restore when restoreState changes", async () => {
    const { posted, send, rerender, qc, fetchImpl } = mount(null);
    await act(async () => send({ type: "ready" }));
    rerender(
      <QueryClientProvider client={qc}>
        <ApiProvider client={new ApiClient("t", fetchImpl)}>
          <ViewHost
            viewId="v1"
            sessionId="s"
            source="export default () => null"
            initialState={INITIAL}
            datasets={DATASETS}
            ownDatasets={OWN}
            restoreState={{ k: 2 }}
            title="card"
            onError={() => undefined}
          />
        </ApiProvider>
      </QueryClientProvider>,
    );
    expect(posted.at(-1)).toMatchObject({
      type: "restore",
      viewId: "v1",
      state: { k: 2 },
    });
  });
});
```

`web/src/host/components/SnapshotScrubber.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SnapshotScrubber } from "./SnapshotScrubber";

const snapshots = [
  { ts: "2026-10-08T00:00:00Z", state: { n: 1 }, queries: [] },
  { ts: "2026-10-08T00:01:00Z", state: { n: 2 }, queries: [] },
  { ts: "2026-10-08T00:02:00Z", state: { n: 3 }, queries: [] },
];

describe("SnapshotScrubber", () => {
  it("renders nothing for fewer than two snapshots", () => {
    const { container } = render(
      <SnapshotScrubber
        snapshots={snapshots.slice(0, 1)}
        onPick={() => undefined}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("picks a snapshot's state by position", () => {
    const onPick = vi.fn();
    render(<SnapshotScrubber snapshots={snapshots} onPick={onPick} />);
    fireEvent.change(screen.getByRole("slider"), { target: { value: "1" } });
    expect(onPick).toHaveBeenCalledWith({ n: 2 });
    expect(screen.getByText("2 of 3")).toBeTruthy();
  });
});
```

- [ ] **Step 3: `ViewHost`**

`web/src/host/containers/ViewHost.tsx`:

```tsx
import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { Column, DatasetMeta, QuerySpec } from "@/shared/api-types";
import type { JsonObject } from "@/shared/json";
import { useApi } from "../api/context";
import { keys } from "../api/keys";
import { HostBridge } from "../bridge/HostBridge";
import type { SharedStateHub } from "../bridge/SharedStateHub";
import { ViewFrame } from "../components/ViewFrame";

export interface ViewHostProps {
  viewId: string;
  sessionId: string;
  source: string;
  initialState: JsonObject;
  datasets: string[];
  ownDatasets: DatasetMeta[];
  restoreState: JsonObject | null;
  hub?: SharedStateHub;
  title: string;
  onStateChanged?: (state: JsonObject, queries: QuerySpec[]) => void;
  onError?: (message: string) => void;
  onFix?: () => void;
}

export function ViewHost(props: ViewHostProps) {
  const {
    viewId,
    sessionId,
    source,
    initialState,
    datasets,
    ownDatasets,
    restoreState,
    hub,
    title,
  } = props;
  const api = useApi();
  const queryClient = useQueryClient();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const bridgeRef = useRef<HostBridge | null>(null);
  const callbacks = useRef(props);
  callbacks.current = props;
  const [error, setError] = useState<string | null>(null);

  // One bridge per iframe for its lifetime; the window listener is the effect's only job.
  useEffect(() => {
    const frame = frameRef.current;
    if (frame === null) return;
    const schemaFor = async (dataset: string): Promise<Column[]> => {
      const own = ownDatasets.find((d) => d.name === dataset);
      if (own !== undefined) return own.schema;
      const all = await queryClient.fetchQuery({
        queryKey: keys.datasets(sessionId),
        queryFn: () => api.datasets(sessionId),
        staleTime: 0,
      });
      const match = all.find((d) => d.name === dataset);
      if (match === undefined) throw new Error(`unknown dataset ${dataset}`);
      return match.schema;
    };
    const bridge = new HostBridge({
      viewId,
      frame: {
        postMessage: (m, origin) => frame.contentWindow?.postMessage(m, origin),
      },
      isFrame: (s) => s === frame.contentWindow,
      onQuery: (spec) => api.query(sessionId, spec),
      onSchema: schemaFor,
      onStateChanged: (state, queries) => {
        hub?.report(viewId, state);
        callbacks.current.onStateChanged?.(state, queries);
      },
      onError: (message) => {
        setError(message);
        callbacks.current.onError?.(message);
      },
    });
    bridgeRef.current = bridge;
    const stop = bridge.listen(window);
    const unregister = hub?.register(viewId, initialState, (state) =>
      bridge.restore(state),
    );
    setError(null);
    bridge.mount({ source, initialState, datasets });
    return () => {
      unregister?.();
      stop();
      bridgeRef.current = null;
    };
  }, [
    api,
    queryClient,
    sessionId,
    viewId,
    source,
    initialState,
    datasets,
    ownDatasets,
    hub,
  ]);

  useEffect(() => {
    if (restoreState !== null) bridgeRef.current?.restore(restoreState);
  }, [restoreState]);

  return (
    <ViewFrame
      ref={frameRef}
      title={title}
      error={error}
      onFix={() => callbacks.current.onFix?.()}
    />
  );
}
```

Callers must pass stable `initialState`, `datasets` and `ownDatasets` references (memoised from the step or the saved view), otherwise the effect remounts; React Query's structural sharing keeps them stable across polls, and the snapshot mutation of `step.view` does not touch them.

`web/src/host/components/SnapshotScrubber.tsx`:

```tsx
import { useState } from "react";
import type { Snapshot } from "@/shared/api-types";
import type { JsonObject } from "@/shared/json";

interface SnapshotScrubberProps {
  snapshots: Snapshot[];
  onPick: (state: JsonObject) => void;
}

export function SnapshotScrubber({ snapshots, onPick }: SnapshotScrubberProps) {
  const [position, setPosition] = useState(snapshots.length - 1);
  if (snapshots.length < 2) return null;
  const current = Math.min(position, snapshots.length - 1);
  return (
    <label className="flex items-center gap-3 text-sm text-muted-foreground">
      History
      <input
        type="range"
        min={0}
        max={snapshots.length - 1}
        value={current}
        onChange={(e) => {
          const next = Number(e.target.value);
          setPosition(next);
          const picked = snapshots[next];
          if (picked !== undefined) onPick(picked.state);
        }}
        className="w-48 accent-primary"
      />
      <span className="tabular-nums">
        {current + 1} of {snapshots.length}
      </span>
    </label>
  );
}
```

- [ ] **Step 4: Rewire `ViewFrameContainer`**

Replace its body so it owns only what is step-specific: snapshots posting, repair, the scrubber, and the actions row that Task 9 fills.

```tsx
import { useMemo, useState, type ReactNode } from "react";
import type { RepairRequest, Step } from "@/shared/api-types";
import type { JsonObject } from "@/shared/json";
import { useApi } from "../api/context";
import { SnapshotScrubber } from "../components/SnapshotScrubber";
import { ViewHost } from "./ViewHost";

interface ViewFrameContainerProps {
  sessionId: string;
  step: Step;
  onRepair: (repair: RepairRequest) => void;
  actions?: ReactNode;
}

export function ViewFrameContainer({
  sessionId,
  step,
  onRepair,
  actions,
}: ViewFrameContainerProps) {
  const api = useApi();
  const [restoreState, setRestoreState] = useState<JsonObject | null>(null);
  const [lastError, setLastError] = useState<string | null>(null);
  const view = step.view;
  const initialState = useMemo(
    () => view?.initial_state ?? {},
    [view?.content_hash],
  );
  const datasets = useMemo(() => view?.datasets ?? [], [view?.content_hash]);
  if (view === null) return null;
  return (
    <div className="flex flex-col gap-2">
      <ViewHost
        viewId={step.id}
        sessionId={sessionId}
        source={view.source}
        initialState={initialState}
        datasets={datasets}
        ownDatasets={step.datasets}
        restoreState={restoreState}
        title={`View for step ${step.index + 1}`}
        onStateChanged={(state, queries) =>
          void api.postSnapshot(sessionId, step.id, { state, queries })
        }
        onError={setLastError}
        onFix={() =>
          lastError !== null && onRepair({ step_id: step.id, error: lastError })
        }
      />
      <div className="flex items-center justify-between gap-4">
        <SnapshotScrubber snapshots={view.snapshots} onPick={setRestoreState} />
        {actions}
      </div>
    </div>
  );
}
```

`useMemo` keyed on `content_hash` is deliberate: `initial_state` and `datasets` never change for a given view hash, and React's exhaustive-deps lint is not installed here. Update the Stage 3 `ViewFrameContainer.test.tsx` expectations only where the DOM changed (the iframe title and overlay are unchanged).

- [ ] **Step 5: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test
git add web && git commit -m "feat: share the view host between steps and cards, add snapshot scrubber"
```

---

### Task 9: Host: project browser, save dialogs, recall

**Files:**

- Create: `web/src/host/components/ProjectBrowser.tsx`, `web/src/host/components/SaveDialog.tsx`, `web/src/host/containers/ProjectRail.tsx`, `web/src/host/containers/StepActions.tsx`
- Modify: `web/src/host/components/SessionRail.tsx` (accept `children` below the sessions), `web/src/host/components/DatasetChips.tsx` (`onSave`), `web/src/host/containers/StepList.tsx` and `SessionPage.tsx` (wire actions and recall), `web/src/host/App.tsx` (`page` state: session or project)
- Test: `web/src/host/components/ProjectBrowser.test.tsx`, `web/src/host/components/SaveDialog.test.tsx`

**Interfaces:**

- Produces: `ProjectBrowser {projects, expanded, onToggle, onOpen(slug), onRecall(slug, kind, name), onCreate}`; `SaveDialog {open, kind: "dataset" | "view", projects, defaultName, onClose, onSave({slug, name, mode, description})}`; `StepActions {sessionId, step}` rendering "Save view" and "Pin to canvas" for steps with a view; `App` page union `{ kind: "session" } | { kind: "project"; slug: string }`.
- Consumes: Task 8 hooks; Stage 3 `SessionRail`, `StepCard`, `DatasetChips`, `SessionPage`.

- [ ] **Step 1: shadcn pieces**

```bash
cd web && npx shadcn@latest add -y dialog label radio-group
```

- [ ] **Step 2: Failing tests**

`web/src/host/components/ProjectBrowser.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Project } from "@/shared/api-types";
import { ProjectBrowser } from "./ProjectBrowser";

const project: Project = {
  meta: {
    slug: "p",
    name: "Momentum",
    description: "",
    created_at: "",
    updated_at: "",
    canvas: [],
  },
  datasets: [
    {
      name: "prices",
      description: "",
      backing: "polars",
      schema: [],
      rows: 3,
      mode: "live",
      saved_at: "",
      source_session: "s",
      source_step: "t",
      validated: false,
      validation_error: "rows differ",
    },
  ],
  views: [
    {
      name: "table",
      description: "",
      datasets: ["prices"],
      component_id: "data-table",
      saved_at: "",
      source_session: "s",
      source_step: "t",
    },
  ],
};

describe("ProjectBrowser", () => {
  it("lists projects, expands to items, recalls and opens", () => {
    const onRecall = vi.fn();
    const onOpen = vi.fn();
    render(
      <ProjectBrowser
        projects={[project]}
        expanded="p"
        onToggle={() => undefined}
        onOpen={onOpen}
        onRecall={onRecall}
        onCreate={() => undefined}
      />,
    );
    expect(screen.getByText("Momentum")).toBeTruthy();
    expect(screen.getByTitle("Not validated: rows differ")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Recall prices" }));
    expect(onRecall).toHaveBeenCalledWith("p", "dataset", "prices");
    fireEvent.click(screen.getByRole("button", { name: "Recall table" }));
    expect(onRecall).toHaveBeenCalledWith("p", "view", "table");
    fireEvent.click(screen.getByRole("button", { name: "Open Momentum" }));
    expect(onOpen).toHaveBeenCalledWith("p");
  });
});
```

`web/src/host/components/SaveDialog.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SaveDialog } from "./SaveDialog";

const projects = [
  {
    slug: "p",
    name: "Momentum",
    description: "",
    created_at: "",
    updated_at: "",
    canvas: [],
  },
];

describe("SaveDialog", () => {
  it("submits project, name, mode and description", () => {
    const onSave = vi.fn();
    render(
      <SaveDialog
        open
        kind="view"
        projects={projects}
        defaultName="step-3-view"
        onClose={() => undefined}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "closes" },
    });
    fireEvent.click(screen.getByLabelText("Pinned copy"));
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "daily" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));
    expect(onSave).toHaveBeenCalledWith({
      slug: "p",
      name: "closes",
      mode: "pinned",
      description: "daily",
    });
  });

  it("slugifies the name and blocks empty names", () => {
    const onSave = vi.fn();
    render(
      <SaveDialog
        open
        kind="view"
        projects={projects}
        defaultName=""
        onClose={() => undefined}
        onSave={onSave}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "My Closes!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ name: "my-closes" }),
    );
  });
});
```

- [ ] **Step 3: Components**

`web/src/host/components/ProjectBrowser.tsx`:

```tsx
import { Button } from "@/components/ui/button";
import type { Project } from "@/shared/api-types";

interface ProjectBrowserProps {
  projects: Project[];
  expanded: string | null;
  onToggle: (slug: string) => void;
  onOpen: (slug: string) => void;
  onRecall: (slug: string, kind: "dataset" | "view", name: string) => void;
  onCreate: () => void;
}

export function ProjectBrowser({
  projects,
  expanded,
  onToggle,
  onOpen,
  onRecall,
  onCreate,
}: ProjectBrowserProps) {
  return (
    <section className="flex flex-col gap-2 border-t border-border pt-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">Projects</h2>
        <Button variant="ghost" size="xs" onClick={onCreate}>
          New project
        </Button>
      </div>
      {projects.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Save a dataset or view to start a project.
        </p>
      )}
      <ul className="flex flex-col gap-1">
        {projects.map(({ meta, datasets, views }) => (
          <li key={meta.slug} className="flex flex-col gap-1">
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-expanded={expanded === meta.slug}
                onClick={() => onToggle(meta.slug)}
                className="flex-1 truncate rounded-md px-2 py-1 text-left text-sm hover:bg-muted"
              >
                {meta.name}
              </button>
              <Button
                variant="ghost"
                size="xs"
                aria-label={`Open ${meta.name}`}
                onClick={() => onOpen(meta.slug)}
              >
                Open
              </Button>
            </div>
            {expanded === meta.slug && (
              <ul className="ml-3 flex flex-col gap-0.5 border-l border-border pl-2">
                {datasets.map((d) => (
                  <li key={d.name} className="flex items-center gap-2 text-sm">
                    <button
                      type="button"
                      aria-label={`Recall ${d.name}`}
                      onClick={() => onRecall(meta.slug, "dataset", d.name)}
                      className="truncate font-mono hover:text-primary"
                    >
                      {d.name}
                    </button>
                    <span className="text-xs text-muted-foreground">
                      {d.mode}
                    </span>
                    {!d.validated && (
                      <span
                        title={`Not validated: ${d.validation_error ?? "unknown reason"}`}
                        className="text-xs text-[var(--status-interrupted)]"
                      >
                        unvalidated
                      </span>
                    )}
                  </li>
                ))}
                {views.map((v) => (
                  <li key={v.name} className="text-sm">
                    <button
                      type="button"
                      aria-label={`Recall ${v.name}`}
                      onClick={() => onRecall(meta.slug, "view", v.name)}
                      className="truncate hover:text-primary"
                    >
                      {v.name}
                    </button>
                    <span className="ml-2 text-xs text-muted-foreground">
                      view
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
```

`web/src/host/components/SaveDialog.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ProjectMeta, SaveMode } from "@/shared/api-types";

export interface SaveChoice {
  slug: string;
  name: string;
  mode: SaveMode;
  description: string;
}

interface SaveDialogProps {
  open: boolean;
  kind: "dataset" | "view";
  projects: ProjectMeta[];
  defaultName: string;
  onClose: () => void;
  onSave: (choice: SaveChoice) => void;
}

export const slugifyName = (name: string): string =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");

export function SaveDialog({
  open,
  kind,
  projects,
  defaultName,
  onClose,
  onSave,
}: SaveDialogProps) {
  const [slug, setSlug] = useState(projects[0]?.slug ?? "");
  const [name, setName] = useState(defaultName);
  const [mode, setMode] = useState<SaveMode>("live");
  const [description, setDescription] = useState("");
  const cleanName = kind === "view" ? slugifyName(name) : name;
  const canSave = slug !== "" && cleanName !== "";
  const label = kind === "view" ? "Save view" : "Save dataset";
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="flex flex-col gap-4">
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="save-project">Project</Label>
          {projects.length === 0 && (
            <p className="text-xs text-muted-foreground">
              Create a project in the rail first.
            </p>
          )}
          <select
            id="save-project"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            className="h-8 rounded-md border border-input bg-background px-2 text-sm"
          >
            {projects.map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="save-name">Name</Label>
          <Input
            id="save-name"
            value={name}
            disabled={kind === "dataset"}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <fieldset className="flex flex-col gap-1.5">
          <legend className="text-sm font-medium">Data</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="mode"
              checked={mode === "live"}
              onChange={() => setMode("live")}
            />
            Live recipe
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="mode"
              checked={mode === "pinned"}
              onChange={() => setMode("pinned")}
            />
            Pinned copy
          </label>
          <p className="text-xs text-muted-foreground">
            A live recipe re-runs the code that made the data. A pinned copy
            also keeps today's rows as parquet.
          </p>
        </fieldset>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="save-description">Description</Label>
          <Textarea
            id="save-description"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!canSave}
            onClick={() => onSave({ slug, name: cleanName, mode, description })}
          >
            {label}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
```

Native radios and a native select keep the dialog under the file cap; the shadcn `radio-group` added above can replace them later. The "Pinned copy" label test relies on `getByLabelText`, which the wrapping `<label>` satisfies.

- [ ] **Step 4: Containers and wiring**

`web/src/host/containers/StepActions.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Step } from "@/shared/api-types";
import {
  useProjects,
  useSaveDataset,
  useSaveView,
  useSetCanvas,
} from "../api/hooks";
import { SaveDialog, type SaveChoice } from "../components/SaveDialog";

interface StepActionsProps {
  sessionId: string;
  step: Step;
  dataset?: string;
  onDone: (message: string) => void;
}

type Pending =
  { kind: "dataset"; name: string } | { kind: "view"; pin: boolean } | null;

export function StepActions({
  sessionId,
  step,
  dataset,
  onDone,
}: StepActionsProps) {
  const projects = useProjects();
  const [pending, setPending] = useState<Pending>(null);
  const saveDataset = useSaveDataset();
  const saveView = useSaveView();
  const setCanvas = useSetCanvas();

  const onSave = (choice: SaveChoice) => {
    const { slug } = choice;
    if (pending?.kind === "dataset") {
      saveDataset.mutate(
        {
          slug,
          body: {
            session_id: sessionId,
            dataset: pending.name,
            mode: choice.mode,
            description: choice.description,
          },
        },
        {
          onSuccess: (meta) =>
            onDone(
              meta.validated
                ? `Saved ${meta.name}`
                : `Saved ${meta.name} without validation: ${meta.validation_error ?? ""}`,
            ),
        },
      );
    } else if (pending?.kind === "view") {
      const pin = pending.pin;
      saveView.mutate(
        {
          slug,
          body: {
            session_id: sessionId,
            step_id: step.id,
            name: choice.name,
            mode: choice.mode,
            description: choice.description,
          },
        },
        {
          onSuccess: (meta) => {
            onDone(`Saved view ${meta.name}`);
            if (pin) {
              const current =
                projects.data?.find((p) => p.slug === slug)?.canvas ?? [];
              const y = current.reduce((max, c) => Math.max(max, c.y + c.h), 0);
              setCanvas.mutate({
                slug,
                cards: [...current, { view: meta.name, x: 0, y, w: 6, h: 8 }],
              });
            }
          },
        },
      );
    }
    setPending(null);
  };

  return (
    <div className="flex items-center gap-2">
      {dataset !== undefined && (
        <Button
          variant="ghost"
          size="xs"
          onClick={() => setPending({ kind: "dataset", name: dataset })}
        >
          Save dataset
        </Button>
      )}
      {step.view !== null && dataset === undefined && (
        <>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setPending({ kind: "view", pin: false })}
          >
            Save view
          </Button>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setPending({ kind: "view", pin: true })}
          >
            Pin to canvas
          </Button>
        </>
      )}
      {pending !== null && (
        <SaveDialog
          open
          kind={pending.kind}
          projects={projects.data ?? []}
          defaultName={
            pending.kind === "dataset"
              ? pending.name
              : `step-${step.index + 1}-view`
          }
          onClose={() => setPending(null)}
          onSave={onSave}
        />
      )}
    </div>
  );
}
```

`DatasetChips` gains `onSave?: (name: string) => void` and renders a small "Save" button per chip when given; `StepCard` gains an `actions?: ReactNode` slot next to the view and passes `onSave` through. `StepList` takes `renderActions?: (step: Step, dataset?: string) => ReactNode`. `SessionColumn` in `SessionPage.tsx` supplies both:

```tsx
            renderActions={(step, dataset) => (
              <StepActions sessionId={id} step={step} dataset={dataset} onDone={setNotice} />
            )}
```

with `const [notice, setNotice] = useState<string | null>(null)` rendered as a dismissible line above the step list.

`web/src/host/containers/ProjectRail.tsx`:

```tsx
import { useState } from "react";
import { useQueries } from "@tanstack/react-query";
import type { Project } from "@/shared/api-types";
import { useApi } from "../api/context";
import { useCreateProject, useProjects, useRecall } from "../api/hooks";
import { keys } from "../api/keys";
import { ProjectBrowser } from "../components/ProjectBrowser";

interface ProjectRailProps {
  sessionId: string | null;
  onOpen: (slug: string) => void;
}

export function ProjectRail({ sessionId, onOpen }: ProjectRailProps) {
  const api = useApi();
  const metas = useProjects();
  const create = useCreateProject();
  const recall = useRecall(sessionId ?? "");
  const [expanded, setExpanded] = useState<string | null>(null);
  const details = useQueries({
    queries: (metas.data ?? []).map((m) => ({
      queryKey: keys.project(m.slug),
      queryFn: () => api.getProject(m.slug),
    })),
  });
  const projects: Project[] = details.flatMap((q) => (q.data ? [q.data] : []));
  return (
    <ProjectBrowser
      projects={projects}
      expanded={expanded}
      onToggle={(slug) => setExpanded(expanded === slug ? null : slug)}
      onOpen={onOpen}
      onRecall={(project, kind, name) => {
        if (sessionId === null) return;
        if (
          window.confirm(
            `Recall ${name} into this session? An existing dataset with that name is replaced.`,
          )
        ) {
          recall.mutate({ project, kind, name });
        }
      }}
      onCreate={() => {
        const name = window.prompt("Project name");
        if (name) create.mutate(name);
      }}
    />
  );
}
```

`window.confirm` and `window.prompt` are deliberate for Stage 4: two tiny flows that do not justify two more dialogs; swap for shadcn dialogs in Stage 5 if the researcher minds.

`App.tsx` gains `const [page, setPage] = useState<{ kind: "session" } | { kind: "project"; slug: string }>({ kind: "session" })` and renders `SessionPage` or `ProjectPage` (Task 10). `SessionPage` takes `onOpenProject` and renders `<ProjectRail sessionId={current} onOpen={onOpenProject} />` as `SessionRail`'s children.

- [ ] **Step 5: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test
git add web && git commit -m "feat: add project browser, save dialogs and recall to the host"
```

---

### Task 10: Canvas page

**Files:**

- Create: `web/src/host/containers/ProjectPage.tsx`, `web/src/host/containers/CanvasPage.tsx`, `web/src/host/components/CanvasCardFrame.tsx`, `web/src/host/components/SavedItems.tsx`
- Modify: `web/package.json` (deps), `web/src/host/index.css` (grid CSS), `web/src/host/App.tsx`
- Test: `web/src/host/containers/CanvasPage.test.tsx`

**Interfaces:**

- Produces: `ProjectPage {slug, sessionId, onBack}` with "Saved" and "Canvas" tabs; `CanvasPage {project, sessionId}`; `CanvasCardFrame {title, missing: string[], onLoad, onRemove, children}`; `layoutToCards(layout)`, `cardsToLayout(cards)`.
- Consumes: Task 8 `ViewHost`, hooks; Task 9 `useRecall`; `react-grid-layout` 2.3 `GridLayout`, `useContainerWidth`, `Layout`.

- [ ] **Step 1: Dependencies and CSS**

```bash
cd web && npm install react-grid-layout react-resizable
```

Append to `web/src/host/index.css`:

```css
@import "react-grid-layout/css/styles.css";
@import "react-resizable/css/styles.css";

/* The iframe would swallow the pointer mid-drag; the handle lives in the card header. */
.react-grid-item.react-draggable-dragging iframe,
.react-grid-item.resizing iframe {
  pointer-events: none;
}
.react-grid-item > .react-resizable-handle {
  z-index: 2;
}
```

- [ ] **Step 2: Failing test**

`web/src/host/containers/CanvasPage.test.tsx` (layout helpers only; the grid itself needs real layout and is covered by Playwright):

```ts
import { describe, expect, it } from "vitest";
import { cardsToLayout, layoutToCards } from "./CanvasPage";

describe("canvas layout mapping", () => {
  it("round-trips cards through the grid layout", () => {
    const cards = [
      { view: "a", x: 0, y: 0, w: 6, h: 8 },
      { view: "b", x: 6, y: 0, w: 6, h: 4 },
    ];
    const layout = cardsToLayout(cards);
    expect(layout[0]).toMatchObject({
      i: "a",
      x: 0,
      y: 0,
      w: 6,
      h: 8,
      minW: 3,
      minH: 3,
    });
    expect(layoutToCards(layout)).toEqual(cards);
  });
});
```

- [ ] **Step 3: Implement**

`web/src/host/components/CanvasCardFrame.tsx`:

```tsx
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface CanvasCardFrameProps {
  title: string;
  missing: string[];
  loading: boolean;
  onLoad: () => void;
  onRemove: () => void;
  children: ReactNode;
}

export function CanvasCardFrame({
  title,
  missing,
  loading,
  onLoad,
  onRemove,
  children,
}: CanvasCardFrameProps) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-border bg-card">
      <div className="card-handle flex cursor-move items-center justify-between border-b border-border px-3 py-1.5 text-sm">
        <span className="truncate">{title}</span>
        <Button variant="ghost" size="xs" onClick={onRemove}>
          Remove
        </Button>
      </div>
      <div className="min-h-0 flex-1">
        {missing.length === 0 ? (
          children
        ) : (
          <div className="flex h-full flex-col items-start gap-2 p-4 text-sm text-muted-foreground">
            <p>Needs {missing.join(", ")} in this session.</p>
            <Button size="sm" disabled={loading} onClick={onLoad}>
              {loading ? "Loading" : "Load"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
```

`web/src/host/containers/CanvasPage.tsx`:

```tsx
import { useEffect, useMemo, useRef, useState } from "react";
import GridLayout, { useContainerWidth, type Layout } from "react-grid-layout";
import type { CanvasCard, Project } from "@/shared/api-types";
import {
  useRecall,
  useSavedView,
  useSession,
  useSetCanvas,
} from "../api/hooks";
import { SharedStateHub } from "../bridge/SharedStateHub";
import { CanvasCardFrame } from "../components/CanvasCardFrame";
import { ViewHost } from "./ViewHost";

const COLS = 12;
const ROW_HEIGHT = 40;

export function cardsToLayout(cards: CanvasCard[]): Layout {
  return cards.map((c) => ({
    i: c.view,
    x: c.x,
    y: c.y,
    w: c.w,
    h: c.h,
    minW: 3,
    minH: 3,
  }));
}

export function layoutToCards(layout: Layout): CanvasCard[] {
  return layout.map((l) => ({ view: l.i, x: l.x, y: l.y, w: l.w, h: l.h }));
}

interface CanvasPageProps {
  project: Project;
  sessionId: string;
}

export function CanvasPage({ project, sessionId }: CanvasPageProps) {
  const { width, containerRef, mounted } = useContainerWidth();
  const session = useSession(sessionId);
  const recall = useRecall(sessionId);
  const setCanvas = useSetCanvas();
  const hub = useMemo(() => new SharedStateHub(), [project.meta.slug]);
  const [layout, setLayout] = useState<Layout>(() =>
    cardsToLayout(project.meta.canvas),
  );
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Debounce layout writes so a drag does not PUT on every frame.
  useEffect(
    () => () => {
      if (timer.current !== null) clearTimeout(timer.current);
    },
    [],
  );

  const present = new Set((session.data?.steps ?? []).flatMap((s) => s.writes));
  const loading = (session.data?.steps.at(-1)?.status ?? "ok") === "running";

  // react-grid-layout fires onLayoutChange once on mount after compaction; only a real
  // change in positions or sizes is worth a PUT.
  const onLayoutChange = (next: Layout) => {
    const cards = layoutToCards(next);
    if (JSON.stringify(cards) === JSON.stringify(layoutToCards(layout))) return;
    setLayout(next);
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(
      () => setCanvas.mutate({ slug: project.meta.slug, cards }),
      500,
    );
  };

  const remove = (view: string) => {
    const next = layout.filter((l) => l.i !== view);
    setLayout(next);
    setCanvas.mutate({ slug: project.meta.slug, cards: layoutToCards(next) });
  };

  return (
    <div ref={containerRef} className="min-h-0 flex-1 overflow-y-auto p-4">
      {project.meta.canvas.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Pin a view from a step to start the canvas.
        </p>
      )}
      {mounted && (
        <GridLayout
          width={width}
          layout={layout}
          gridConfig={{ cols: COLS, rowHeight: ROW_HEIGHT, margin: [12, 12] }}
          dragConfig={{ handle: ".card-handle" }}
          onLayoutChange={onLayoutChange}
        >
          {layout.map((item) => {
            const view = project.views.find((v) => v.name === item.i);
            if (view === undefined) return <div key={item.i} />;
            const missing = view.datasets.filter((d) => !present.has(d));
            return (
              <div key={item.i}>
                <CanvasCardFrame
                  title={view.name}
                  missing={missing}
                  loading={loading}
                  onLoad={() =>
                    recall.mutate({
                      project: project.meta.slug,
                      kind: "view",
                      name: view.name,
                    })
                  }
                  onRemove={() => remove(view.name)}
                >
                  <CanvasCardView
                    slug={project.meta.slug}
                    view={view.name}
                    sessionId={sessionId}
                    hub={hub}
                  />
                </CanvasCardFrame>
              </div>
            );
          })}
        </GridLayout>
      )}
    </div>
  );
}
```

`present` from step writes is an approximation of the kernel namespace that avoids another poll; a name written then deleted is rare and only costs a failing query shown inside the card.

`CanvasCardView` reads the saved TSX and state through `useSavedView` (Task 8, backed by `GET /projects/{slug}/views/{name}` from Task 6):

```tsx
function CanvasCardView({
  slug,
  view,
  sessionId,
  hub,
}: {
  slug: string;
  view: string;
  sessionId: string;
  hub: SharedStateHub;
}) {
  const saved = useSavedView(slug, view);
  const initialState = useMemo(() => saved.data?.state ?? {}, [saved.data]);
  const datasets = useMemo(() => saved.data?.meta.datasets ?? [], [saved.data]);
  const own = useMemo(() => [], []);
  if (saved.data === undefined) return null;
  return (
    <ViewHost
      viewId={`canvas:${view}`}
      sessionId={sessionId}
      source={saved.data.source}
      initialState={initialState}
      datasets={datasets}
      ownDatasets={own}
      restoreState={null}
      hub={hub}
      title={`Canvas card ${view}`}
    />
  );
}
```

`web/src/host/components/SavedItems.tsx` lists datasets (name, mode, rows, validated badge with reason, description) and views (name, datasets, component) in two plain lists; it is the "Saved" tab and takes `{ project: Project }` only.

`web/src/host/containers/ProjectPage.tsx`:

```tsx
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useProject } from "../api/hooks";
import { SavedItems } from "../components/SavedItems";
import { CanvasPage } from "./CanvasPage";

interface ProjectPageProps {
  slug: string;
  sessionId: string | null;
  onBack: () => void;
}

export function ProjectPage({ slug, sessionId, onBack }: ProjectPageProps) {
  const project = useProject(slug);
  const [tab, setTab] = useState<"saved" | "canvas">("canvas");
  if (project.data === undefined)
    return (
      <main className="flex-1 p-8 text-sm text-muted-foreground">Loading</main>
    );
  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <div className="flex items-center gap-4 border-b border-border px-8 py-3">
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back to session
        </Button>
        <h1 className="text-base font-medium">{project.data.meta.name}</h1>
        <div role="tablist" className="ml-auto flex gap-1">
          {(["saved", "canvas"] as const).map((t) => (
            <button
              key={t}
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className="rounded-md px-2 py-1 text-sm aria-selected:bg-muted aria-selected:text-primary"
            >
              {t === "saved" ? "Saved" : "Canvas"}
            </button>
          ))}
        </div>
      </div>
      {tab === "saved" && <SavedItems project={project.data} />}
      {tab === "canvas" &&
        (sessionId === null ? (
          <p className="p-8 text-sm text-muted-foreground">
            Open a session first; canvas cards query through it.
          </p>
        ) : (
          <CanvasPage project={project.data} sessionId={sessionId} />
        ))}
    </main>
  );
}
```

`App.tsx` renders `ProjectPage` for `page.kind === "project"` with the active session id lifted into `App` (move `activeId` state from `SessionPage` up to `App` and pass it down).

- [ ] **Step 4: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && npm run build
git add web && git commit -m "feat: add the project canvas with draggable, resizable cards"
```

---

### Task 11: Linked keys across cards

**Files:**

- Create: `web/src/host/bridge/SharedStateHub.ts`
- Test: `web/src/host/bridge/SharedStateHub.test.ts`

**Interfaces:**

- Produces: `SharedStateHub` with `register(cardId, initial, restore): () => void` and `report(cardId, state): void`; `sharedKeys(state): JsonObject` (entries whose key starts with `shared:`).
- Consumes: `ViewHost` (Task 8) calls `register` after mounting and `report` on every `stateChanged`.

- [ ] **Step 1: Failing test**

`web/src/host/bridge/SharedStateHub.test.ts`:

```ts
import { describe, expect, it, vi } from "vitest";
import { SharedStateHub, sharedKeys } from "./SharedStateHub";

describe("SharedStateHub", () => {
  it("extracts shared keys", () => {
    expect(sharedKeys({ "shared:ticker": "AAPL", limit: 5 })).toEqual({
      "shared:ticker": "AAPL",
    });
  });

  it("fans a shared change out to every other card merged with its own state", () => {
    const hub = new SharedStateHub();
    const a = vi.fn();
    const b = vi.fn();
    hub.register("a", { "shared:ticker": "AAPL", limit: 5 }, a);
    hub.register("b", { "shared:ticker": "MSFT", sort: null }, b);
    expect(a).not.toHaveBeenCalled();
    expect(b).not.toHaveBeenCalled();
    hub.report("a", { "shared:ticker": "NVDA", limit: 9 });
    expect(a).not.toHaveBeenCalled();
    expect(b).toHaveBeenCalledWith({ "shared:ticker": "NVDA", sort: null });
  });

  it("uses the latest reported state as the merge base and stops after unregister", () => {
    const hub = new SharedStateHub();
    const b = vi.fn();
    hub.register("a", {}, () => undefined);
    const off = hub.register("b", { x: 1 }, b);
    hub.report("b", { x: 2 });
    hub.report("a", { "shared:k": true });
    expect(b).toHaveBeenLastCalledWith({ x: 2, "shared:k": true });
    off();
    hub.report("a", { "shared:k": false });
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("does nothing when the change carries no shared keys", () => {
    const hub = new SharedStateHub();
    const b = vi.fn();
    hub.register("a", {}, () => undefined);
    hub.register("b", {}, b);
    hub.report("a", { limit: 3 });
    expect(b).not.toHaveBeenCalled();
  });
});
```

- [ ] **Step 2: Implement**

`web/src/host/bridge/SharedStateHub.ts`:

```ts
import type { JsonObject } from "@/shared/json";

interface Card {
  last: JsonObject;
  restore: (state: JsonObject) => void;
}

export function sharedKeys(state: JsonObject): JsonObject {
  return Object.fromEntries(
    Object.entries(state).filter(([key]) => key.startsWith("shared:")),
  );
}

/** Fans `shared:` view-state keys out across the cards of one canvas. */
export class SharedStateHub {
  private readonly cards = new Map<string, Card>();

  register(
    cardId: string,
    initial: JsonObject,
    restore: (state: JsonObject) => void,
  ): () => void {
    this.cards.set(cardId, { last: initial, restore });
    return () => {
      this.cards.delete(cardId);
    };
  }

  report(cardId: string, state: JsonObject): void {
    const card = this.cards.get(cardId);
    if (card !== undefined) card.last = state;
    const shared = sharedKeys(state);
    if (Object.keys(shared).length === 0) return;
    for (const [id, other] of this.cards) {
      if (id === cardId) continue;
      other.last = { ...other.last, ...shared };
      other.restore(other.last);
    }
  }
}
```

The receiving card's `restore` replaces its store without firing `stateChanged`, so the hub never echoes.

- [ ] **Step 3: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test
git add web && git commit -m "feat: link shared view-state keys across canvas cards"
```

---

### Task 12: End-to-end flow, docs

**Files:**

- Create: `tests/e2e/test_projects.py`
- Modify: `docs/working-state.md`, `docs/context/code-map.md`, `docs/context/decisions.md`, `docs/context/glossary.md`, `docs/open-items.md`, `README.md`

**Interfaces:**

- Consumes: the Stage 3 `serve` fixture in `tests/e2e/conftest.py` and its helpers.

- [ ] **Step 1: Playwright test**

`tests/e2e/test_projects.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import Page, expect

from quarry.agent.types import AssistantTurn, ToolCall
from tests.e2e.conftest import RunningServer
from tests.e2e.test_ui import end, open_session, py, render

PRICES = "df = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03'], 'px': [101.5, 102.25]})"
TIDY = "import polars as pl\n" + PRICES + "\n"


def test_save_recall_and_canvas(serve: Callable[[list[AssistantTurn]], RunningServer], page: Page) -> None:
    server = serve([py("c1", PRICES), render("c2", "data-table"), end("Here is df"), end(TIDY)])
    open_session(page, server, "show df")
    expect(page.get_by_text("Here is df")).to_be_visible(timeout=30_000)

    page.on("dialog", lambda d: d.accept("Momentum") if d.type == "prompt" else d.accept())
    page.get_by_role("button", name="New project").click()
    expect(page.get_by_role("button", name="Momentum", exact=True)).to_be_visible()

    page.get_by_role("button", name="Pin to canvas").click()
    page.get_by_label("Name").fill("closes")
    page.get_by_role("dialog").get_by_role("button", name="Save view").click()
    expect(page.get_by_text("Saved view closes")).to_be_visible(timeout=60_000)

    page.get_by_role("button", name="New session").click()
    page.get_by_role("button", name="Momentum", exact=True).click()
    page.get_by_role("button", name="Recall df", exact=True).click()
    expect(page.get_by_text("Recall df from Momentum")).to_be_visible(timeout=30_000)
    expect(page.get_by_text("Done", exact=True)).to_be_visible(timeout=30_000)

    page.get_by_role("button", name="Open Momentum").click()
    page.get_by_role("tab", name="Canvas").click()
    frame = page.frame_locator("iframe[title='Canvas card closes']")
    expect(frame.get_by_text("102.25")).to_be_visible(timeout=30_000)
```

The `render` helper in `tests/e2e/test_ui.py` uses `datasets: ["df"]`, which this test relies on. The tidy turn is the fourth `FakeProvider` turn; the save calls the provider once with `tools=[]`.

- [ ] **Step 2: Docs**

- `docs/working-state.md`: Stage 4 row to "In progress" with the branch, latest verification, next actions.
- `docs/context/code-map.md`: a `quarry.projects` section (`models`, `files`, `store`, `recipe`, `tidy`, `validate`) and rows for `server/projects.py`, `server/project_routes.py`; a `web/src/host` addition for `ViewHost`, `SharedStateHub`, `CanvasPage`.
- `docs/context/decisions.md`, new "Projects" section, one bullet each: tidied script validated first with the raw script as fallback; validation uses `describe` on both kernels, never `step.datasets`; recall overwrites an existing name after a confirm; the canvas binds to the active session and card state is ephemeral per visit; `shared:` keys fan out through the host with no seeding; `react-grid-layout` v2 with its own types.
- `docs/context/glossary.md`: Project, Recipe, Pinned, Recall step, Canvas card, Linked key.
- `docs/open-items.md`: resolve the Stage 4 items this plan covers (see below) and file what it defers.
- `README.md`: a "Projects (Stage 4)" section: save, recall, canvas, where files live.

- [ ] **Step 3: Verify and commit**

```bash
cd web && npm run build && cd ..
uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src
npx prettier --prose-wrap always --write README.md docs/working-state.md docs/context/*.md docs/open-items.md
git add tests docs README.md && git commit -m "test: cover save, recall and canvas end to end"
```

---

## Open items

From `docs/open-items.md`, Stage 4 section, as filed by the Stage 1 reviews:

- **Lineage through SQL strings** (`sql_local("... FROM recent")` is not a read): deferred to Stage 5. A recipe that misses a source step fails validation (`NameError` in the scratch kernel) and is saved unvalidated with that reason, so the gap is visible, not silent. Record the deferral.
- **Other lineage blind spots** (helpers bound without `def`, attribute mutation): same treatment, same deferral.
- **Failed step's in-place mutation as a write**: Task 2 keeps only `ok` runs of each step, so a failed run's mutation is never in a recipe; a successful earlier run's mutation is. That is the decision; record it.
- **Kernel working directory and relative snapshot paths**: Task 5 passes the absolute `parquet_path`, and Task 7 generates recall code with the absolute path. Resolved for projects.
- **`close()` after `shutdown()` cutting an in-flight snapshot short**: the pinned snapshot runs on the session kernel inside `hold`, which does not close the kernel; the scratch kernel never snapshots. Not blocking; leave the item filed.

## Done when

- A dataset saved live or pinned from a finished session has `recipe.py`, `recipe.raw.py` and `meta.json` on disk with `validated` reflecting a real scratch-kernel run, and `data.parquet` when pinned.
- Saving a view saves its datasets first (one mode prompt), its TSX, and its latest snapshot state.
- Recall creates a `recall` step with `runs` filled; restart replays it; recalled views mount with their saved state.
- The rail lists projects with their datasets and views; the project page has a Saved tab and a Canvas tab with draggable, resizable cards persisted in `project.json`; "Pin to canvas" appends a card.
- Changing a `shared:` key in one card restores the other cards with that value.
- Saving while a step runs returns 409 at once.
- `npm run check`, `npm test`, `npm run build`, `uv run pytest` (including `tests/e2e`), ruff and mypy pass locally and in CI.
