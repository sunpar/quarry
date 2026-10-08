# Quarry Stage 1: Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Python core of Quarry: configuration, the query spec compiler with polars, DuckDB, and source targets, lineage capture, the kernel subprocess with its JSON-RPC client, and the data layer, all usable from a REPL and fully tested.

**Architecture:** A `quarry` package under `src/` with four subpackages. `quarry.query` is pure: spec models and three compile targets. `quarry.kernel` is the subprocess that holds datasets and executes code, plus the client the server will use to drive it. `quarry.data` builds the namespace the kernel exposes (loaders, SQL Server, parquet catalog). `quarry.config` loads TOML plus environment. Nothing in Stage 1 knows about HTTP, agents, or the browser.

**Tech Stack:** Python 3.11+, uv, polars >= 1.0, duckdb >= 1.0, pydantic >= 2, pyarrow, arrow-odbc (optional extra), pytest, ruff, mypy.

**Spec:** `docs/superpowers/specs/2026-10-08-quarry-design.md` (sections 5, 6, 7, 11, 14, 15 stage 1, 17)

## Global Constraints

- Python 3.11 or newer. `python` does not exist on the dev Mac; use `uv run` or `.venv/bin/python`.
- Every function signature is fully annotated, parameters and return. Built-in generics only (`list[str]`, `dict[str, int]`), `X | None` not `Optional`.
- Data containers are `@dataclass(slots=True)` or pydantic `BaseModel`. No stringly-typed dicts crossing module boundaries.
- No bare `except:` and no `except Exception: pass`.
- `pathlib.Path` for every path. `zip(strict=True)`. Timezone-aware datetimes.
- Every file is run through `ruff format` and `ruff check --fix` before commit. mypy errors are bugs.
- Query spec evaluation order is fixed: filters, then group-by with aggs or pivot (never both), then sort, then offset and limit, then select.
- Query results are capped at `row_cap` rows (default 50000) regardless of the spec.
- The kernel never raises across the socket. Every method returns a result or a structured error.
- Dataset types are exactly `polars.DataFrame`, `polars.LazyFrame`, and `duckdb.DuckDBPyRelation`.
- Package layout: `src/quarry/{config.py, query/, kernel/, data/}`, tests under `tests/`.

## Review Focus

Failure modes the spec implies that a researcher will hit. Each has a pinned test in the owning task.

1. A filter or select names a column that does not exist. Expected: a `QueryError` naming the column, not a polars or DuckDB traceback. Pinned in Task 4 and Task 5.
2. A string literal is compared against a Date or Datetime column (every date filter from the UI arrives as an ISO string). Expected: the comparison works on both targets. Pinned in Task 4 and Task 5.
3. Step code rebinds a dataset name to something that is not a dataset (`returns = None`, `del returns`). Expected: the name leaves the registry and the step's `writes` does not include it. Pinned in Task 7 and Task 8.
4. Step code prints megabytes of output. Expected: only the last 4 KB is returned and the kernel stays responsive. Pinned in Task 9.
5. A column name contains a space or a double quote. Expected: the SQL target quotes it correctly and the polars target passes it through. Pinned in Task 5.

---

### Task 1: Package scaffold

**Files:**

- Create: `pyproject.toml`
- Create: `src/quarry/__init__.py`
- Create: `src/quarry/py.typed`
- Create: `tests/__init__.py`
- Create: `tests/test_package.py`
- Create: `.gitignore`
- Create: `.github/workflows/ci.yml`
- Create: `README.md`

**Interfaces:**

- Produces: an installable `quarry` package with `quarry.__version__: str`, and the commands `uv run pytest`, `uv run ruff check src tests`, `uv run ruff format --check src tests`, `uv run mypy src`.

- [ ] **Step 1: Write pyproject.toml**

```toml
[project]
name = "quarry"
version = "0.1.0"
description = "Agentic data exploration for quant researchers"
readme = "README.md"
requires-python = ">=3.11"
dependencies = [
    "polars>=1.0",
    "duckdb>=1.0",
    "pydantic>=2.0",
    "pyarrow>=15.0",
]

[project.optional-dependencies]
mssql = ["arrow-odbc>=4.0"]

[dependency-groups]
dev = [
    "pytest>=8.0",
    "ruff>=0.5",
    "mypy>=1.10",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/quarry"]

[tool.pytest.ini_options]
testpaths = ["tests"]

[tool.ruff]
target-version = "py311"
line-length = 100
src = ["src", "tests"]

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "ANN", "RUF"]
ignore = ["ANN401"]

[tool.ruff.lint.per-file-ignores]
"tests/*" = ["ANN"]

[tool.mypy]
python_version = "3.11"
strict = true
packages = ["quarry"]
mypy_path = "src"

[[tool.mypy.overrides]]
module = ["duckdb", "duckdb.*", "arrow_odbc", "pyarrow", "pyarrow.*"]
ignore_missing_imports = true
```

- [ ] **Step 2: Write the package init, py.typed, gitignore, README**

`src/quarry/__init__.py`:

```python
"""Quarry: agentic data exploration for quant researchers."""

__version__ = "0.1.0"
```

`src/quarry/py.typed`: empty file.

`.gitignore`:

```
.venv/
__pycache__/
*.pyc
.pytest_cache/
.mypy_cache/
.ruff_cache/
dist/
*.egg-info/
src/quarry/static/
web/node_modules/
web/dist/
```

`README.md`:

```markdown
# Quarry

Agentic data exploration for quant researchers. Design: `docs/superpowers/specs/2026-10-08-quarry-design.md`.

## Development

    uv sync --all-extras
    uv run pytest
    uv run ruff check src tests && uv run ruff format --check src tests
    uv run mypy src
```

- [ ] **Step 3: Write the smoke test**

`tests/__init__.py`: empty file.

`tests/test_package.py`:

```python
import quarry


def test_version_is_string():
    assert isinstance(quarry.__version__, str)
```

- [ ] **Step 4: Install and run the test**

Run: `uv sync --all-extras && uv run pytest -v`
Expected: `test_version_is_string PASSED`

- [ ] **Step 5: Run lint, format, and type check**

Run: `uv run ruff check src tests && uv run ruff format src tests && uv run mypy src`
Expected: no errors. If `arrow-odbc` fails to install because the ODBC driver manager is missing, run `uv sync` without `--all-extras` and note it; the mssql extra is only needed at runtime.

- [ ] **Step 6: Write the CI workflow**

`.github/workflows/ci.yml`:

```yaml
name: ci
on:
  push:
    branches: [main]
  pull_request:
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v3
      - run: uv python install 3.11
      - run: uv sync
      - run: uv run ruff check src tests
      - run: uv run ruff format --check src tests
      - run: uv run mypy src
      - run: uv run pytest -v
```

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml uv.lock src tests .gitignore .github README.md
git commit -m "chore: scaffold quarry package with uv, ruff, mypy, pytest, ci"
```

---

### Task 2: Configuration

**Files:**

- Create: `src/quarry/config.py`
- Test: `tests/test_config.py`

**Interfaces:**

- Produces:
  - `class ProviderConfig(BaseModel)`: `name: Literal["anthropic", "openai"] = "anthropic"`, `model: str = "claude-sonnet-5-5"`, `api_key_file: Path | None = None`
  - `class DataConfig(BaseModel)`: `parquet_root: Path | None = None`, `mssql_dsn: str = ""`, `row_cap: int = 50000`, `kernel_memory_mb: int = 0`
  - `class LibrariesConfig(BaseModel)`: `team_components: Path | None = None`, `highcharts_license: str = ""`, `highcharts_path: Path | None = None`, `scichart_license: str = ""`, `scichart_path: Path | None = None`
  - `class QuarryConfig(BaseModel)`: `root: Path`, `provider: ProviderConfig`, `data: DataConfig`, `libraries: LibrariesConfig`
  - `def load_config(root: Path, env: Mapping[str, str] | None = None) -> QuarryConfig`: reads `root / "config.toml"` if present, applies `QUARRY_MSSQL_DSN` from env over the file value, returns defaults when the file is absent.
  - `def api_key(config: QuarryConfig, env: Mapping[str, str] | None = None) -> str`: returns `QUARRY_ANTHROPIC_API_KEY` or `QUARRY_OPENAI_API_KEY` by provider name, else reads `api_key_file`, refusing files with group or world permission bits. Raises `ConfigError`.

- [ ] **Step 1: Write the failing tests**

`tests/test_config.py`:

```python
import os
from pathlib import Path

import pytest

from quarry.config import ConfigError, QuarryConfig, api_key, load_config


def test_defaults_when_no_file(tmp_path: Path):
    cfg = load_config(tmp_path, env={})
    assert cfg.root == tmp_path
    assert cfg.provider.name == "anthropic"
    assert cfg.data.row_cap == 50000
    assert cfg.data.parquet_root is None


def test_reads_toml(tmp_path: Path):
    (tmp_path / "config.toml").write_text(
        '[provider]\nname = "openai"\nmodel = "gpt-5"\n'
        '[data]\nparquet_root = "/data/cache"\nrow_cap = 100\n'
    )
    cfg = load_config(tmp_path, env={})
    assert cfg.provider.name == "openai"
    assert cfg.provider.model == "gpt-5"
    assert cfg.data.parquet_root == Path("/data/cache")
    assert cfg.data.row_cap == 100


def test_env_overrides_mssql_dsn(tmp_path: Path):
    (tmp_path / "config.toml").write_text('[data]\nmssql_dsn = "file-dsn"\n')
    cfg = load_config(tmp_path, env={"QUARRY_MSSQL_DSN": "env-dsn"})
    assert cfg.data.mssql_dsn == "env-dsn"


def test_api_key_from_env(tmp_path: Path):
    cfg = load_config(tmp_path, env={})
    assert api_key(cfg, env={"QUARRY_ANTHROPIC_API_KEY": "sk-test"}) == "sk-test"


def test_api_key_from_owner_only_file(tmp_path: Path):
    key_file = tmp_path / "anthropic.key"
    key_file.write_text("sk-file\n")
    os.chmod(key_file, 0o600)
    (tmp_path / "config.toml").write_text(f'[provider]\napi_key_file = "{key_file}"\n')
    cfg = load_config(tmp_path, env={})
    assert api_key(cfg, env={}) == "sk-file"


def test_api_key_refuses_group_readable_file(tmp_path: Path):
    key_file = tmp_path / "anthropic.key"
    key_file.write_text("sk-file\n")
    os.chmod(key_file, 0o640)
    (tmp_path / "config.toml").write_text(f'[provider]\napi_key_file = "{key_file}"\n')
    cfg = load_config(tmp_path, env={})
    with pytest.raises(ConfigError, match="permissions"):
        api_key(cfg, env={})


def test_api_key_missing_raises(tmp_path: Path):
    cfg = QuarryConfig(root=tmp_path)
    with pytest.raises(ConfigError, match="QUARRY_ANTHROPIC_API_KEY"):
        api_key(cfg, env={})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.config'`

- [ ] **Step 3: Write the implementation**

`src/quarry/config.py`:

```python
"""Quarry configuration: TOML file under the root plus environment overrides."""

from __future__ import annotations

import os
import stat
import tomllib
from collections.abc import Mapping
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, Field

CONFIG_FILENAME: Final = "config.toml"
ENV_MSSQL_DSN: Final = "QUARRY_MSSQL_DSN"
ENV_API_KEY: Final[dict[str, str]] = {
    "anthropic": "QUARRY_ANTHROPIC_API_KEY",
    "openai": "QUARRY_OPENAI_API_KEY",
}


class ConfigError(Exception):
    """Raised for an unusable configuration."""


class ProviderConfig(BaseModel):
    name: Literal["anthropic", "openai"] = "anthropic"
    model: str = "claude-sonnet-5-5"
    api_key_file: Path | None = None


class DataConfig(BaseModel):
    parquet_root: Path | None = None
    mssql_dsn: str = ""
    row_cap: int = 50000
    kernel_memory_mb: int = 0


class LibrariesConfig(BaseModel):
    team_components: Path | None = None
    highcharts_license: str = ""
    highcharts_path: Path | None = None
    scichart_license: str = ""
    scichart_path: Path | None = None


class QuarryConfig(BaseModel):
    root: Path
    provider: ProviderConfig = Field(default_factory=ProviderConfig)
    data: DataConfig = Field(default_factory=DataConfig)
    libraries: LibrariesConfig = Field(default_factory=LibrariesConfig)


def load_config(root: Path, env: Mapping[str, str] | None = None) -> QuarryConfig:
    environment = os.environ if env is None else env
    path = root / CONFIG_FILENAME
    raw: dict[str, object] = {}
    if path.exists():
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    config = QuarryConfig.model_validate({"root": root, **raw})
    dsn = environment.get(ENV_MSSQL_DSN)
    if dsn:
        config = config.model_copy(update={"data": config.data.model_copy(update={"mssql_dsn": dsn})})
    return config


def api_key(config: QuarryConfig, env: Mapping[str, str] | None = None) -> str:
    environment = os.environ if env is None else env
    env_name = ENV_API_KEY[config.provider.name]
    from_env = environment.get(env_name)
    if from_env:
        return from_env
    key_file = config.provider.api_key_file
    if key_file is None:
        raise ConfigError(f"No API key: set {env_name} or provider.api_key_file")
    return _read_owner_only(key_file.expanduser())


def _read_owner_only(path: Path) -> str:
    if not path.exists():
        raise ConfigError(f"API key file not found: {path}")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & (stat.S_IRWXG | stat.S_IRWXO):
        raise ConfigError(f"API key file {path} has group or world permissions; use chmod 600")
    key = path.read_text().strip()
    if not key:
        raise ConfigError(f"API key file is empty: {path}")
    return key
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: 7 passed

- [ ] **Step 5: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/config.py tests/test_config.py
git commit -m "feat(config): load config.toml with env overrides and owner-only key files"
```

---

### Task 3: Query spec models

**Files:**

- Create: `src/quarry/query/__init__.py`
- Create: `src/quarry/query/spec.py`
- Test: `tests/query/__init__.py`
- Test: `tests/query/test_spec.py`

**Interfaces:**

- Produces (all in `quarry.query.spec`, re-exported from `quarry.query`):
  - `FilterOp = Literal["eq","ne","lt","le","gt","ge","in","not_in","between","contains","starts_with","is_null","not_null"]`
  - `AggFn = Literal["sum","mean","min","max","count","median","std","first","last"]`
  - `PivotAggFn = Literal["sum","mean","min","max","count","median","first","last"]`
  - `Json = JsonValue` (pydantic's recursive JSON type, re-exported so no other module imports pydantic for it)
  - `class Filter(BaseModel)`: `col: str`, `op: FilterOp`, `value: Json = None`
  - `class Agg(BaseModel)`: `col: str`, `fn: AggFn`, `alias: str | None = None`; property `name -> str` returning `alias or f"{col}_{fn}"`
  - `class Pivot(BaseModel)`: `index: list[str]`, `columns: str`, `values: str`, `agg: PivotAggFn`
  - `class Sort(BaseModel)`: `col: str`, `desc: bool = False`
  - `class QuerySpec(BaseModel)`: `dataset: str`, `select: list[str] | None`, `filters: list[Filter]`, `group_by: list[str] | None`, `aggs: list[Agg]`, `pivot: Pivot | None`, `sort: list[Sort]`, `limit: int | None`, `offset: int = 0`, `format: Literal["json","arrow"] = "json"`
  - Validation errors (pydantic `ValidationError`): `group_by` together with `pivot`; `aggs` without `group_by`; `group_by` without `aggs`; `between` without a two-element list value; `in`/`not_in` without a list value; `is_null`/`not_null` with a value; negative `offset` or non-positive `limit`.
  - `class QueryError(Exception)`: raised by compile targets for a column that does not exist in the dataset. Attribute `column: str`.

- [ ] **Step 1: Write the failing tests**

`tests/query/__init__.py`: empty.

`tests/query/test_spec.py`:

```python
import pytest
from pydantic import ValidationError

from quarry.query import Agg, Filter, Pivot, QuerySpec


def test_minimal_spec():
    spec = QuerySpec(dataset="returns")
    assert spec.filters == []
    assert spec.offset == 0
    assert spec.format == "json"


def test_agg_default_name():
    assert Agg(col="ret", fn="mean").name == "ret_mean"
    assert Agg(col="ret", fn="mean", alias="avg").name == "avg"


def test_group_by_and_pivot_rejected():
    with pytest.raises(ValidationError, match="group_by"):
        QuerySpec(
            dataset="r",
            group_by=["a"],
            aggs=[Agg(col="x", fn="sum")],
            pivot=Pivot(index=["a"], columns="b", values="x", agg="sum"),
        )


def test_aggs_require_group_by():
    with pytest.raises(ValidationError, match="group_by"):
        QuerySpec(dataset="r", aggs=[Agg(col="x", fn="sum")])


def test_group_by_requires_aggs():
    with pytest.raises(ValidationError, match="aggs"):
        QuerySpec(dataset="r", group_by=["a"])


def test_between_requires_pair():
    with pytest.raises(ValidationError, match="between"):
        Filter(col="x", op="between", value=[1])
    Filter(col="x", op="between", value=[1, 2])


def test_in_requires_list():
    with pytest.raises(ValidationError, match="list"):
        Filter(col="x", op="in", value=1)


def test_null_ops_take_no_value():
    with pytest.raises(ValidationError, match="value"):
        Filter(col="x", op="is_null", value=1)
    Filter(col="x", op="not_null")


def test_limit_and_offset_bounds():
    with pytest.raises(ValidationError):
        QuerySpec(dataset="r", limit=0)
    with pytest.raises(ValidationError):
        QuerySpec(dataset="r", offset=-1)


def test_round_trips_json():
    spec = QuerySpec(
        dataset="r",
        filters=[Filter(col="sector", op="eq", value="tech")],
        group_by=["sector"],
        aggs=[Agg(col="ret", fn="mean")],
        sort=[{"col": "ret_mean", "desc": True}],
        limit=10,
    )
    assert QuerySpec.model_validate_json(spec.model_dump_json()) == spec
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/query/test_spec.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.query'`

- [ ] **Step 3: Write the implementation**

`src/quarry/query/spec.py`:

```python
"""The declarative query language under every view and every to-code action."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, JsonValue, model_validator

FilterOp = Literal[
    "eq", "ne", "lt", "le", "gt", "ge", "in", "not_in",
    "between", "contains", "starts_with", "is_null", "not_null",
]
AggFn = Literal["sum", "mean", "min", "max", "count", "median", "std", "first", "last"]
PivotAggFn = Literal["sum", "mean", "min", "max", "count", "median", "first", "last"]
Json = JsonValue

LIST_OPS: frozenset[str] = frozenset({"in", "not_in"})
NULL_OPS: frozenset[str] = frozenset({"is_null", "not_null"})


class QueryError(Exception):
    """A spec references a column the dataset does not have."""

    def __init__(self, column: str, dataset: str) -> None:
        super().__init__(f"Column {column!r} does not exist in dataset {dataset!r}")
        self.column = column
        self.dataset = dataset


class Filter(BaseModel):
    col: str
    op: FilterOp
    value: Json = None

    @model_validator(mode="after")
    def _check_value_shape(self) -> Filter:
        if self.op == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between requires a two-element list value")
        elif self.op in LIST_OPS:
            if not isinstance(self.value, list):
                raise ValueError(f"{self.op} requires a list value")
        elif self.op in NULL_OPS and self.value is not None:
            raise ValueError(f"{self.op} takes no value")
        return self


class Agg(BaseModel):
    col: str
    fn: AggFn
    alias: str | None = None

    @property
    def name(self) -> str:
        return self.alias or f"{self.col}_{self.fn}"


class Pivot(BaseModel):
    index: list[str]
    columns: str
    values: str
    agg: PivotAggFn


class Sort(BaseModel):
    col: str
    desc: bool = False


class QuerySpec(BaseModel):
    dataset: str
    select: list[str] | None = None
    filters: list[Filter] = Field(default_factory=list)
    group_by: list[str] | None = None
    aggs: list[Agg] = Field(default_factory=list)
    pivot: Pivot | None = None
    sort: list[Sort] = Field(default_factory=list)
    limit: int | None = Field(default=None, gt=0)
    offset: int = Field(default=0, ge=0)
    format: Literal["json", "arrow"] = "json"

    @model_validator(mode="after")
    def _check_shape(self) -> QuerySpec:
        if self.group_by is not None and self.pivot is not None:
            raise ValueError("group_by and pivot cannot both be set")
        if self.aggs and self.group_by is None:
            raise ValueError("aggs require group_by")
        if self.group_by is not None and not self.aggs:
            raise ValueError("group_by requires at least one entry in aggs")
        return self
```

`src/quarry/query/__init__.py`:

```python
from quarry.query.spec import (
    Agg,
    AggFn,
    Filter,
    FilterOp,
    Json,
    Pivot,
    PivotAggFn,
    QueryError,
    QuerySpec,
    Sort,
)

__all__ = [
    "Agg",
    "AggFn",
    "Filter",
    "FilterOp",
    "Json",
    "Pivot",
    "PivotAggFn",
    "QueryError",
    "QuerySpec",
    "Sort",
]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/query/test_spec.py -v`
Expected: 10 passed

- [ ] **Step 5: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/query tests/query
git commit -m "feat(query): add QuerySpec models with shape validation"
```

---

### Task 4: Polars compile target

**Files:**

- Create: `src/quarry/query/polars_target.py`
- Create: `tests/query/fixtures.py`
- Test: `tests/query/test_polars_target.py`
- Modify: `src/quarry/query/__init__.py` (add `to_polars` export)

**Interfaces:**

- Consumes: `QuerySpec`, `Filter`, `Agg`, `Pivot`, `Sort`, `QueryError` from Task 3.
- Produces:
  - `def to_polars(spec: QuerySpec, frame: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame`: applies the spec in the fixed order and returns a LazyFrame. Raises `QueryError` for unknown columns before touching polars.
  - `def filter_expr(f: Filter, dtype: pl.DataType) -> pl.Expr` and `def agg_expr(a: Agg) -> pl.Expr`: exported for the source target to mirror.
  - `tests/query/fixtures.py` exposes `def trades() -> pl.DataFrame` (the shared fixture frame) and `SPECS: list[QuerySpec]` (the shared equivalence specs). Later tasks reuse both.

- [ ] **Step 1: Write the shared fixture module**

`tests/query/fixtures.py`:

```python
"""Fixture frame and specs shared by every compile-target test."""

from datetime import date

import polars as pl

from quarry.query import Agg, Filter, Pivot, QuerySpec, Sort


def trades() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "date": [date(2024, 1, 2), date(2024, 1, 2), date(2024, 1, 3), date(2024, 1, 3), date(2024, 1, 4)],
            "ticker": ["AAPL", "MSFT", "AAPL", "MSFT", "AAPL"],
            "sector": ["tech", "tech", "tech", "tech", "tech"],
            "ret": [0.01, -0.02, 0.03, 0.00, None],
            "volume": [100, 200, 300, 400, 500],
            "note col": ["a", "b", "c", "d", "e"],
            'q"uote': [1, 2, 3, 4, 5],
        }
    )


SPECS: list[QuerySpec] = [
    QuerySpec(dataset="trades"),
    QuerySpec(dataset="trades", select=["ticker", "ret"]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="eq", value="AAPL")]),
    QuerySpec(dataset="trades", filters=[Filter(col="volume", op="between", value=[200, 400])]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="in", value=["AAPL", "IBM"])]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="not_in", value=["AAPL"])]),
    QuerySpec(dataset="trades", filters=[Filter(col="ret", op="is_null")]),
    QuerySpec(dataset="trades", filters=[Filter(col="ret", op="not_null")]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="contains", value="AP")]),
    QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="starts_with", value="MS")]),
    QuerySpec(dataset="trades", filters=[Filter(col="date", op="ge", value="2024-01-03")]),
    QuerySpec(dataset="trades", filters=[Filter(col="volume", op="gt", value=250), Filter(col="ret", op="ne", value=0.0)]),
    QuerySpec(
        dataset="trades",
        group_by=["ticker"],
        aggs=[
            Agg(col="ret", fn="sum"),
            Agg(col="ret", fn="mean"),
            Agg(col="ret", fn="min"),
            Agg(col="ret", fn="max"),
            Agg(col="ret", fn="count"),
            Agg(col="volume", fn="median"),
            Agg(col="volume", fn="std", alias="vol_sd"),
        ],
        sort=[Sort(col="ticker")],
    ),
    QuerySpec(
        dataset="trades",
        pivot=Pivot(index=["date"], columns="ticker", values="volume", agg="sum"),
        sort=[Sort(col="date")],
    ),
    QuerySpec(dataset="trades", sort=[Sort(col="volume", desc=True)], limit=2),
    QuerySpec(dataset="trades", sort=[Sort(col="volume")], limit=2, offset=1),
    QuerySpec(dataset="trades", select=["note col", 'q"uote'], sort=[Sort(col='q"uote', desc=True)]),
]
```

- [ ] **Step 2: Write the failing tests**

`tests/query/test_polars_target.py`:

```python
from datetime import date

import polars as pl
import pytest

from quarry.query import Agg, Filter, QueryError, QuerySpec, Sort
from quarry.query.polars_target import to_polars
from tests.query.fixtures import SPECS, trades


def test_passthrough_returns_lazyframe():
    out = to_polars(QuerySpec(dataset="trades"), trades())
    assert isinstance(out, pl.LazyFrame)
    assert out.collect().height == 5


def test_filter_eq():
    spec = QuerySpec(dataset="trades", filters=[Filter(col="ticker", op="eq", value="AAPL")])
    assert to_polars(spec, trades()).collect().height == 3


def test_string_literal_against_date_column():
    spec = QuerySpec(dataset="trades", filters=[Filter(col="date", op="ge", value="2024-01-03")])
    out = to_polars(spec, trades()).collect()
    assert out["date"].min() == date(2024, 1, 3)
    assert out.height == 3


def test_group_by_agg_names():
    spec = QuerySpec(
        dataset="trades",
        group_by=["ticker"],
        aggs=[Agg(col="ret", fn="mean"), Agg(col="volume", fn="sum", alias="vol")],
        sort=[Sort(col="ticker")],
    )
    out = to_polars(spec, trades()).collect()
    assert out.columns == ["ticker", "ret_mean", "vol"]
    assert out["vol"].to_list() == [900, 600]


def test_pivot():
    spec = QuerySpec(
        dataset="trades",
        pivot={"index": ["date"], "columns": "ticker", "values": "volume", "agg": "sum"},
        sort=[Sort(col="date")],
    )
    out = to_polars(spec, trades()).collect()
    assert out.columns == ["date", "AAPL", "MSFT"]
    assert out["AAPL"].to_list() == [100, 300, 500]


def test_sort_offset_limit_select_order():
    spec = QuerySpec(
        dataset="trades",
        select=["ticker"],
        sort=[Sort(col="volume", desc=True)],
        limit=2,
        offset=1,
    )
    out = to_polars(spec, trades()).collect()
    assert out.columns == ["ticker"]
    assert out["ticker"].to_list() == ["MSFT", "AAPL"]


def test_unknown_filter_column_raises_query_error():
    spec = QuerySpec(dataset="trades", filters=[Filter(col="nope", op="eq", value=1)])
    with pytest.raises(QueryError) as info:
        to_polars(spec, trades())
    assert info.value.column == "nope"


def test_unknown_select_column_raises_query_error():
    with pytest.raises(QueryError):
        to_polars(QuerySpec(dataset="trades", select=["missing"]), trades())


def test_lazy_input_accepted():
    out = to_polars(QuerySpec(dataset="trades", limit=1), trades().lazy()).collect()
    assert out.height == 1


@pytest.mark.parametrize("spec", SPECS, ids=[s.model_dump_json() for s in SPECS])
def test_every_fixture_spec_compiles(spec: QuerySpec):
    to_polars(spec, trades()).collect()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/query/test_polars_target.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.query.polars_target'`

- [ ] **Step 4: Write the implementation**

`src/quarry/query/polars_target.py`:

```python
"""Compile a QuerySpec to a polars LazyFrame."""

from __future__ import annotations

from datetime import date, datetime

import polars as pl

from quarry.query.spec import Agg, Filter, Json, Pivot, QueryError, QuerySpec


def to_polars(spec: QuerySpec, frame: pl.DataFrame | pl.LazyFrame) -> pl.LazyFrame:
    lf = frame.lazy()
    schema = lf.collect_schema()
    _check_columns(spec, set(schema.names()))
    if spec.filters:
        lf = lf.filter(pl.all_horizontal([filter_expr(f, schema[f.col]) for f in spec.filters]))
    if spec.group_by is not None:
        lf = lf.group_by(spec.group_by).agg([agg_expr(a) for a in spec.aggs])
    elif spec.pivot is not None:
        lf = _pivot(lf, spec.pivot)
    if spec.sort:
        lf = lf.sort([s.col for s in spec.sort], descending=[s.desc for s in spec.sort])
    if spec.limit is not None or spec.offset:
        lf = lf.slice(spec.offset, spec.limit)
    if spec.select is not None:
        lf = lf.select(spec.select)
    return lf


def filter_expr(f: Filter, dtype: pl.DataType) -> pl.Expr:
    col = pl.col(f.col)
    match f.op:
        case "eq":
            return col == _lit(f.value, dtype)
        case "ne":
            return col != _lit(f.value, dtype)
        case "lt":
            return col < _lit(f.value, dtype)
        case "le":
            return col <= _lit(f.value, dtype)
        case "gt":
            return col > _lit(f.value, dtype)
        case "ge":
            return col >= _lit(f.value, dtype)
        case "in":
            return col.is_in(_py_list(f.value, dtype))
        case "not_in":
            return ~col.is_in(_py_list(f.value, dtype))
        case "between":
            lo, hi = _py_list(f.value, dtype)
            return col.is_between(pl.lit(lo), pl.lit(hi))
        case "contains":
            return col.str.contains(str(f.value), literal=True)
        case "starts_with":
            return col.str.starts_with(str(f.value))
        case "is_null":
            return col.is_null()
        case "not_null":
            return col.is_not_null()


def agg_expr(a: Agg) -> pl.Expr:
    col = pl.col(a.col)
    match a.fn:
        case "sum":
            expr = col.sum()
        case "mean":
            expr = col.mean()
        case "min":
            expr = col.min()
        case "max":
            expr = col.max()
        case "count":
            expr = col.count()
        case "median":
            expr = col.median()
        case "std":
            expr = col.std()
        case "first":
            expr = col.first()
        case "last":
            expr = col.last()
    return expr.alias(a.name)


def _pivot(lf: pl.LazyFrame, pivot: Pivot) -> pl.LazyFrame:
    wide = lf.collect().pivot(
        on=pivot.columns,
        index=pivot.index,
        values=pivot.values,
        aggregate_function=pivot.agg,
    )
    return wide.lazy()


def _lit(value: Json, dtype: pl.DataType) -> pl.Expr:
    return pl.lit(_py(value, dtype))


def _py(value: Json, dtype: pl.DataType) -> object:
    """Convert a JSON literal to the Python value polars should compare against."""
    if isinstance(value, str):
        if dtype == pl.Date:
            return date.fromisoformat(value)
        if isinstance(dtype, pl.Datetime):
            return datetime.fromisoformat(value)
    return value


def _py_list(value: Json, dtype: pl.DataType) -> list[object]:
    if not isinstance(value, list):
        raise TypeError("expected a list value")
    return [_py(item, dtype) for item in value]


def _check_columns(spec: QuerySpec, names: set[str]) -> None:
    referenced: list[str] = [f.col for f in spec.filters]
    if spec.group_by is not None:
        referenced += spec.group_by
        referenced += [a.col for a in spec.aggs]
    if spec.pivot is not None:
        referenced += [*spec.pivot.index, spec.pivot.columns, spec.pivot.values]
    for name in referenced:
        if name not in names:
            raise QueryError(name, spec.dataset)
    # sort and select run after aggregation, so they may reference agg names.
    produced = names | {a.name for a in spec.aggs}
    if spec.pivot is None:
        for s in spec.sort:
            if s.col not in produced:
                raise QueryError(s.col, spec.dataset)
        for name in spec.select or []:
            if name not in produced:
                raise QueryError(name, spec.dataset)
```

Add to `src/quarry/query/__init__.py`:

```python
from quarry.query.polars_target import to_polars
```

and `"to_polars"` to `__all__`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/query/test_polars_target.py -v`
Expected: all pass. `is_in` receives plain Python values (dates already converted), which polars accepts directly.

- [ ] **Step 6: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/query tests/query
git commit -m "feat(query): compile QuerySpec to polars LazyFrame"
```

---

### Task 5: DuckDB SQL compile target with cross-target equivalence

**Files:**

- Create: `src/quarry/query/sql_target.py`
- Test: `tests/query/test_sql_target.py`
- Test: `tests/query/test_equivalence.py`
- Modify: `src/quarry/query/__init__.py` (add `to_sql` export)

**Interfaces:**

- Consumes: spec models from Task 3, `trades()` and `SPECS` from Task 4.
- Produces:
  - `def to_sql(spec: QuerySpec, relation: str, columns: Sequence[str] | None = None) -> str`: returns one DuckDB SQL statement reading from the quoted identifier `relation`. When `columns` is given, unknown references raise `QueryError` before rendering.
  - `def quote_ident(name: str) -> str` and `def quote_literal(value: Json) -> str`.

- [ ] **Step 1: Write the failing unit tests**

`tests/query/test_sql_target.py`:

```python
import duckdb
import pytest

from quarry.query import Agg, Filter, QueryError, QuerySpec, Sort
from quarry.query.sql_target import quote_ident, quote_literal, to_sql
from tests.query.fixtures import trades


def run(sql: str) -> duckdb.DuckDBPyRelation:
    conn = duckdb.connect()
    conn.register("trades", trades())
    return conn.sql(sql)


def test_quote_ident_escapes_double_quotes():
    assert quote_ident('q"uote') == '"q""uote"'
    assert quote_ident("note col") == '"note col"'


def test_quote_literal():
    assert quote_literal("it's") == "'it''s'"
    assert quote_literal(3) == "3"
    assert quote_literal(2.5) == "2.5"
    assert quote_literal(True) == "TRUE"
    assert quote_literal(None) == "NULL"


def test_passthrough():
    sql = to_sql(QuerySpec(dataset="trades"), "trades")
    assert run(sql).pl().height == 5


def test_filter_and_select_with_odd_names():
    spec = QuerySpec(
        dataset="trades",
        select=["note col", 'q"uote'],
        filters=[Filter(col='q"uote', op="gt", value=3)],
        sort=[Sort(col='q"uote', desc=True)],
    )
    out = run(to_sql(spec, "trades")).pl()
    assert out.columns == ["note col", 'q"uote']
    assert out['q"uote'].to_list() == [5, 4]


def test_string_literal_against_date_column():
    spec = QuerySpec(dataset="trades", filters=[Filter(col="date", op="ge", value="2024-01-03")])
    assert run(to_sql(spec, "trades")).pl().height == 3


def test_group_by_aliases():
    spec = QuerySpec(
        dataset="trades",
        group_by=["ticker"],
        aggs=[Agg(col="ret", fn="mean"), Agg(col="volume", fn="sum", alias="vol")],
        sort=[Sort(col="ticker")],
    )
    out = run(to_sql(spec, "trades")).pl()
    assert out.columns == ["ticker", "ret_mean", "vol"]


def test_pivot():
    spec = QuerySpec(
        dataset="trades",
        pivot={"index": ["date"], "columns": "ticker", "values": "volume", "agg": "sum"},
        sort=[Sort(col="date")],
    )
    out = run(to_sql(spec, "trades")).pl()
    assert sorted(out.columns) == ["AAPL", "MSFT", "date"]
    assert out["AAPL"].to_list() == [100, 300, 500]


def test_unknown_column_raises_when_columns_given():
    spec = QuerySpec(dataset="trades", filters=[Filter(col="nope", op="eq", value=1)])
    with pytest.raises(QueryError):
        to_sql(spec, "trades", columns=trades().columns)
```

- [ ] **Step 2: Write the failing equivalence test**

`tests/query/test_equivalence.py`:

```python
"""Every fixture spec must produce the same result on both execution targets."""

import duckdb
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quarry.query import QuerySpec
from quarry.query.polars_target import to_polars
from quarry.query.sql_target import to_sql
from tests.query.fixtures import SPECS, trades


def normalize(df: pl.DataFrame) -> pl.DataFrame:
    df = df.select(sorted(df.columns))
    numeric = [c for c, t in df.schema.items() if t.is_numeric()]
    df = df.with_columns([pl.col(c).cast(pl.Float64) for c in numeric])
    return df.sort(df.columns)


@pytest.mark.parametrize("spec", SPECS, ids=[s.model_dump_json() for s in SPECS])
def test_targets_agree(spec: QuerySpec):
    frame = trades()
    via_polars = to_polars(spec, frame).collect()
    conn = duckdb.connect()
    conn.register("trades", frame)
    via_sql = conn.sql(to_sql(spec, "trades")).pl()
    assert_frame_equal(normalize(via_polars), normalize(via_sql), check_dtypes=False, rtol=1e-9)
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/query/test_sql_target.py tests/query/test_equivalence.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.query.sql_target'`

- [ ] **Step 4: Write the implementation**

`src/quarry/query/sql_target.py`:

```python
"""Compile a QuerySpec to a single DuckDB SQL statement."""

from __future__ import annotations

from collections.abc import Sequence

from quarry.query.spec import Agg, Filter, Json, Pivot, QueryError, QuerySpec

SQL_AGG: dict[str, str] = {
    "sum": "sum",
    "mean": "avg",
    "min": "min",
    "max": "max",
    "count": "count",
    "median": "median",
    "std": "stddev_samp",
    "first": "first",
    "last": "last",
}


def to_sql(spec: QuerySpec, relation: str, columns: Sequence[str] | None = None) -> str:
    if columns is not None:
        _check_columns(spec, set(columns))
    inner = f"SELECT * FROM {quote_ident(relation)}"
    if spec.filters:
        inner += " WHERE " + " AND ".join(filter_sql(f) for f in spec.filters)
    if spec.group_by is not None:
        cols = ", ".join(quote_ident(c) for c in spec.group_by)
        aggs = ", ".join(agg_sql(a) for a in spec.aggs)
        inner = f"SELECT {cols}, {aggs} FROM ({inner}) GROUP BY {cols}"
    elif spec.pivot is not None:
        inner = pivot_sql(inner, spec.pivot)
    projection = "*" if spec.select is None else ", ".join(quote_ident(c) for c in spec.select)
    outer = f"SELECT {projection} FROM ({inner})"
    if spec.sort:
        outer += " ORDER BY " + ", ".join(
            f"{quote_ident(s.col)} {'DESC' if s.desc else 'ASC'}" for s in spec.sort
        )
    if spec.limit is not None:
        outer += f" LIMIT {spec.limit}"
    if spec.offset:
        outer += f" OFFSET {spec.offset}"
    return outer


def filter_sql(f: Filter) -> str:
    col = quote_ident(f.col)
    match f.op:
        case "eq":
            return f"{col} = {quote_literal(f.value)}"
        case "ne":
            return f"{col} <> {quote_literal(f.value)}"
        case "lt":
            return f"{col} < {quote_literal(f.value)}"
        case "le":
            return f"{col} <= {quote_literal(f.value)}"
        case "gt":
            return f"{col} > {quote_literal(f.value)}"
        case "ge":
            return f"{col} >= {quote_literal(f.value)}"
        case "in":
            return f"{col} IN ({_literal_list(f.value)})"
        case "not_in":
            return f"{col} NOT IN ({_literal_list(f.value)})"
        case "between":
            lo, hi = _as_list(f.value)
            return f"{col} BETWEEN {quote_literal(lo)} AND {quote_literal(hi)}"
        case "contains":
            return f"contains({col}, {quote_literal(str(f.value))})"
        case "starts_with":
            return f"starts_with({col}, {quote_literal(str(f.value))})"
        case "is_null":
            return f"{col} IS NULL"
        case "not_null":
            return f"{col} IS NOT NULL"


def agg_sql(a: Agg) -> str:
    return f"{SQL_AGG[a.fn]}({quote_ident(a.col)}) AS {quote_ident(a.name)}"


def pivot_sql(source: str, pivot: Pivot) -> str:
    index = ", ".join(quote_ident(c) for c in pivot.index)
    using = f"{SQL_AGG[pivot.agg]}({quote_ident(pivot.values)})"
    return f"PIVOT ({source}) ON {quote_ident(pivot.columns)} USING {using} GROUP BY {index}"


def quote_ident(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def quote_literal(value: Json) -> str:
    match value:
        case None:
            return "NULL"
        case bool():
            return "TRUE" if value else "FALSE"
        case int() | float():
            return repr(value)
        case str():
            return "'" + value.replace("'", "''") + "'"
        case list():
            return "[" + ", ".join(quote_literal(v) for v in value) + "]"
        case dict():
            raise TypeError("dict literals are not supported in filters")


def _as_list(value: Json) -> list[Json]:
    if not isinstance(value, list):
        raise TypeError("expected a list value")
    return value


def _literal_list(value: Json) -> str:
    return ", ".join(quote_literal(v) for v in _as_list(value))


def _check_columns(spec: QuerySpec, names: set[str]) -> None:
    referenced: list[str] = [f.col for f in spec.filters]
    if spec.group_by is not None:
        referenced += spec.group_by
        referenced += [a.col for a in spec.aggs]
    if spec.pivot is not None:
        referenced += [*spec.pivot.index, spec.pivot.columns, spec.pivot.values]
    for name in referenced:
        if name not in names:
            raise QueryError(name, spec.dataset)
    produced = names | {a.name for a in spec.aggs}
    if spec.pivot is None:
        for s in spec.sort:
            if s.col not in produced:
                raise QueryError(s.col, spec.dataset)
        for name in spec.select or []:
            if name not in produced:
                raise QueryError(name, spec.dataset)
```

Add `from quarry.query.sql_target import to_sql` and `"to_sql"` to `src/quarry/query/__init__.py`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/query -v`
Expected: all pass. Known places a mismatch can appear, and the fix for each:

- DuckDB `median` of an integer column returns a double while polars returns a float; `normalize` casts both to Float64, so this is fine.
- If the pivot equivalence case fails because DuckDB names pivoted columns differently, print both frames' columns and adjust `normalize` to sort columns only; do not change the compilers to special-case names.
- If `first`/`last` ever enter `SPECS`, they are order-dependent and must be removed; they are deliberately absent.

- [ ] **Step 6: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/query tests/query
git commit -m "feat(query): compile QuerySpec to DuckDB SQL, prove equivalence with polars target"
```

---

### Task 6: Source compile target

**Files:**

- Create: `src/quarry/query/source_target.py`
- Test: `tests/query/test_source_target.py`
- Modify: `src/quarry/query/__init__.py` (add `to_source`, `Backing` exports)

**Interfaces:**

- Consumes: spec models, `to_polars` (for equivalence), `quote_ident`/`quote_literal` and `to_sql` (for the DuckDB rendering).
- Produces:
  - `Backing = Literal["polars", "polars_lazy", "duckdb"]` (lives in `quarry.query.spec`, add it there in this task).
  - `def to_source(spec: QuerySpec, backing: Backing, result_name: str = "result") -> str`: returns Python source. For polars backings, a polars method chain ending in `.collect()` assigned to `result_name`. For `duckdb`, a `duckdb.sql(...)` call over `to_sql(spec, spec.dataset)` assigned to `result_name` as a polars DataFrame via `.pl()`; DuckDB's replacement scan resolves the quoted dataset name to the relation variable in scope. The generated source assumes `pl`, `duckdb`, and the dataset name are in scope, and imports `date`/`datetime` itself only when it uses them.

- [ ] **Step 1: Write the failing tests**

`tests/query/test_source_target.py`:

```python
import duckdb
import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quarry.query import QuerySpec, to_polars, to_source
from tests.query.fixtures import SPECS, trades


def run_source(source: str, backing: str) -> pl.DataFrame:
    namespace: dict[str, object] = {"pl": pl, "duckdb": duckdb}
    frame = trades()
    if backing == "duckdb":
        # Generated code calls duckdb.sql(), the default connection, so register there.
        duckdb.register("trades_src", frame)
        namespace["trades"] = duckdb.sql("SELECT * FROM trades_src")
    elif backing == "polars_lazy":
        namespace["trades"] = frame.lazy()
    else:
        namespace["trades"] = frame
    exec(source, namespace)  # the test executes generated code on purpose
    result = namespace["result"]
    assert isinstance(result, pl.DataFrame)
    return result


def test_polars_source_is_readable():
    src = to_source(
        QuerySpec.model_validate(
            {
                "dataset": "trades",
                "filters": [{"col": "ticker", "op": "eq", "value": "AAPL"}],
                "sort": [{"col": "volume", "desc": True}],
                "limit": 2,
            }
        ),
        "polars",
    )
    assert 'pl.col("ticker") == "AAPL"' in src
    assert '.sort(["volume"], descending=[True])' in src
    assert ".slice(0, 2)" in src
    assert src.strip().startswith("result = (")
    assert src.strip().endswith(".collect()\n)")


def test_date_literal_imports_date():
    src = to_source(
        QuerySpec.model_validate(
            {"dataset": "trades", "filters": [{"col": "date", "op": "ge", "value": "2024-01-03"}]}
        ),
        "polars",
    )
    assert "from datetime import date" in src
    assert 'date.fromisoformat("2024-01-03")' in src


def test_duckdb_source_uses_sql():
    src = to_source(QuerySpec(dataset="trades", limit=1), "duckdb")
    assert "duckdb.sql(" in src
    assert ".pl()" in src


@pytest.mark.parametrize("backing", ["polars", "polars_lazy", "duckdb"])
@pytest.mark.parametrize("spec", SPECS, ids=[s.model_dump_json() for s in SPECS])
def test_source_matches_polars_target(spec: QuerySpec, backing: str):
    expected = to_polars(spec, trades()).collect()
    actual = run_source(to_source(spec, backing), backing)
    expected = expected.select(sorted(expected.columns)).sort(sorted(expected.columns))
    actual = actual.select(sorted(actual.columns)).sort(sorted(actual.columns))
    assert_frame_equal(expected, actual, check_dtypes=False, rtol=1e-9)
```

The date-literal source test requires `to_source` to render the string against the Date column. `to_source` does not have the frame schema, so it renders date-looking strings (`YYYY-MM-DD`) with `date.fromisoformat` and datetime-looking strings (containing `T` or a space after a date) with `datetime.fromisoformat`; other strings stay plain. This is the one place the source target diverges from `to_polars`, which uses the real dtype. Document this in the module docstring.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/query/test_source_target.py -v`
Expected: FAIL with `ImportError: cannot import name 'to_source'`

- [ ] **Step 3: Write the implementation**

Add to `src/quarry/query/spec.py`:

```python
Backing = Literal["polars", "polars_lazy", "duckdb"]
```

`src/quarry/query/source_target.py`:

```python
"""Render a QuerySpec as Python source a researcher can read and run.

The polars rendering mirrors `polars_target` method for method. Because this
module has no schema, ISO-date-shaped strings render as `date.fromisoformat`
and ISO-datetime-shaped strings as `datetime.fromisoformat`; all other
strings render as plain literals.
"""

from __future__ import annotations

import re
from typing import Final

from quarry.query.spec import Agg, Backing, Filter, Json, Pivot, QuerySpec
from quarry.query.sql_target import to_sql

DATE_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}$")
DATETIME_RE: Final = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}")


def to_source(spec: QuerySpec, backing: Backing, result_name: str = "result") -> str:
    if backing == "duckdb":
        sql = to_sql(spec, spec.dataset)
        return f"{result_name} = duckdb.sql({sql!r}).pl()\n"
    lines = [f"{spec.dataset}.lazy()"]
    if spec.filters:
        lines.append(f".filter({' & '.join(_paren(filter_source(f)) for f in spec.filters)})")
    if spec.group_by is not None:
        aggs = ", ".join(agg_source(a) for a in spec.aggs)
        lines.append(f".group_by({spec.group_by!r}).agg([{aggs}])")
    elif spec.pivot is not None:
        lines.append(_pivot_source(spec.pivot))
    if spec.sort:
        cols = [s.col for s in spec.sort]
        desc = [s.desc for s in spec.sort]
        lines.append(f".sort({cols!r}, descending={desc!r})")
    if spec.limit is not None or spec.offset:
        lines.append(f".slice({spec.offset}, {spec.limit!r})")
    if spec.select is not None:
        lines.append(f".select({spec.select!r})")
    lines.append(".collect()")
    body = "\n".join(f"    {line}" for line in lines)
    imports = _imports(spec)
    return f"{imports}{result_name} = (\n{body}\n)\n"


def filter_source(f: Filter) -> str:
    col = f"pl.col({f.col!r})"
    match f.op:
        case "eq":
            return f"{col} == {_lit(f.value)}"
        case "ne":
            return f"{col} != {_lit(f.value)}"
        case "lt":
            return f"{col} < {_lit(f.value)}"
        case "le":
            return f"{col} <= {_lit(f.value)}"
        case "gt":
            return f"{col} > {_lit(f.value)}"
        case "ge":
            return f"{col} >= {_lit(f.value)}"
        case "in":
            return f"{col}.is_in({_lit_list(f.value)})"
        case "not_in":
            return f"~{col}.is_in({_lit_list(f.value)})"
        case "between":
            lo, hi = _as_list(f.value)
            return f"{col}.is_between({_lit(lo)}, {_lit(hi)})"
        case "contains":
            return f"{col}.str.contains({str(f.value)!r}, literal=True)"
        case "starts_with":
            return f"{col}.str.starts_with({str(f.value)!r})"
        case "is_null":
            return f"{col}.is_null()"
        case "not_null":
            return f"{col}.is_not_null()"


def agg_source(a: Agg) -> str:
    return f"pl.col({a.col!r}).{a.fn}().alias({a.name!r})"


def _pivot_source(p: Pivot) -> str:
    return (
        f".collect().pivot(on={p.columns!r}, index={p.index!r}, "
        f"values={p.values!r}, aggregate_function={p.agg!r}).lazy()"
    )


def _lit(value: Json) -> str:
    if isinstance(value, str):
        if DATE_RE.match(value):
            return f"date.fromisoformat({value!r})"
        if DATETIME_RE.match(value):
            return f"datetime.fromisoformat({value!r})"
    return repr(value)


def _as_list(value: Json) -> list[Json]:
    if not isinstance(value, list):
        raise TypeError("expected a list value")
    return value


def _lit_list(value: Json) -> str:
    return "[" + ", ".join(_lit(v) for v in _as_list(value)) + "]"


def _paren(expr: str) -> str:
    return f"({expr})"


def _imports(spec: QuerySpec) -> str:
    values = [f.value for f in spec.filters]
    flat: list[Json] = []
    for v in values:
        flat.extend(v if isinstance(v, list) else [v])
    needs_date = any(isinstance(v, str) and DATE_RE.match(v) for v in flat)
    needs_datetime = any(isinstance(v, str) and DATETIME_RE.match(v) for v in flat)
    names = [n for n, needed in (("date", needs_date), ("datetime", needs_datetime)) if needed]
    return f"from datetime import {', '.join(names)}\n\n" if names else ""
```

Add `from quarry.query.source_target import to_source` and `from quarry.query.spec import Backing` to `src/quarry/query/__init__.py`, with `"to_source"` and `"Backing"` in `__all__`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/query -v`
Expected: all pass. The pivot spec under `polars_lazy` runs `.collect().pivot(...).lazy()`, which is valid.

- [ ] **Step 5: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/query tests/query
git commit -m "feat(query): render QuerySpec as runnable polars or DuckDB Python source"
```

---

### Task 7: Lineage analysis

**Files:**

- Create: `src/quarry/kernel/__init__.py`
- Create: `src/quarry/kernel/lineage.py`
- Test: `tests/kernel/__init__.py`
- Test: `tests/kernel/test_lineage.py`

**Interfaces:**

- Produces (in `quarry.kernel.lineage`):
  - `@dataclass(slots=True, frozen=True) class CodeNames`: `stores: frozenset[str]`, `loads: frozenset[str]`, `defines: frozenset[str]`
  - `def analyze(code: str) -> CodeNames`: module-level only. `stores` = names bound by assignment, augmented assignment, annotated assignment, tuple unpacking, `with ... as`, `for` targets, and imports at module level. `loads` = names read at module level including the root of attribute and subscript chains, and names read inside module-level function bodies that are not parameters or locals of that function. `defines` = top-level `def` and `class` names. Raises `SyntaxError` through unchanged.
  - `def dataset_writes(names: CodeNames, before: set[str], after: set[str]) -> list[str]`: sorted names that are datasets after execution and were either stored by the code or newly present.
  - `def dataset_reads(names: CodeNames, before: set[str], defined_earlier: set[str]) -> list[str]`: sorted loaded names that were datasets before execution, plus loaded names in `defined_earlier`.

- [ ] **Step 1: Write the failing tests**

`tests/kernel/__init__.py`: empty.

`tests/kernel/test_lineage.py`:

```python
import pytest

from quarry.kernel.lineage import analyze, dataset_reads, dataset_writes


def test_simple_assignment():
    names = analyze("returns = loaders.daily_returns(['AAPL'])")
    assert names.stores == {"returns"}
    assert "loaders" in names.loads
    assert names.defines == frozenset()


def test_attribute_chain_root_is_a_load():
    names = analyze("tech = returns.filter(pl.col('sector') == 'tech')")
    assert names.stores == {"tech"}
    assert {"returns", "pl"} <= names.loads


def test_subscript_root_is_a_load():
    names = analyze("x = frames['a']")
    assert "frames" in names.loads


def test_tuple_unpacking_and_augmented():
    names = analyze("a, b = f()\nc += 1")
    assert names.stores == {"a", "b", "c"}
    assert {"f", "c"} <= names.loads


def test_with_and_for_targets():
    names = analyze("with open('x') as fh:\n    pass\nfor row in rows:\n    pass")
    assert {"fh", "row"} <= names.stores
    assert "rows" in names.loads


def test_imports_are_stores():
    names = analyze("import polars as pl\nfrom datetime import date")
    assert names.stores == {"pl", "date"}


def test_function_definition_and_free_variables():
    code = "def clean(df):\n    return df.join(sectors, on='ticker')\n"
    names = analyze(code)
    assert names.defines == {"clean"}
    assert "sectors" in names.loads
    assert "df" not in names.loads


def test_function_locals_are_not_loads():
    code = "def f():\n    tmp = 1\n    return tmp\n"
    assert "tmp" not in analyze(code).loads


def test_syntax_error_propagates():
    with pytest.raises(SyntaxError):
        analyze("def (:")


def test_dataset_writes_only_counts_dataset_objects():
    names = analyze("returns = None\nprices = load()")
    writes = dataset_writes(names, before={"returns"}, after={"prices"})
    assert writes == ["prices"]


def test_dataset_writes_includes_rebound_existing_dataset():
    names = analyze("returns = returns.head(10)")
    assert dataset_writes(names, before={"returns"}, after={"returns"}) == ["returns"]


def test_dataset_reads():
    names = analyze("out = clean(returns, other)")
    reads = dataset_reads(names, before={"returns", "unused"}, defined_earlier={"clean"})
    assert reads == ["clean", "returns"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_lineage.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.kernel'`

- [ ] **Step 3: Write the implementation**

`src/quarry/kernel/__init__.py`: empty docstring module.

`src/quarry/kernel/lineage.py`:

```python
"""Static analysis of step code for dataset reads, writes, and definitions."""

from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(slots=True, frozen=True)
class CodeNames:
    stores: frozenset[str]
    loads: frozenset[str]
    defines: frozenset[str]


def analyze(code: str) -> CodeNames:
    tree = ast.parse(code)
    stores: set[str] = set()
    loads: set[str] = set()
    defines: set[str] = set()
    for node in tree.body:
        match node:
            case ast.FunctionDef() | ast.AsyncFunctionDef() | ast.ClassDef():
                defines.add(node.name)
                loads |= _free_names(node)
            case ast.Import() | ast.ImportFrom():
                stores |= {(alias.asname or alias.name).split(".")[0] for alias in node.names}
            case _:
                s, l = _module_level_names(node)
                stores |= s
                loads |= l
    return CodeNames(frozenset(stores), frozenset(loads), frozenset(defines))


def dataset_writes(names: CodeNames, before: set[str], after: set[str]) -> list[str]:
    return sorted(n for n in after if n in names.stores or n not in before)


def dataset_reads(names: CodeNames, before: set[str], defined_earlier: set[str]) -> list[str]:
    return sorted(n for n in names.loads if n in before or n in defined_earlier)


def _module_level_names(node: ast.AST) -> tuple[set[str], set[str]]:
    stores: set[str] = set()
    loads: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            if isinstance(child.ctx, ast.Store):
                stores.add(child.id)
            else:
                loads.add(child.id)
        elif isinstance(child, ast.AugAssign) and isinstance(child.target, ast.Name):
            loads.add(child.target.id)  # `c += 1` reads c before it stores c
        elif isinstance(child, ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda):
            loads |= _free_names(child)
    return stores, loads


def _free_names(func: ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda | ast.ClassDef) -> set[str]:
    """Names read in a function body that are not its parameters or locals."""
    if isinstance(func, ast.ClassDef):
        bound: set[str] = set()
        body: list[ast.stmt] = func.body
    else:
        bound = {a.arg for a in _all_args(func.args)}
        body = func.body if isinstance(func, ast.FunctionDef | ast.AsyncFunctionDef) else [ast.Expr(func.body)]
    local_stores: set[str] = set()
    reads: set[str] = set()
    for stmt in body:
        for child in ast.walk(stmt):
            if isinstance(child, ast.Name):
                if isinstance(child.ctx, ast.Store):
                    local_stores.add(child.id)
                else:
                    reads.add(child.id)
    return reads - bound - local_stores


def _all_args(args: ast.arguments) -> list[ast.arg]:
    extra = [a for a in (args.vararg, args.kwarg) if a is not None]
    return [*args.posonlyargs, *args.args, *args.kwonlyargs, *extra]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_lineage.py -v`
Expected: 12 passed

- [ ] **Step 5: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/kernel tests/kernel
git commit -m "feat(kernel): static lineage analysis of step code"
```

---

### Task 8: Dataset registry and metadata

**Files:**

- Create: `src/quarry/kernel/datasets.py`
- Test: `tests/kernel/test_datasets.py`

**Interfaces:**

- Consumes: `Backing` from Task 6.
- Produces (in `quarry.kernel.datasets`):
  - `class Column(BaseModel)`: `name: str`, `dtype: str`
  - `class DatasetMeta(BaseModel)`: `name: str`, `backing: Backing`, `schema_: list[Column]` (serialized as `schema`, use `Field(alias="schema")` with `populate_by_name=True`), `rows: int | None`, `preview: list[dict[str, Json]]`
  - `Dataset = pl.DataFrame | pl.LazyFrame | duckdb.DuckDBPyRelation`
  - `def is_dataset(obj: object) -> TypeGuard[Dataset]`
  - `def backing_of(obj: Dataset) -> Backing`
  - `def describe(name: str, obj: Dataset, *, count_rows: bool) -> DatasetMeta`: schema from the object, `rows` only when `count_rows` or the object is an eager DataFrame, preview of 20 rows as JSON-safe dicts.
  - `def dataset_names(namespace: Mapping[str, object]) -> set[str]`: names bound to dataset objects, excluding names starting with `_`.
  - `def to_json_rows(df: pl.DataFrame) -> list[dict[str, Json]]`: JSON-safe rows (dates and datetimes as ISO strings).

- [ ] **Step 1: Write the failing tests**

`tests/kernel/test_datasets.py`:

```python
from datetime import date

import duckdb
import polars as pl

from quarry.kernel.datasets import DatasetMeta, backing_of, dataset_names, describe, is_dataset, to_json_rows


def frame() -> pl.DataFrame:
    return pl.DataFrame({"d": [date(2024, 1, 1)], "x": [1.5], "s": ["a"]})


def test_is_dataset_for_each_type():
    assert is_dataset(frame())
    assert is_dataset(frame().lazy())
    assert is_dataset(duckdb.connect().sql("SELECT 1 AS one"))
    assert not is_dataset([1, 2])
    assert not is_dataset(None)


def test_backing_of():
    assert backing_of(frame()) == "polars"
    assert backing_of(frame().lazy()) == "polars_lazy"
    assert backing_of(duckdb.connect().sql("SELECT 1 AS one")) == "duckdb"


def test_describe_eager_counts_rows_and_previews():
    meta = describe("f", frame(), count_rows=False)
    assert meta.name == "f"
    assert meta.rows == 1
    assert [c.name for c in meta.schema_] == ["d", "x", "s"]
    assert meta.schema_[0].dtype == "Date"
    assert meta.preview == [{"d": "2024-01-01", "x": 1.5, "s": "a"}]


def test_describe_lazy_defers_row_count():
    assert describe("f", frame().lazy(), count_rows=False).rows is None
    assert describe("f", frame().lazy(), count_rows=True).rows == 1


def test_describe_duckdb_relation():
    rel = duckdb.connect().sql("SELECT 1 AS one, 'x' AS s")
    meta = describe("r", rel, count_rows=True)
    assert meta.backing == "duckdb"
    assert meta.rows == 1
    assert [c.name for c in meta.schema_] == ["one", "s"]
    assert meta.preview == [{"one": 1, "s": "x"}]


def test_describe_serializes_schema_key():
    meta = describe("f", frame(), count_rows=False)
    assert "schema" in meta.model_dump(by_alias=True)
    assert DatasetMeta.model_validate(meta.model_dump(by_alias=True)) == meta


def test_dataset_names_skips_private_and_non_datasets():
    ns = {"a": frame(), "_b": frame(), "c": 3, "pl": pl}
    assert dataset_names(ns) == {"a"}


def test_to_json_rows_handles_datetime_and_null():
    df = pl.DataFrame({"t": [None], "x": [None]}, schema={"t": pl.Datetime, "x": pl.Int64})
    assert to_json_rows(df) == [{"t": None, "x": None}]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_datasets.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.kernel.datasets'`

- [ ] **Step 3: Write the implementation**

`src/quarry/kernel/datasets.py`:

```python
"""What counts as a dataset in the kernel namespace, and how to describe one."""

from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Final, TypeGuard

import duckdb
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from quarry.query.spec import Backing, Json

PREVIEW_ROWS: Final = 20

Dataset = pl.DataFrame | pl.LazyFrame | duckdb.DuckDBPyRelation


class Column(BaseModel):
    name: str
    dtype: str


class DatasetMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    backing: Backing
    schema_: list[Column] = Field(alias="schema")
    rows: int | None
    preview: list[dict[str, Json]]


def is_dataset(obj: object) -> TypeGuard[Dataset]:
    return isinstance(obj, pl.DataFrame | pl.LazyFrame | duckdb.DuckDBPyRelation)


def backing_of(obj: Dataset) -> Backing:
    if isinstance(obj, pl.DataFrame):
        return "polars"
    if isinstance(obj, pl.LazyFrame):
        return "polars_lazy"
    return "duckdb"


def describe(name: str, obj: Dataset, *, count_rows: bool) -> DatasetMeta:
    backing = backing_of(obj)
    if isinstance(obj, pl.DataFrame):
        schema = _polars_schema(obj.schema)
        rows: int | None = obj.height
        head = obj.head(PREVIEW_ROWS)
    elif isinstance(obj, pl.LazyFrame):
        schema = _polars_schema(obj.collect_schema())
        rows = obj.select(pl.len()).collect().item() if count_rows else None
        head = obj.head(PREVIEW_ROWS).collect()
    else:
        schema = [Column(name=n, dtype=str(t)) for n, t in zip(obj.columns, obj.types, strict=True)]
        rows = obj.aggregate("count(*)").fetchone()[0] if count_rows else None
        head = obj.limit(PREVIEW_ROWS).pl()
    return DatasetMeta(name=name, backing=backing, schema=schema, rows=rows, preview=to_json_rows(head))


def dataset_names(namespace: Mapping[str, object]) -> set[str]:
    return {n for n, v in namespace.items() if not n.startswith("_") and is_dataset(v)}


def to_json_rows(df: pl.DataFrame) -> list[dict[str, Json]]:
    rows: list[dict[str, Json]] = json.loads(df.write_json())
    return rows


def _polars_schema(schema: Mapping[str, pl.DataType]) -> list[Column]:
    return [Column(name=n, dtype=str(t)) for n, t in schema.items()]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_datasets.py -v`
Expected: 8 passed. If `write_json` emits datetimes in a different shape than `"2024-01-01"` for a Date, keep the test's expectation and convert temporal columns with `df.with_columns(pl.col(pl.Date, pl.Datetime).cast(pl.String))` inside `to_json_rows` before serializing. Note that `pl.Datetime` as a selector matches every time unit.

- [ ] **Step 5: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/kernel tests/kernel
git commit -m "feat(kernel): dataset detection and DatasetMeta description"
```

---

### Task 9: Executor

**Files:**

- Create: `src/quarry/kernel/executor.py`
- Test: `tests/kernel/test_executor.py`

**Interfaces:**

- Consumes: `analyze`, `dataset_writes`, `dataset_reads` (Task 7); `DatasetMeta`, `describe`, `dataset_names`, `is_dataset` (Task 8); `QuerySpec`, `to_polars`, `to_sql`, `QueryError` (Tasks 3 to 5).
- Produces (in `quarry.kernel.executor`):
  - `class ExecError(BaseModel)`: `type: str`, `message: str`, `traceback: str`
  - `class ExecResult(BaseModel)`: `status: Literal["ok","error","interrupted"]`, `stdout_tail: str`, `stderr_tail: str`, `error: ExecError | None`, `reads: list[str]`, `writes: list[str]`, `defines: list[str]`, `datasets: list[DatasetMeta]`, `duration_ms: int`
  - `class QueryResult(BaseModel)`: `schema_: list[Column]` (alias `schema`), `rows: list[dict[str, Json]] | None`, `arrow_base64: str | None`, `row_count: int`, `truncated: bool`
  - `class Executor`: `__init__(self, namespace: dict[str, object], *, row_cap: int, tail_bytes: int = 4096)`; `execute(self, code: str) -> ExecResult`; `describe(self, name: str) -> DatasetMeta`; `list_datasets(self) -> list[DatasetMeta]`; `query(self, spec: QuerySpec) -> QueryResult`; `snapshot(self, name: str, path: Path) -> DatasetMeta`. All raise `KeyError(name)` for an unknown dataset and `QueryError` from the compilers; `execute` never raises.
  - `TAIL_BYTES: Final = 4096`

- [ ] **Step 1: Write the failing tests**

`tests/kernel/test_executor.py`:

```python
import base64
import io
from pathlib import Path

import duckdb
import polars as pl
import pytest

from quarry.kernel.executor import Executor
from quarry.query import Filter, QueryError, QuerySpec


def make() -> Executor:
    conn = duckdb.connect()
    return Executor({"pl": pl, "duckdb": duckdb, "_conn": conn}, row_cap=3)


def test_execute_registers_dataset_and_reports_lineage():
    ex = make()
    result = ex.execute("returns = pl.DataFrame({'ticker': ['A', 'B'], 'ret': [0.1, 0.2]})")
    assert result.status == "ok"
    assert result.writes == ["returns"]
    assert result.reads == []
    assert result.datasets[0].name == "returns"
    assert result.datasets[0].rows == 2
    second = ex.execute("top = returns.filter(pl.col('ret') > 0.15)")
    assert second.reads == ["returns"]
    assert second.writes == ["top"]


def test_execute_captures_stdout_tail():
    ex = make()
    result = ex.execute("print('x' * 10000)")
    assert result.status == "ok"
    assert len(result.stdout_tail) == 4096
    assert result.stdout_tail.endswith("x\n")


def test_execute_error_is_structured():
    ex = make()
    result = ex.execute("1 / 0")
    assert result.status == "error"
    assert result.error is not None
    assert result.error.type == "ZeroDivisionError"
    assert "ZeroDivisionError" in result.error.traceback


def test_execute_syntax_error_is_structured():
    result = make().execute("def (:")
    assert result.status == "error"
    assert result.error is not None
    assert result.error.type == "SyntaxError"


def test_execute_keyboard_interrupt_is_interrupted_status():
    result = make().execute("raise KeyboardInterrupt")
    assert result.status == "interrupted"


def test_rebinding_to_non_dataset_removes_it():
    ex = make()
    ex.execute("returns = pl.DataFrame({'a': [1]})")
    result = ex.execute("returns = None")
    assert result.writes == []
    assert [m.name for m in ex.list_datasets()] == []


def test_helper_defined_earlier_counts_as_read():
    ex = make()
    ex.execute("def clean(df):\n    return df.head(1)\n")
    ex.execute("returns = pl.DataFrame({'a': [1, 2]})")
    result = ex.execute("small = clean(returns)")
    assert result.reads == ["clean", "returns"]


def test_describe_and_unknown_name():
    ex = make()
    ex.execute("lf = pl.DataFrame({'a': [1, 2, 3]}).lazy()")
    assert ex.describe("lf").rows == 3
    with pytest.raises(KeyError):
        ex.describe("nope")


def test_query_polars_with_row_cap():
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [5, 4, 3, 2, 1]})")
    out = ex.query(QuerySpec(dataset="df", sort=[{"col": "a"}]))
    assert out.rows == [{"a": 1}, {"a": 2}, {"a": 3}]
    assert out.truncated is True
    assert out.row_count == 3


def test_query_duckdb_relation():
    ex = make()
    ex.execute("rel = _conn.sql(\"SELECT * FROM (VALUES (1, 'x'), (2, 'y')) t(n, s)\")")
    out = ex.query(QuerySpec(dataset="rel", filters=[Filter(col="n", op="eq", value=2)]))
    assert out.rows == [{"n": 2, "s": "y"}]


def test_query_arrow_format():
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    out = ex.query(QuerySpec(dataset="df", format="arrow"))
    assert out.rows is None
    assert out.arrow_base64 is not None
    decoded = pl.read_ipc(io.BytesIO(base64.b64decode(out.arrow_base64)))
    assert decoded["a"].to_list() == [1]


def test_query_unknown_column_raises_query_error():
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    with pytest.raises(QueryError):
        ex.query(QuerySpec(dataset="df", filters=[Filter(col="zz", op="eq", value=1)]))


def test_snapshot_writes_parquet(tmp_path: Path):
    ex = make()
    ex.execute("lf = pl.DataFrame({'a': [1, 2]}).lazy()")
    meta = ex.snapshot("lf", tmp_path / "lf.parquet")
    assert meta.rows == 2
    assert pl.read_parquet(tmp_path / "lf.parquet")["a"].to_list() == [1, 2]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_executor.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.kernel.executor'`

- [ ] **Step 3: Write the implementation**

`src/quarry/kernel/executor.py`:

```python
"""Execute step code in a persistent namespace and track dataset lineage."""

from __future__ import annotations

import base64
import contextlib
import io
import time
import traceback
from pathlib import Path
from typing import Final, Literal

import duckdb
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from quarry.kernel.datasets import Column, Dataset, DatasetMeta, dataset_names, describe, is_dataset, to_json_rows
from quarry.kernel.lineage import analyze, dataset_reads, dataset_writes
from quarry.query.polars_target import to_polars
from quarry.query.spec import Json, QuerySpec
from quarry.query.sql_target import to_sql

TAIL_BYTES: Final = 4096


class ExecError(BaseModel):
    type: str
    message: str
    traceback: str


class ExecResult(BaseModel):
    status: Literal["ok", "error", "interrupted"]
    stdout_tail: str
    stderr_tail: str
    error: ExecError | None
    reads: list[str]
    writes: list[str]
    defines: list[str]
    datasets: list[DatasetMeta]
    duration_ms: int


class QueryResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: list[Column] = Field(alias="schema")
    rows: list[dict[str, Json]] | None
    arrow_base64: str | None
    row_count: int
    truncated: bool


class Executor:
    def __init__(self, namespace: dict[str, object], *, row_cap: int, tail_bytes: int = TAIL_BYTES) -> None:
        self._ns = namespace
        self._row_cap = row_cap
        self._tail = tail_bytes
        self._defined: set[str] = set()

    def execute(self, code: str) -> ExecResult:
        started = time.monotonic()
        before = dataset_names(self._ns)
        out, err = io.StringIO(), io.StringIO()
        status: Literal["ok", "error", "interrupted"] = "ok"
        error: ExecError | None = None
        names = None
        try:
            names = analyze(code)
            compiled = compile(code, "<step>", "exec")
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                exec(compiled, self._ns)  # executing researcher code is the kernel's job
        except KeyboardInterrupt:
            status = "interrupted"
        except BaseException as exc:  # every failure must become a structured result
            status = "error"
            error = ExecError(type=type(exc).__name__, message=str(exc), traceback=traceback.format_exc())
        after = dataset_names(self._ns)
        if names is None:
            reads, writes, defines = [], sorted(after - before), []
        else:
            reads = dataset_reads(names, before, self._defined)
            writes = dataset_writes(names, before, after)
            defines = sorted(names.defines)
            self._defined |= names.defines
        return ExecResult(
            status=status,
            stdout_tail=out.getvalue()[-self._tail :],
            stderr_tail=err.getvalue()[-self._tail :],
            error=error,
            reads=reads,
            writes=writes,
            defines=defines,
            datasets=[describe(n, self._dataset(n), count_rows=False) for n in writes],
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def describe(self, name: str) -> DatasetMeta:
        return describe(name, self._dataset(name), count_rows=True)

    def list_datasets(self) -> list[DatasetMeta]:
        return [describe(n, self._dataset(n), count_rows=False) for n in sorted(dataset_names(self._ns))]

    def query(self, spec: QuerySpec) -> QueryResult:
        obj = self._dataset(spec.dataset)
        capped = spec.model_copy(update={"limit": min(spec.limit or self._row_cap, self._row_cap)})
        frame = self._run(capped, obj)
        truncated = frame.height >= self._row_cap and (spec.limit is None or spec.limit > self._row_cap)
        schema = [Column(name=n, dtype=str(t)) for n, t in frame.schema.items()]
        if spec.format == "arrow":
            buffer = io.BytesIO()
            frame.write_ipc(buffer)
            encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
            return QueryResult(schema=schema, rows=None, arrow_base64=encoded, row_count=frame.height, truncated=truncated)
        return QueryResult(schema=schema, rows=to_json_rows(frame), arrow_base64=None, row_count=frame.height, truncated=truncated)

    def snapshot(self, name: str, path: Path) -> DatasetMeta:
        obj = self._dataset(name)
        frame = obj.collect() if isinstance(obj, pl.LazyFrame) else obj.pl() if isinstance(obj, duckdb.DuckDBPyRelation) else obj
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(path)
        return describe(name, frame, count_rows=True)

    def _dataset(self, name: str) -> Dataset:
        obj = self._ns.get(name)
        if name.startswith("_") or not is_dataset(obj):
            raise KeyError(name)
        return obj

    def _run(self, spec: QuerySpec, obj: Dataset) -> pl.DataFrame:
        if isinstance(obj, duckdb.DuckDBPyRelation):
            sql = to_sql(spec, "__quarry_src", columns=obj.columns)
            return obj.query("__quarry_src", sql).pl()
        return to_polars(spec, obj).collect()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/kernel/test_executor.py -v`
Expected: 13 passed. If `DuckDBPyRelation.query(view_name, sql)` is unavailable in the installed DuckDB, replace `_run`'s relation branch with: create a fresh `duckdb.connect()`, `conn.register("__quarry_src", obj.arrow())`, and `conn.sql(sql).pl()`. Either path satisfies the tests.

- [ ] **Step 5: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/kernel tests/kernel
git commit -m "feat(kernel): executor with lineage, structured errors, capped queries, snapshots"
```

---

### Task 10: Kernel protocol, service, subprocess entry, and client

**Files:**

- Create: `src/quarry/kernel/protocol.py`
- Create: `src/quarry/kernel/service.py`
- Create: `src/quarry/kernel/__main__.py`
- Create: `src/quarry/kernel/client.py`
- Test: `tests/kernel/test_protocol.py`
- Test: `tests/kernel/test_client.py`

**Interfaces:**

- Consumes: `Executor`, `ExecResult`, `QueryResult` (Task 9); `DatasetMeta` (Task 8); `QuerySpec` (Task 3); `QuarryConfig`, `load_config` (Task 2). `build_namespace(config: QuarryConfig) -> dict[str, object]` from Task 11; until Task 11 lands, `__main__` uses a placeholder namespace `{"pl": pl, "duckdb": duckdb}` and Task 11 replaces that one line.
- Produces:
  - `quarry.kernel.protocol`: `class Request(BaseModel)`: `id: int`, `method: str`, `params: dict[str, Json]`; `class RpcError(BaseModel)`: `type: str`, `message: str`; `class Response(BaseModel)`: `id: int`, `result: Json | None = None`, `error: RpcError | None = None`; `def encode(msg: BaseModel) -> bytes` (JSON plus newline) and `def decode_request(line: bytes) -> Request`, `def decode_response(line: bytes) -> Response`.
  - `quarry.kernel.service`: `class KernelService`: `__init__(self, executor: Executor)`; `def handle(self, request: Request) -> Response` dispatching `execute`, `describe`, `query`, `list_datasets`, `snapshot`, `shutdown`; `interrupt` is handled by the transport, not the service. Unknown method, `KeyError`, `QueryError`, and `ValidationError` become `RpcError` with `type` set to the exception class name.
  - `quarry.kernel.__main__`: `python -m quarry.kernel --socket PATH --root ROOT`. Connects to the Unix socket at PATH (the client listens), runs a reader thread that handles every request except `execute` immediately and queues `execute` for the main thread. `interrupt` sends `SIGINT` to the process so a running `execute` raises `KeyboardInterrupt`. `shutdown` exits after responding. Applies `RLIMIT_AS` when `config.data.kernel_memory_mb > 0`.
  - `quarry.kernel.client`: `class KernelDead(Exception)`; `class KernelClient`: `@classmethod spawn(cls, root: Path, *, startup_timeout: float = 30.0) -> KernelClient`; `execute(self, code: str) -> ExecResult`; `interrupt(self) -> None`; `describe(self, name: str) -> DatasetMeta`; `list_datasets(self) -> list[DatasetMeta]`; `query(self, spec: QuerySpec) -> QueryResult`; `snapshot(self, name: str, path: Path) -> DatasetMeta`; `shutdown(self) -> None`; `is_alive(self) -> bool`; `close(self) -> None`. Every call raises `KernelDead` if the process has exited or the socket breaks, and `RpcFailure(type, message)` for an error response.

- [ ] **Step 1: Write the failing protocol tests**

`tests/kernel/test_protocol.py`:

```python
import duckdb
import polars as pl
import pytest

from quarry.kernel.executor import Executor
from quarry.kernel.protocol import Request, Response, decode_request, decode_response, encode
from quarry.kernel.service import KernelService


def service() -> KernelService:
    return KernelService(Executor({"pl": pl, "duckdb": duckdb}, row_cap=10))


def test_encode_decode_round_trip():
    req = Request(id=1, method="execute", params={"code": "x = 1"})
    assert decode_request(encode(req)) == req
    resp = Response(id=1, result={"ok": True})
    assert decode_response(encode(resp)) == resp
    assert encode(req).endswith(b"\n")


def test_execute_dispatch():
    resp = service().handle(Request(id=1, method="execute", params={"code": "df = pl.DataFrame({'a': [1]})"}))
    assert resp.error is None
    assert isinstance(resp.result, dict)
    assert resp.result["writes"] == ["df"]


def test_describe_unknown_is_error_response():
    resp = service().handle(Request(id=2, method="describe", params={"name": "nope"}))
    assert resp.error is not None
    assert resp.error.type == "KeyError"


def test_unknown_method():
    resp = service().handle(Request(id=3, method="fly", params={}))
    assert resp.error is not None
    assert resp.error.type == "UnknownMethod"


def test_query_validation_error():
    svc = service()
    svc.handle(Request(id=1, method="execute", params={"code": "df = pl.DataFrame({'a': [1]})"}))
    resp = svc.handle(Request(id=2, method="query", params={"spec": {"dataset": "df", "limit": 0}}))
    assert resp.error is not None
    assert resp.error.type == "ValidationError"


@pytest.mark.parametrize("method", ["execute", "describe", "query", "snapshot"])
def test_missing_params_is_error_not_crash(method: str):
    resp = service().handle(Request(id=9, method=method, params={}))
    assert resp.error is not None
```

- [ ] **Step 2: Write the failing client tests (real subprocess)**

`tests/kernel/test_client.py`:

```python
import threading
import time
from pathlib import Path

import polars as pl
import pytest

from quarry.kernel.client import KernelClient, KernelDead, RpcFailure
from quarry.query import QuerySpec


@pytest.fixture
def kernel(tmp_path: Path):
    client = KernelClient.spawn(tmp_path)
    yield client
    client.close()


def test_execute_round_trip(kernel: KernelClient):
    result = kernel.execute("df = pl.DataFrame({'a': [1, 2, 3]})")
    assert result.status == "ok"
    assert result.writes == ["df"]
    assert kernel.describe("df").rows == 3
    assert [m.name for m in kernel.list_datasets()] == ["df"]


def test_query_round_trip(kernel: KernelClient):
    kernel.execute("df = pl.DataFrame({'a': [3, 1, 2]})")
    out = kernel.query(QuerySpec(dataset="df", sort=[{"col": "a"}], limit=2))
    assert out.rows == [{"a": 1}, {"a": 2}]


def test_snapshot_round_trip(kernel: KernelClient, tmp_path: Path):
    kernel.execute("df = pl.DataFrame({'a': [1]})")
    kernel.snapshot("df", tmp_path / "out.parquet")
    assert pl.read_parquet(tmp_path / "out.parquet")["a"].to_list() == [1]


def test_error_response_raises_rpc_failure(kernel: KernelClient):
    with pytest.raises(RpcFailure) as info:
        kernel.describe("missing")
    assert info.value.type == "KeyError"


def test_interrupt_busy_loop(kernel: KernelClient):
    holder: dict[str, object] = {}

    def run() -> None:
        holder["result"] = kernel.execute("import time\nwhile True:\n    time.sleep(0.01)\n")

    thread = threading.Thread(target=run)
    thread.start()
    time.sleep(0.5)
    kernel.interrupt()
    thread.join(timeout=10)
    assert not thread.is_alive()
    result = holder["result"]
    assert getattr(result, "status", None) == "interrupted"
    assert kernel.execute("x = 1").status == "ok"


def test_kernel_crash_is_detected(kernel: KernelClient):
    with pytest.raises(KernelDead):
        kernel.execute("import os\nos._exit(3)\n")
    assert not kernel.is_alive()


def test_shutdown(kernel: KernelClient):
    kernel.shutdown()
    deadline = time.monotonic() + 5
    while kernel.is_alive() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not kernel.is_alive()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `uv run pytest tests/kernel/test_protocol.py tests/kernel/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError` for `quarry.kernel.protocol` and `quarry.kernel.client`

- [ ] **Step 4: Write protocol.py**

`src/quarry/kernel/protocol.py`:

```python
"""Newline-delimited JSON-RPC between the server and a kernel subprocess."""

from __future__ import annotations

from pydantic import BaseModel, Field

from quarry.query.spec import Json


class Request(BaseModel):
    id: int
    method: str
    params: dict[str, Json] = Field(default_factory=dict)


class RpcError(BaseModel):
    type: str
    message: str


class Response(BaseModel):
    id: int
    result: Json | None = None
    error: RpcError | None = None


def encode(msg: BaseModel) -> bytes:
    return msg.model_dump_json(by_alias=True).encode("utf-8") + b"\n"


def decode_request(line: bytes) -> Request:
    return Request.model_validate_json(line)


def decode_response(line: bytes) -> Response:
    return Response.model_validate_json(line)
```

- [ ] **Step 5: Write service.py**

`src/quarry/kernel/service.py`:

```python
"""Dispatch kernel RPC requests to the executor. Never raises."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ValidationError

from quarry.kernel.executor import Executor
from quarry.kernel.protocol import Request, Response, RpcError
from quarry.query.spec import Json, QueryError, QuerySpec


class UnknownMethod(Exception):
    pass


class KernelService:
    def __init__(self, executor: Executor) -> None:
        self._executor = executor

    def handle(self, request: Request) -> Response:
        try:
            result = self._dispatch(request.method, request.params)
        except (UnknownMethod, KeyError, QueryError, ValidationError, TypeError, ValueError, OSError) as exc:
            return Response(id=request.id, error=RpcError(type=type(exc).__name__, message=str(exc)))
        return Response(id=request.id, result=_jsonable(result))

    def _dispatch(self, method: str, params: dict[str, Json]) -> BaseModel | list[BaseModel] | None:
        match method:
            case "execute":
                return self._executor.execute(_text(params, "code"))
            case "describe":
                return self._executor.describe(_text(params, "name"))
            case "list_datasets":
                return self._executor.list_datasets()
            case "query":
                return self._executor.query(QuerySpec.model_validate(params.get("spec")))
            case "snapshot":
                return self._executor.snapshot(_text(params, "name"), Path(_text(params, "path")))
            case "shutdown":
                return None
            case _:
                raise UnknownMethod(method)


def _text(params: dict[str, Json], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str):
        raise TypeError(f"param {key!r} must be a string")
    return value


def _jsonable(value: BaseModel | list[BaseModel] | None) -> Json:
    if value is None:
        return None
    if isinstance(value, list):
        return [item.model_dump(by_alias=True, mode="json") for item in value]
    dumped: Json = value.model_dump(by_alias=True, mode="json")
    return dumped
```

- [ ] **Step 6: Write `__main__.py`**

`src/quarry/kernel/__main__.py`:

```python
"""Kernel subprocess entry: python -m quarry.kernel --socket PATH --root ROOT."""

from __future__ import annotations

import argparse
import os
import queue
import resource
import signal
import socket
import sys
import threading
from pathlib import Path

import duckdb
import polars as pl

from quarry.config import load_config
from quarry.kernel.executor import Executor
from quarry.kernel.protocol import Request, Response, decode_request, encode
from quarry.kernel.service import KernelService


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--socket", required=True)
    parser.add_argument("--root", required=True)
    args = parser.parse_args()
    config = load_config(Path(args.root))
    if config.data.kernel_memory_mb > 0:
        limit = config.data.kernel_memory_mb * 1024 * 1024
        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    namespace: dict[str, object] = {"pl": pl, "duckdb": duckdb}
    service = KernelService(Executor(namespace, row_cap=config.data.row_cap))
    conn = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    conn.connect(args.socket)
    serve(conn, service)


def serve(conn: socket.socket, service: KernelService) -> None:
    signal.signal(signal.SIGINT, signal.default_int_handler)
    write_lock = threading.Lock()
    execute_queue: queue.Queue[Request | None] = queue.Queue()

    def send(response: Response) -> None:
        with write_lock:
            conn.sendall(encode(response))

    def reader() -> None:
        buffer = b""
        while True:
            chunk = conn.recv(65536)
            if not chunk:
                execute_queue.put(None)
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                request = decode_request(line)
                if request.method == "execute":
                    execute_queue.put(request)
                elif request.method == "interrupt":
                    os.kill(os.getpid(), signal.SIGINT)
                    send(Response(id=request.id, result=None))
                elif request.method == "shutdown":
                    send(service.handle(request))
                    execute_queue.put(None)
                    return
                else:
                    send(service.handle(request))

    threading.Thread(target=reader, daemon=True).start()
    while True:
        try:
            request = execute_queue.get()
        except KeyboardInterrupt:
            continue
        if request is None:
            break
        send(service.handle(request))
    conn.close()
    sys.exit(0)


if __name__ == "__main__":
    main()
```

Note on interrupt timing: `SIGINT` raises `KeyboardInterrupt` in the main thread. If it lands while the main thread is idle in `execute_queue.get()`, the `except KeyboardInterrupt: continue` swallows it. If it lands inside `exec`, the executor reports `interrupted`.

- [ ] **Step 7: Write client.py**

`src/quarry/kernel/client.py`:

```python
"""Spawn and drive a kernel subprocess over a Unix socket."""

from __future__ import annotations

import itertools
import socket
import subprocess
import sys
import tempfile
import threading
from concurrent.futures import Future
from pathlib import Path

from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import ExecResult, QueryResult
from quarry.kernel.protocol import Request, Response, decode_response, encode
from quarry.query.spec import Json, QuerySpec


class KernelDead(Exception):
    """The kernel process exited or its socket broke."""


class RpcFailure(Exception):
    def __init__(self, type_: str, message: str) -> None:
        super().__init__(f"{type_}: {message}")
        self.type = type_
        self.message = message


class KernelClient:
    def __init__(self, process: subprocess.Popen[bytes], conn: socket.socket, tmpdir: tempfile.TemporaryDirectory[str]) -> None:
        self._process = process
        self._conn = conn
        self._tmpdir = tmpdir
        self._ids = itertools.count(1)
        self._pending: dict[int, Future[Response]] = {}
        self._lock = threading.Lock()
        self._dead = False
        threading.Thread(target=self._reader, daemon=True).start()

    @classmethod
    def spawn(cls, root: Path, *, startup_timeout: float = 30.0) -> KernelClient:
        tmpdir = tempfile.TemporaryDirectory(prefix="quarry-kernel-")
        socket_path = Path(tmpdir.name) / "kernel.sock"
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(socket_path))
        listener.listen(1)
        listener.settimeout(startup_timeout)
        process = subprocess.Popen(
            [sys.executable, "-m", "quarry.kernel", "--socket", str(socket_path), "--root", str(root)],
            stdin=subprocess.DEVNULL,
        )
        try:
            conn, _ = listener.accept()
        except TimeoutError as exc:
            process.kill()
            raise KernelDead("kernel did not connect in time") from exc
        finally:
            listener.close()
        return cls(process, conn, tmpdir)

    def execute(self, code: str) -> ExecResult:
        return ExecResult.model_validate(self._call("execute", {"code": code}))

    def interrupt(self) -> None:
        self._call("interrupt", {})

    def describe(self, name: str) -> DatasetMeta:
        return DatasetMeta.model_validate(self._call("describe", {"name": name}))

    def list_datasets(self) -> list[DatasetMeta]:
        result = self._call("list_datasets", {})
        if not isinstance(result, list):
            raise RpcFailure("BadResult", "list_datasets did not return a list")
        return [DatasetMeta.model_validate(item) for item in result]

    def query(self, spec: QuerySpec) -> QueryResult:
        return QueryResult.model_validate(self._call("query", {"spec": spec.model_dump(mode="json")}))

    def snapshot(self, name: str, path: Path) -> DatasetMeta:
        return DatasetMeta.model_validate(self._call("snapshot", {"name": name, "path": str(path)}))

    def shutdown(self) -> None:
        try:
            self._call("shutdown", {})
        except KernelDead:
            pass

    def is_alive(self) -> bool:
        return not self._dead and self._process.poll() is None

    def close(self) -> None:
        if self.is_alive():
            self._process.kill()
        self._process.wait(timeout=5)
        self._conn.close()
        self._tmpdir.cleanup()

    def _call(self, method: str, params: dict[str, Json]) -> Json:
        if not self.is_alive():
            raise KernelDead("kernel is not running")
        request = Request(id=next(self._ids), method=method, params=params)
        future: Future[Response] = Future()
        with self._lock:
            self._pending[request.id] = future
        try:
            self._conn.sendall(encode(request))
        except OSError as exc:
            self._mark_dead()
            raise KernelDead("kernel socket closed") from exc
        response = future.result()
        if response.error is not None:
            raise RpcFailure(response.error.type, response.error.message)
        return response.result

    def _reader(self) -> None:
        buffer = b""
        while True:
            try:
                chunk = self._conn.recv(65536)
            except OSError:
                chunk = b""
            if not chunk:
                self._mark_dead()
                return
            buffer += chunk
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                response = decode_response(line)
                with self._lock:
                    future = self._pending.pop(response.id, None)
                if future is not None:
                    future.set_result(response)

    def _mark_dead(self) -> None:
        self._dead = True
        with self._lock:
            pending = list(self._pending.values())
            self._pending.clear()
        for future in pending:
            if not future.done():
                future.set_exception(KernelDead("kernel exited"))
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/kernel -v`
Expected: all pass, including the subprocess tests. If `test_kernel_crash_is_detected` hangs, the reader thread is not seeing EOF: confirm `_mark_dead` sets exceptions on pending futures and that `os._exit` closes the socket (it does). If `test_interrupt_busy_loop` reports `ok` instead of `interrupted`, the signal arrived before `exec` started; raise the sleep to one second.

- [ ] **Step 9: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/kernel tests/kernel
git commit -m "feat(kernel): JSON-RPC subprocess with interrupt, crash detection, and client"
```

---

### Task 11: Data layer and kernel namespace

**Files:**

- Create: `src/quarry/data/__init__.py`
- Create: `src/quarry/data/loaders.py`
- Create: `src/quarry/data/mssql.py`
- Create: `src/quarry/data/parquet.py`
- Create: `src/quarry/data/namespace.py`
- Modify: `src/quarry/kernel/__main__.py` (replace the placeholder namespace line)
- Test: `tests/data/__init__.py`
- Test: `tests/data/test_loaders.py`
- Test: `tests/data/test_mssql.py`
- Test: `tests/data/test_parquet.py`
- Test: `tests/data/test_namespace.py`
- Test: `tests/data/fake_firmlib.py`

**Interfaces:**

- Consumes: `QuarryConfig` (Task 2).
- Produces:
  - `quarry.data.loaders`: `class LoaderSpec(BaseModel)`: `name: str`, `description: str`, `import_: str` (alias `import`, form `module:function`), `signature: str`; `class LoaderFailure(BaseModel)`: `name: str`, `error: str`; `@dataclass(slots=True) class LoaderRegistry`: `specs: list[LoaderSpec]`, `functions: dict[str, Callable[..., object]]`, `failures: list[LoaderFailure]`; method `bound(self) -> Loaders` returning a namespace object with each loader as an attribute; `def load_loaders(path: Path) -> LoaderRegistry` (empty registry when the file is absent); `def describe_loaders(registry: LoaderRegistry) -> str` rendering one line per loader for the agent prompt.
  - `quarry.data.mssql`: `BatchReader = Callable[[str, str, Sequence[object] | None], Iterable[pa.RecordBatch]]`; `def make_sql(dsn: str, reader: BatchReader | None = None) -> Callable[..., pl.DataFrame]` returning `sql(query: str, *, params: Sequence[object] | None = None) -> pl.DataFrame`. The default reader wraps `arrow_odbc.read_arrow_batches_from_odbc`, imported lazily so the extra is optional. An empty `dsn` makes `sql` raise `RuntimeError("SQL Server DSN not configured")`.
  - `quarry.data.parquet`: `class PartitionLayout(BaseModel)`: `dataset: str`, `keys: list[str]`; `class ParquetCatalog`: `__init__(self, root: Path | None, conn: duckdb.DuckDBPyConnection)`; `pq(self, relative_glob: str) -> duckdb.DuckDBPyRelation` (`read_parquet` with `hive_partitioning=true` over `root / relative_glob`); `sql_local(self, query: str) -> duckdb.DuckDBPyRelation`; `register(self, name: str, frame: pl.DataFrame) -> None`; `def scan_layout(root: Path) -> list[PartitionLayout]` (two levels deep, `key=value` directory names).
  - `quarry.data.namespace`: `def build_namespace(config: QuarryConfig) -> dict[str, object]` with keys `pl`, `duckdb`, `loaders`, `sql`, `pq`, `sql_local`, `catalog`, `_conn`, `_registry`.

- [ ] **Step 1: Write the fake firm library and failing loader tests**

`tests/data/__init__.py`: empty.

`tests/data/fake_firmlib.py`:

```python
import polars as pl


def load_daily(tickers: list[str]) -> pl.DataFrame:
    return pl.DataFrame({"ticker": tickers, "ret": [0.01] * len(tickers)})
```

`tests/data/test_loaders.py`:

```python
from pathlib import Path

from quarry.data.loaders import describe_loaders, load_loaders


def write(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "loaders.toml"
    path.write_text(body)
    return path


def test_missing_file_is_empty_registry(tmp_path: Path):
    reg = load_loaders(tmp_path / "loaders.toml")
    assert reg.specs == [] and reg.functions == {} and reg.failures == []


def test_loads_and_binds(tmp_path: Path):
    path = write(
        tmp_path,
        '[[loader]]\nname = "daily_returns"\ndescription = "Daily returns"\n'
        'import = "tests.data.fake_firmlib:load_daily"\n'
        'signature = "load_daily(tickers: list[str]) -> pl.DataFrame"\n',
    )
    reg = load_loaders(path)
    assert [s.name for s in reg.specs] == ["daily_returns"]
    assert reg.failures == []
    out = reg.bound().daily_returns(["AAPL"])
    assert out["ticker"].to_list() == ["AAPL"]


def test_bad_import_is_a_failure_not_an_exception(tmp_path: Path):
    path = write(
        tmp_path,
        '[[loader]]\nname = "broken"\ndescription = "x"\nimport = "no.such.module:fn"\nsignature = "fn()"\n',
    )
    reg = load_loaders(path)
    assert reg.functions == {}
    assert reg.failures[0].name == "broken"
    assert "no.such.module" in reg.failures[0].error


def test_describe_loaders_renders_one_line_each(tmp_path: Path):
    path = write(
        tmp_path,
        '[[loader]]\nname = "daily_returns"\ndescription = "Daily returns"\n'
        'import = "tests.data.fake_firmlib:load_daily"\nsignature = "load_daily(tickers)"\n',
    )
    text = describe_loaders(load_loaders(path))
    assert text == "loaders.daily_returns: load_daily(tickers) -- Daily returns"
```

- [ ] **Step 2: Write the failing mssql tests**

`tests/data/test_mssql.py`:

```python
from collections.abc import Iterable, Sequence

import pyarrow as pa
import pytest

from quarry.data.mssql import make_sql


def fake_reader(query: str, dsn: str, params: Sequence[object] | None) -> Iterable[pa.RecordBatch]:
    assert dsn == "dsn-x"
    assert "FROM prices" in query
    yield pa.RecordBatch.from_pydict({"ticker": ["A"], "px": [1.5]})
    yield pa.RecordBatch.from_pydict({"ticker": ["B"], "px": [2.5]})


def test_sql_concatenates_batches_into_polars():
    sql = make_sql("dsn-x", reader=fake_reader)
    df = sql("SELECT * FROM prices")
    assert df["ticker"].to_list() == ["A", "B"]
    assert df["px"].to_list() == [1.5, 2.5]


def test_sql_with_no_rows_returns_empty_frame_with_schema():
    def empty(query: str, dsn: str, params: Sequence[object] | None) -> Iterable[pa.RecordBatch]:
        return iter(())

    df = make_sql("dsn-x", reader=empty)("SELECT 1")
    assert df.height == 0


def test_sql_without_dsn_raises():
    with pytest.raises(RuntimeError, match="DSN"):
        make_sql("", reader=fake_reader)("SELECT 1")
```

- [ ] **Step 3: Write the failing parquet tests**

`tests/data/test_parquet.py`:

```python
from pathlib import Path

import duckdb
import polars as pl

from quarry.data.parquet import ParquetCatalog, scan_layout


def build_cache(root: Path) -> None:
    for year in (2023, 2024):
        for month in (1, 2):
            path = root / "prices" / f"year={year}" / f"month={month}"
            path.mkdir(parents=True)
            pl.DataFrame({"ticker": ["A"], "px": [float(year + month)]}).write_parquet(path / "part.parquet")
    (root / "notes.txt").write_text("ignored")


def test_scan_layout_reports_partition_keys(tmp_path: Path):
    build_cache(tmp_path)
    layout = scan_layout(tmp_path)
    assert [(l.dataset, l.keys) for l in layout] == [("prices", ["year", "month"])]


def test_scan_layout_of_missing_root_is_empty(tmp_path: Path):
    assert scan_layout(tmp_path / "missing") == []


def test_pq_reads_with_hive_partitioning(tmp_path: Path):
    build_cache(tmp_path)
    catalog = ParquetCatalog(tmp_path, duckdb.connect())
    rel = catalog.pq("prices/**/*.parquet")
    df = rel.filter("year = 2024").pl()
    assert set(df.columns) >= {"ticker", "px", "year", "month"}
    assert df.height == 2


def test_register_and_sql_local(tmp_path: Path):
    catalog = ParquetCatalog(None, duckdb.connect())
    catalog.register("frame", pl.DataFrame({"a": [1, 2]}))
    assert catalog.sql_local("SELECT sum(a) AS s FROM frame").pl()["s"].to_list() == [3]


def test_pq_without_root_raises(tmp_path: Path):
    import pytest

    catalog = ParquetCatalog(None, duckdb.connect())
    with pytest.raises(RuntimeError, match="parquet_root"):
        catalog.pq("x/*.parquet")
```

- [ ] **Step 4: Write the failing namespace test**

`tests/data/test_namespace.py`:

```python
from pathlib import Path

import polars as pl

from quarry.config import QuarryConfig
from quarry.data.namespace import build_namespace


def test_namespace_has_expected_names(tmp_path: Path):
    (tmp_path / "loaders.toml").write_text(
        '[[loader]]\nname = "daily_returns"\ndescription = "d"\n'
        'import = "tests.data.fake_firmlib:load_daily"\nsignature = "load_daily(tickers)"\n'
    )
    ns = build_namespace(QuarryConfig(root=tmp_path))
    assert {"pl", "duckdb", "loaders", "sql", "pq", "sql_local", "catalog"} <= set(ns)
    assert ns["pl"] is pl
    assert ns["loaders"].daily_returns(["X"])["ticker"].to_list() == ["X"]


def test_registered_frames_are_visible_to_sql_local(tmp_path: Path):
    ns = build_namespace(QuarryConfig(root=tmp_path))
    ns["catalog"].register("f", pl.DataFrame({"a": [4]}))
    assert ns["sql_local"]("SELECT a FROM f").pl()["a"].to_list() == [4]
```

- [ ] **Step 5: Run tests to verify they fail**

Run: `uv run pytest tests/data -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.data'`

- [ ] **Step 6: Write loaders.py**

`src/quarry/data/__init__.py`: empty docstring module.

`src/quarry/data/loaders.py`:

```python
"""Registry of the firm's internal loader functions, declared in loaders.toml."""

from __future__ import annotations

import importlib
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field


class LoaderSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str
    import_: str = Field(alias="import")
    signature: str


class LoaderFailure(BaseModel):
    name: str
    error: str


Loaders = SimpleNamespace


@dataclass(slots=True)
class LoaderRegistry:
    specs: list[LoaderSpec] = field(default_factory=list)
    functions: dict[str, Callable[..., object]] = field(default_factory=dict)
    failures: list[LoaderFailure] = field(default_factory=list)

    def bound(self) -> Loaders:
        return SimpleNamespace(**self.functions)


def load_loaders(path: Path) -> LoaderRegistry:
    registry = LoaderRegistry()
    if not path.exists():
        return registry
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    for entry in raw.get("loader", []):
        spec = LoaderSpec.model_validate(entry)
        registry.specs.append(spec)
        try:
            registry.functions[spec.name] = _import(spec.import_)
        except (ImportError, AttributeError, ValueError) as exc:
            registry.failures.append(LoaderFailure(name=spec.name, error=str(exc)))
    return registry


def describe_loaders(registry: LoaderRegistry) -> str:
    return "\n".join(
        f"loaders.{s.name}: {s.signature} -- {s.description}"
        for s in registry.specs
        if s.name in registry.functions
    )


def _import(target: str) -> Callable[..., object]:
    module_name, _, attr = target.partition(":")
    if not module_name or not attr:
        raise ValueError(f"import must look like module:function, got {target!r}")
    module = importlib.import_module(module_name)
    func = getattr(module, attr)
    if not callable(func):
        raise ValueError(f"{target} is not callable")
    return func  # type: ignore[no-any-return]
```

- [ ] **Step 7: Write mssql.py**

`src/quarry/data/mssql.py`:

```python
"""SQL Server access returning polars frames via Arrow."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import polars as pl
import pyarrow as pa

BatchReader = Callable[[str, str, Sequence[object] | None], Iterable[pa.RecordBatch]]
SqlFn = Callable[..., pl.DataFrame]


def make_sql(dsn: str, reader: BatchReader | None = None) -> SqlFn:
    read = reader or _odbc_reader

    def sql(query: str, *, params: Sequence[object] | None = None) -> pl.DataFrame:
        if not dsn:
            raise RuntimeError("SQL Server DSN not configured: set data.mssql_dsn or QUARRY_MSSQL_DSN")
        batches = list(read(query, dsn, params))
        if not batches:
            return pl.DataFrame()
        table = pa.Table.from_batches(batches)
        frame = pl.from_arrow(table)
        if not isinstance(frame, pl.DataFrame):
            raise TypeError("expected a DataFrame from Arrow table")
        return frame

    return sql


def _odbc_reader(query: str, dsn: str, params: Sequence[object] | None) -> Iterable[pa.RecordBatch]:
    from arrow_odbc import read_arrow_batches_from_odbc

    return read_arrow_batches_from_odbc(query=query, connection_string=dsn, parameters=list(params or []))
```

- [ ] **Step 8: Write parquet.py**

`src/quarry/data/parquet.py`:

```python
"""DuckDB over the Hive-partitioned parquet cache, plus local frame registration."""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl
from pydantic import BaseModel


class PartitionLayout(BaseModel):
    dataset: str
    keys: list[str]


class ParquetCatalog:
    def __init__(self, root: Path | None, conn: duckdb.DuckDBPyConnection) -> None:
        self._root = root
        self._conn = conn

    def pq(self, relative_glob: str) -> duckdb.DuckDBPyRelation:
        if self._root is None:
            raise RuntimeError("parquet_root is not configured")
        pattern = str(self._root / relative_glob).replace("'", "''")
        return self._conn.sql(f"SELECT * FROM read_parquet('{pattern}', hive_partitioning = true)")

    def sql_local(self, query: str) -> duckdb.DuckDBPyRelation:
        return self._conn.sql(query)

    def register(self, name: str, frame: pl.DataFrame) -> None:
        self._conn.register(name, frame)


def scan_layout(root: Path) -> list[PartitionLayout]:
    if not root.is_dir():
        return []
    layouts: list[PartitionLayout] = []
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        keys: list[str] = []
        current = dataset_dir
        for _ in range(2):
            children = sorted(p for p in current.iterdir() if p.is_dir() and "=" in p.name)
            if not children:
                break
            keys.append(children[0].name.split("=", 1)[0])
            current = children[0]
        if keys:
            layouts.append(PartitionLayout(dataset=dataset_dir.name, keys=keys))
    return layouts
```

- [ ] **Step 9: Write namespace.py and wire it into the kernel**

`src/quarry/data/namespace.py`:

```python
"""The namespace every kernel starts with."""

from __future__ import annotations

import duckdb
import polars as pl

from quarry.config import QuarryConfig
from quarry.data.loaders import load_loaders
from quarry.data.mssql import make_sql
from quarry.data.parquet import ParquetCatalog


def build_namespace(config: QuarryConfig) -> dict[str, object]:
    conn = duckdb.connect()
    registry = load_loaders(config.root / "loaders.toml")
    catalog = ParquetCatalog(config.data.parquet_root, conn)
    return {
        "pl": pl,
        "duckdb": duckdb,
        "loaders": registry.bound(),
        "sql": make_sql(config.data.mssql_dsn),
        "pq": catalog.pq,
        "sql_local": catalog.sql_local,
        "catalog": catalog,
        "_conn": conn,
        "_registry": registry,
    }
```

In `src/quarry/kernel/__main__.py`, replace

```python
    namespace: dict[str, object] = {"pl": pl, "duckdb": duckdb}
```

with

```python
    namespace = build_namespace(config)
```

add `from quarry.data.namespace import build_namespace`, and remove the now-unused `import duckdb` and `import polars as pl` lines.

- [ ] **Step 10: Run tests to verify they pass**

Run: `uv run pytest -v`
Expected: every test in the repository passes, including the kernel subprocess tests, which now start with the full namespace.

- [ ] **Step 11: Format, lint, type check, commit**

```bash
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add src/quarry/data src/quarry/kernel/__main__.py tests/data
git commit -m "feat(data): loader registry, SQL Server via arrow-odbc, parquet catalog, kernel namespace"
```

---

### Task 12: End-to-end core check and REPL usage docs

**Files:**

- Test: `tests/test_end_to_end_core.py`
- Modify: `README.md`

**Interfaces:**

- Consumes: `KernelClient` (Task 10), `build_cache`-style parquet layout, `QuerySpec`, `to_source` (Task 6).
- Produces: a documented REPL flow and one test that exercises the whole Stage 1 path through the subprocess: load from the parquet cache via `pq`, filter in polars, query both backings through the socket, render the query as source, run that source in the kernel, and snapshot.

- [ ] **Step 1: Write the failing end-to-end test**

`tests/test_end_to_end_core.py`:

```python
from pathlib import Path

import polars as pl
import pytest

from quarry.kernel.client import KernelClient
from quarry.query import Filter, QuerySpec, to_source


def build_cache(root: Path) -> None:
    for year in (2023, 2024):
        path = root / "prices" / f"year={year}"
        path.mkdir(parents=True)
        pl.DataFrame({"ticker": ["A", "B"], "px": [1.0 * year, 2.0 * year]}).write_parquet(path / "p.parquet")


@pytest.fixture
def kernel(tmp_path: Path):
    build_cache(tmp_path / "cache")
    (tmp_path / "config.toml").write_text(f'[data]\nparquet_root = "{tmp_path / "cache"}"\nrow_cap = 100\n')
    client = KernelClient.spawn(tmp_path)
    yield client
    client.close()


def test_core_path(kernel: KernelClient, tmp_path: Path):
    loaded = kernel.execute("prices = pq('prices/**/*.parquet')")
    assert loaded.status == "ok"
    assert loaded.datasets[0].backing == "duckdb"

    recent = kernel.execute("recent = prices.filter('year = 2024').pl()")
    assert recent.reads == ["prices"]
    assert recent.datasets[0].backing == "polars"
    assert recent.datasets[0].rows == 2

    spec = QuerySpec(dataset="recent", filters=[Filter(col="ticker", op="eq", value="B")])
    assert kernel.query(spec).rows == [{"ticker": "B", "px": 4048.0, "year": 2024}]

    spec_rel = QuerySpec(dataset="prices", filters=[Filter(col="year", op="eq", value=2023)], sort=[{"col": "ticker"}])
    assert [r["px"] for r in kernel.query(spec_rel).rows or []] == [2023.0, 4046.0]

    source = to_source(spec, "polars", result_name="only_b")
    materialized = kernel.execute(source)
    assert materialized.status == "ok"
    assert materialized.reads == ["recent"]
    assert materialized.writes == ["only_b"]

    meta = kernel.snapshot("only_b", tmp_path / "only_b.parquet")
    assert meta.rows == 1
```

- [ ] **Step 2: Run the test to verify it fails or passes**

Run: `uv run pytest tests/test_end_to_end_core.py -v`
Expected: PASS if Tasks 1 through 11 are complete. If it fails, the failure identifies the seam that leaks: a `KeyError` means the dataset name was not registered (check `dataset_names` and the `_` prefix rule), a `QueryError` on `year` means DuckDB's hive column did not arrive (check `hive_partitioning = true`), a wrong `px` means the glob matched only one partition, and `"year": "2024"` as a string means the installed DuckDB did not autocast hive types; in that case add `hive_types_autocast = true` to the `read_parquet` call in `ParquetCatalog.pq`.

- [ ] **Step 3: Document the REPL flow in the README**

Append to `README.md`:

````markdown
## Using the core from a REPL (Stage 1)

```python
from pathlib import Path
from quarry.kernel.client import KernelClient
from quarry.query import QuerySpec, Filter, to_source

k = KernelClient.spawn(Path("~/.quarry").expanduser())
k.execute("prices = pq('prices/**/*.parquet')")
k.execute("recent = prices.filter('year = 2024').pl()")
k.query(QuerySpec(dataset="recent", filters=[Filter(col="ticker", op="eq", value="B")])).rows
print(to_source(QuerySpec(dataset="recent", limit=10), "polars"))
k.shutdown()
```

The kernel namespace starts with `pl`, `duckdb`, `loaders.<name>` for every
entry in `~/.quarry/loaders.toml`, `sql(query)` for SQL Server, `pq(glob)` for
the parquet cache, and `sql_local(query)` for DuckDB over registered frames.
````

- [ ] **Step 4: Run the full suite, format, lint, type check, commit**

```bash
uv run pytest -v
uv run ruff format src tests && uv run ruff check --fix src tests && uv run mypy src
git add tests/test_end_to_end_core.py README.md
git commit -m "test: end-to-end core path through the kernel subprocess; document REPL usage"
```

---

## Self-review notes

- Spec coverage for Stage 1: section 5 (Dataset, QuerySpec, Backing) in Tasks 3, 6, 8; section 6 (kernel methods, lineage, limits) in Tasks 7, 9, 10; section 7 (loaders, SQL Server, parquet catalog, compiler with three targets) in Tasks 4, 5, 6, 11; section 11 config in Task 2; section 14 tests for compiler equivalence, lineage, kernel-as-subprocess in Tasks 5, 7, 10. Restart-and-replay lives in the server (Stage 2) and is out of scope here.
- Known divergence: `to_source` infers date literals from string shape while `to_polars` uses the real dtype. Documented in the module docstring and covered by the equivalence test in Task 6 because every date-shaped fixture value targets a Date column.
- `first` and `last` aggregations are deliberately excluded from the cross-target fixture set because they are order-dependent in SQL.
- `RLIMIT_AS` is a no-op on macOS; the dev machines are Linux.
