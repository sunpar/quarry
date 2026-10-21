import copy
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Iterator, Mapping
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import NamedTuple

import duckdb
import nbformat
import polars as pl
import pytest

from quarry.kernel.datasets import Column
from quarry.kernel.executor import Executor
from quarry.projects.export import _recipe_order, dataset_script, notebook, notebook_json
from quarry.projects.models import SavedDatasetMeta, SavedViewMeta
from quarry.projects.store import ProjectStore
from quarry.query import Json, QuerySpec
from tests.fixtures import kept_default_connection

# Recipes `analyze` gives up on with RecursionError and MemoryError (or RecursionError, past
# 3.11), not SyntaxError.
UNPARSABLE = ["x = " + " + ".join(["1"] * 10_000), "x = " + "-" * 200_000 + "1"]

RECIPE = "prices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})\n"
VIEW_SOURCE = "export default function V() { return null }"
SETUP = "# Rebuilds Quarry's kernel namespace"


@pytest.fixture(autouse=True)
def namespace_contained(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """The setup cell configures DuckDB's default connection and makes a temp directory."""
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path))
    with kept_default_connection():
        yield


def project_with_saved_items(root: Path) -> ProjectStore:
    store = ProjectStore(root)
    store.create("Momentum", "a study")
    meta = SavedDatasetMeta(
        name="prices",
        description="closing prices",
        backing="polars",
        schema=[Column(name="ts", dtype="String"), Column(name="px", dtype="Float64")],
        rows=1,
        mode="live",
        saved_at="2026-10-09T00:00:00Z",
        source_session="s",
        source_step="t",
        validated=True,
    )
    store.write_dataset("momentum", meta, recipe=RECIPE, raw=RECIPE)
    view = SavedViewMeta(
        name="table",
        description="the table",
        datasets=["prices"],
        component_id="data-table",
        saved_at="2026-10-09T00:00:00Z",
        source_session="s",
        source_step="t",
    )
    store.write_view(
        "momentum",
        view,
        source=VIEW_SOURCE,
        state={"limit": 5},
        queries=[
            {"dataset": "prices", "sort": [{"col": "ts"}], "limit": 5},
            {"dataset": "prices", "limit": 0},
        ],
    )
    return store


def save_another_dataset(store: ProjectStore, name: str, recipe: str) -> None:
    saved = store.get("momentum").datasets[0].model_copy(update={"name": name})
    store.write_dataset("momentum", saved, recipe=recipe, raw=recipe)


class Cell(NamedTuple):
    kind: str
    source: str
    id: str


def cells_of(doc: Mapping[str, Json]) -> list[Cell]:
    """The notebook's cells, narrowed from its JSON."""
    raw = doc["cells"]
    assert isinstance(raw, list)
    cells: list[Cell] = []
    for cell in raw:
        assert isinstance(cell, dict)
        kind, source, cell_id = cell["cell_type"], cell["source"], cell["id"]
        assert isinstance(kind, str) and isinstance(source, str) and isinstance(cell_id, str)
        cells.append(Cell(kind, source, cell_id))
    return cells


def sources(doc: Mapping[str, Json], kind: str) -> list[str]:
    return [c.source for c in cells_of(doc) if c.kind == kind]


def run_code_cells(doc: Mapping[str, Json]) -> dict[str, object]:
    namespace: dict[str, object] = {}
    for source in sources(doc, "code"):
        exec(source, namespace)  # the test executes exported code on purpose
    return namespace


@pytest.mark.parametrize(
    ("recipe", "query", "expected"),
    [
        (
            "prices = pl.DataFrame({'ret': [0.0, 1.0, None]}).lazy()\n",
            {"dataset": "prices", "filters": [{"col": "ret", "op": "in", "value": [0]}]},
            [{"ret": 0.0}],
        ),
        (
            "prices = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03']})\n",
            {"dataset": "prices", "filters": [{"col": "ts", "op": "eq", "value": "2024-01-02"}]},
            [{"ts": "2024-01-02"}],
        ),
        (
            "from datetime import date\n"
            "prices = pl.DataFrame({'ts': [date(2024, 1, 2), date(2024, 1, 3)]})\n",
            {"dataset": "prices", "filters": [{"col": "ts", "op": "eq", "value": "2024-01-02"}]},
            [{"ts": date(2024, 1, 2)}],
        ),
        (
            "prices = pl.DataFrame({'k': ['a', 'a'], 'n': [9223372036854775807] * 2})\n",
            {"dataset": "prices", "group_by": ["k"], "aggs": [{"col": "n", "fn": "sum"}]},
            [{"k": "a", "n_sum": Decimal("18446744073709551614")}],
        ),
        (
            "prices = sql_local(\"SELECT INTERVAL '1 day' AS elapsed, "
            'union_value(x := 7) AS choice")\n',
            {"dataset": "prices"},
            [{"elapsed": "1 day", "choice": "7"}],
        ),
    ],
    ids=["float-in", "date-shaped-string", "date", "integer-sum", "relation-projection"],
)
def test_exported_queries_use_the_replayed_dataset_schema(
    tmp_path: Path, recipe: str, query: dict[str, Json], expected: list[dict[str, object]]
) -> None:
    store = project_with_saved_items(tmp_path)
    # Deliberately retain stale saved backing/schema: the recipe's actual object is authoritative.
    store.write_dataset("momentum", store.get("momentum").datasets[0], recipe=recipe, raw=recipe)
    store.write_view(
        "momentum", store.get("momentum").views[0], source=VIEW_SOURCE, state={}, queries=[query]
    )
    namespace = run_code_cells(notebook(store.get("momentum"), store))
    result = namespace["prices_1"]
    assert isinstance(result, pl.DataFrame) and result.to_dicts() == expected
    # To code uses the same replayed object; its result must agree even with stale disk metadata.
    to_code_namespace = {"pl": pl, "prices": namespace["prices"]}
    executor = Executor(to_code_namespace, conn=duckdb.default_connection(), row_cap=50_000)
    exec(executor.to_code([QuerySpec.model_validate(query)]).code, to_code_namespace)
    to_code_result = to_code_namespace["prices_1"]
    assert isinstance(to_code_result, pl.DataFrame) and to_code_result.equals(result)


def test_notebook_validates_and_runs(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    store = project_with_saved_items(tmp_path)
    doc = notebook(store.get("momentum"), store)
    # A copy: validate repairs what it can in place, such as a repeated cell id.
    nbformat.validate(copy.deepcopy(doc))
    cells = [(c.kind, c.source) for c in cells_of(doc)]
    expected = [
        ("markdown", "# Momentum\n\na study"),
        ("code", SETUP),
        ("markdown", "## prices\n\nclosing prices"),
        ("code", "prices = pl.DataFrame"),
        ("markdown", "## View: table\n\nthe table"),
        ("code", "# Render against"),
        ("markdown", "```tsx\nexport default"),
    ]
    assert len(cells) == len(expected)
    for (kind, source), (want_kind, prefix) in zip(cells, expected, strict=True):
        assert kind == want_kind and source.startswith(prefix), (kind, source[:40])
    assert f"load_config(Path({str(tmp_path)!r}))" in cells[1][1]
    namespace = run_code_cells(doc)
    code = capsys.readouterr().out
    assert "prices_1 = (" in code and "# query 2 could not be rendered:" in code
    assert isinstance(namespace["prices_1"], pl.DataFrame)
    ids = [c.id for c in cells_of(doc)]
    assert len(set(ids)) == len(ids)
    assert notebook(store.get("momentum"), store) == doc  # an export is reproducible
    assert json.loads(notebook_json(store.get("momentum"), store))["nbformat"] == 4
    metadata = doc["metadata"]
    assert isinstance(metadata, dict)
    quarry_metadata = metadata["quarry"]
    assert isinstance(quarry_metadata, dict)
    environment = quarry_metadata["export_environment"]
    assert isinstance(environment, dict) and set(environment) == {
        "quarry",
        "python",
        "polars",
        "duckdb",
    }
    assert all(isinstance(version, str) and version for version in environment.values())


def test_export_generation_does_not_run_recipes(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    marker = tmp_path / "recipe-ran"
    recipe = f"Path({str(marker)!r}).touch()\n" + RECIPE
    store.write_dataset("momentum", store.get("momentum").datasets[0], recipe=recipe, raw=recipe)
    doc = notebook(store.get("momentum"), store)
    assert not marker.exists()
    run_code_cells(doc)
    assert marker.exists()


def test_a_result_name_never_overwrites_a_saved_dataset(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    save_another_dataset(
        store, "prices_1", "prices_1 = sql_local('SELECT 9 AS a FROM prices').pl()\n"
    )
    table = store.get("momentum").views[0]
    store.write_view(
        "momentum",
        table.model_copy(update={"name": "chart"}),
        source=VIEW_SOURCE,
        state={},
        queries=[{"dataset": "prices", "limit": 1}],
    )
    doc = notebook(store.get("momentum"), store)
    # chart sorts before table: its query skips the saved prices_1, and table's skips chart's too.
    namespace = run_code_cells(doc)
    assert isinstance(namespace["prices_2"], pl.DataFrame)
    saved = namespace["prices_1"]
    assert isinstance(saved, pl.DataFrame) and saved["a"].to_list() == [9]
    assert isinstance(namespace["prices_3"], pl.DataFrame)


def test_query_results_preserve_recipe_bindings_and_helper_names(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    recipe = "prices_1 = 'keep this helper'\nrun_queries = pl.DataFrame({'a': [9]})\n" + RECIPE
    store.write_dataset("momentum", store.get("momentum").datasets[0], recipe=recipe, raw=recipe)
    namespace = run_code_cells(notebook(store.get("momentum"), store))
    assert namespace["prices_1"] == "keep this helper"
    assert isinstance(namespace["prices_2"], pl.DataFrame)
    helper_name = namespace["run_queries"]
    assert isinstance(helper_name, pl.DataFrame) and helper_name.to_dicts() == [{"a": 9}]


@pytest.mark.parametrize(
    ("name", "binding_name"),
    [
        ("globals", "globals"),
        ("__import__", "__import__"),
        ("__builtins__", "__builtins__"),
        ("exec", "exec"),
        ("_quarry_queries_1", "_quarry_queries_1"),
        (
            "_\uff51\uff55\uff41\uff52\uff52\uff59_\uff51\uff55\uff45\uff52\uff49\uff45\uff53_1",
            "_quarry_queries_1",
        ),
    ],
)
def test_runtime_rendering_preserves_recipes_that_shadow_builtins(
    tmp_path: Path, name: str, binding_name: str
) -> None:
    store = project_with_saved_items(tmp_path)
    recipe = f"{name} = pl.DataFrame({{'a': [9]}})\n" + RECIPE
    store.write_dataset("momentum", store.get("momentum").datasets[0], recipe=recipe, raw=recipe)
    namespace = run_code_cells(notebook(store.get("momentum"), store))
    result = namespace["prices_1"]
    assert isinstance(result, pl.DataFrame) and result.to_dicts() == [
        {"ts": "2024-01-02", "px": 1.0}
    ]
    binding = namespace[binding_name]
    assert isinstance(binding, pl.DataFrame) and binding.to_dicts() == [{"a": 9}]


def test_runtime_callable_survives_recipe_exception_aliases(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    recipe = (
        "try:\n    raise ValueError()\nexcept ValueError as _quarry_queries_1:\n    pass\n" + RECIPE
    )
    store.write_dataset("momentum", store.get("momentum").datasets[0], recipe=recipe, raw=recipe)
    namespace = run_code_cells(notebook(store.get("momentum"), store))
    result = namespace["prices_1"]
    assert isinstance(result, pl.DataFrame) and result.to_dicts() == [
        {"ts": "2024-01-02", "px": 1.0}
    ]
    assert "_quarry_queries_1" not in namespace


@pytest.mark.parametrize(
    "bad_query",
    [
        {"dataset": "prices-invalid"},
        {"dataset": "prices", "filters": [{"col": "px", "op": "eq", "value": float("nan")}]},
        {"dataset": "prices", "filters": [{"col": "px", "op": "eq", "value": float("inf")}]},
    ],
    ids=["invalid-identifier", "nan", "infinity"],
)
def test_malformed_query_stays_a_comment_and_valid_siblings_run(
    tmp_path: Path, bad_query: dict[str, Json], capsys: pytest.CaptureFixture[str]
) -> None:
    store = project_with_saved_items(tmp_path)
    store.write_view(
        "momentum",
        store.get("momentum").views[0],
        source=VIEW_SOURCE,
        state={},
        queries=[bad_query, {"dataset": "prices", "limit": 1}],
    )
    namespace = run_code_cells(notebook(store.get("momentum"), store))
    result = namespace["prices_2"]
    assert isinstance(result, pl.DataFrame) and result.to_dicts() == [
        {"ts": "2024-01-02", "px": 1.0}
    ]
    assert "# query 1 could not be rendered:" in capsys.readouterr().out


def test_a_query_whose_import_would_rebind_a_saved_dataset_is_not_rendered(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    store = project_with_saved_items(tmp_path)
    recipe = (
        "prices = pl.DataFrame({'ts': ['2024-01-02']}).with_columns(pl.col('ts').str.to_date())\n"
    )
    store.write_dataset("momentum", store.get("momentum").datasets[0], recipe=recipe, raw=recipe)
    save_another_dataset(store, "date", "import polars as pl\ndate = pl.DataFrame({'a': [1]})\n")
    since: dict[str, Json] = {
        "dataset": "prices",
        "filters": [{"col": "ts", "op": "ge", "value": "2024-01-01"}],
    }
    store.write_view(
        "momentum",
        store.get("momentum").views[0],
        source=VIEW_SOURCE,
        state={},
        queries=[since, {"dataset": "prices", "limit": 1}],
    )
    doc = notebook(store.get("momentum"), store)
    namespace = run_code_cells(doc)
    code = capsys.readouterr().out
    assert "# query 1 could not be rendered: dataset 'date' would be shadowed" in code
    # The failed query keeps its position number.
    assert "from datetime import" not in code and "prices_2 = (" in code
    saved = namespace["date"]
    assert isinstance(saved, pl.DataFrame) and saved["a"].to_list() == [1]


def test_an_unrendered_query_stays_a_comment_whatever_its_error_says(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = project_with_saved_items(tmp_path)
    hostile: dict[str, Json] = {"dataset": "prices", "x\rimport sys; sys.exit(3)\n\x00\u202e": 1}
    store.write_view(
        "momentum", store.get("momentum").views[0], source=VIEW_SOURCE, state={}, queries=[hostile]
    )
    doc = notebook(store.get("momentum"), store)
    # The key's line breaks would run the rest as code, and a NUL stops it compiling.
    run_code_cells(doc)
    code = capsys.readouterr().out
    assert "# query 1 could not be rendered:" in code
    assert "\\u0000\\u202e" in code and "\x00" not in code


def test_dataset_script_has_a_header_and_the_recipe(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    script = dataset_script(store.get("momentum"), store, "prices")
    assert script.startswith("# prices: closing prices\n# Saved from Quarry project Momentum")
    assert f"\n\n{SETUP}" in script and script.endswith(f"\n\n{RECIPE}")
    path = tmp_path / "prices.py"
    path.write_text(script + "print(prices.height)\n")
    # A fresh interpreter; -I keeps the working directory and PYTHONPATH off sys.path.
    ran = subprocess.run(
        [sys.executable, "-I", str(path)],
        capture_output=True,
        text=True,
        env={**os.environ, "TMPDIR": str(tmp_path)},
        check=False,
    )
    assert (ran.returncode, ran.stdout) == (0, "1\n"), ran.stderr


@pytest.mark.parametrize(
    "recipe",
    [
        "from __future__ import annotations\nlater: int = 1\n",
        '"""Later."""\nfrom __future__ import annotations\nlater: int = 1\n',
        "from __future__ import annotations; later = pl.DataFrame()\n",
    ],
)
def test_a_dataset_script_puts_the_recipes_future_import_first(tmp_path: Path, recipe: str) -> None:
    store = project_with_saved_items(tmp_path)
    save_another_dataset(store, "later", recipe)
    script = dataset_script(store.get("momentum"), store, "later")
    # After the header's comments, which may precede it, and before the setup's statements.
    assert script.index("\nfrom __future__ import annotations\n") < script.index(SETUP)
    compile(script, "later.py", "exec")


def test_pinned_dataset_script_mentions_the_parquet(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    saved = store.get("momentum").datasets[0].model_copy(update={"mode": "pinned"})
    store.staging_path("momentum", "prices").write_bytes(b"")
    store.write_dataset("momentum", saved, recipe=RECIPE, raw=RECIPE)
    script = dataset_script(store.get("momentum"), store, "prices")
    assert "data.parquet" in script and "pl.read_parquet(" in script


def test_dataset_script_keeps_free_text_in_its_comments(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    saved = (
        store.get("momentum")
        .datasets[0]
        .model_copy(
            update={
                "description": "two\rlines\x00",
                "validated": False,
                "validation_error": "rows differ\nraise SystemExit(3)",
            }
        )
    )
    store.write_dataset("momentum", saved, recipe=RECIPE, raw=RECIPE)
    script = dataset_script(store.get("momentum"), store, "prices")
    assert script.startswith("# prices: two lines\\u0000\n")
    assert "# Not validated: rows differ raise SystemExit(3)\n" in script
    exec(script, {})  # the test executes exported code on purpose


def test_a_recipe_runs_before_the_saved_dataset_it_rebinds(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    load = "import polars as pl\nprices = pl.DataFrame({'ts': ['a', 'b'], 'px': [1.0, 2.0]})\n"
    # Each raw recipe replays the load: returns' would reset prices to both rows.
    filtered = load + "prices = prices.filter(pl.col('px') > 1)\n"
    store.write_dataset(
        "momentum", store.get("momentum").datasets[0], recipe=filtered, raw=filtered
    )
    save_another_dataset(store, "returns", load + "returns = prices.select(pl.col('px') * 10)\n")
    doc = notebook(store.get("momentum"), store)
    headings = [source.split("\n")[0] for source in sources(doc, "markdown")]
    assert headings[1:4] == ["## returns", "## prices", "## View: table"]
    namespace = run_code_cells(doc)
    prices, returns, result = namespace["prices"], namespace["returns"], namespace["prices_1"]
    assert isinstance(prices, pl.DataFrame) and prices.height == 1
    assert isinstance(returns, pl.DataFrame) and returns["px"].to_list() == [10.0, 20.0]
    assert isinstance(result, pl.DataFrame) and result.height == 1


def test_a_recipe_whose_def_rebinds_a_saved_dataset_runs_first() -> None:
    recipes = ["prices = 1\n", "def prices():\n    return 2\n\nreturns = prices()\n"]
    assert _recipe_order(["prices", "returns"], recipes) == [(1, []), (0, [])]


@pytest.mark.parametrize("recipe", UNPARSABLE)
def test_a_recipe_too_deep_to_parse_constrains_no_other(recipe: str) -> None:
    assert _recipe_order(["prices", "returns"], [recipe, "returns = 1\n"]) == [(0, []), (1, [])]


def test_recipes_in_a_cycle_keep_saved_order_and_say_what_they_rebind(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    save_another_dataset(store, "left", "left = 1\nright = 2\n")
    save_another_dataset(store, "right", "right = 2\nleft = 1\n")
    save_another_dataset(store, "zeta", "left = (\n")  # does not parse, so constrains nothing
    doc = notebook(store.get("momentum"), store)
    code = sources(doc, "code")[1:5]
    # Saved order throughout: left's binding of right is replaced by right's own recipe.
    assert code[0] == "left = 1\nright = 2\n" and code[1] == RECIPE
    assert code[2].startswith("# This recipe also assigns left, which an earlier cell loaded")
    assert code[2].endswith("\nright = 2\nleft = 1\n") and code[3] == "left = (\n"


def test_the_view_source_fence_outlasts_its_backticks(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    source = "export default function V() { return '````' }"
    store.write_view(
        "momentum", store.get("momentum").views[0], source=source, state={}, queries=[]
    )
    fence = cells_of(notebook(store.get("momentum"), store))[-1].source
    assert fence == f"`````tsx\n{source}\n`````\n"


def test_a_cycle_keeps_saved_order_when_an_outside_recipe_assigns_a_member(
    tmp_path: Path,
) -> None:
    store = project_with_saved_items(tmp_path)
    save_another_dataset(store, "alpha", "alpha = 1\nbeta = 1\n")
    save_another_dataset(store, "beta", "beta = 1\nalpha = 1\n")
    save_another_dataset(store, "xray", "xray = 1\nalpha = 1\n")
    doc = notebook(store.get("momentum"), store)
    headings = [source.split("\n")[0] for source in sources(doc, "markdown")]
    # xray runs before alpha, which it assigns; alpha still runs before beta, as saved.
    assert headings[1:5] == ["## prices", "## xray", "## alpha", "## beta"]
    code = sources(doc, "code")[1:]
    assert code[3].startswith("# This recipe also assigns alpha, which an earlier cell loaded")
    assert not any(source.startswith("# This recipe") for source in code[:3])


def test_a_view_that_publishes_its_spec_exports_that_spec(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    store = project_with_saved_items(tmp_path)
    table = store.get("momentum").views[0]
    spec: dict[str, Json] = {
        "dataset": "prices",
        "group_by": ["ts"],
        "aggs": [{"col": "px", "fn": "sum"}],
    }
    # The pivot's queries are its arrow load and a one-row probe of the spec.
    store.write_view(
        "momentum",
        table,
        source=VIEW_SOURCE,
        state={"spec": spec, "dropped": ['filter px "!="']},
        queries=[{"dataset": "prices", "format": "arrow"}, {**spec, "limit": 1}],
    )
    doc = notebook(store.get("momentum"), store)
    code = sources(doc, "code")[2]
    assert code.startswith('# To code leaves out: filter px "!="\n')
    namespace = run_code_cells(doc)
    code = capsys.readouterr().out
    assert "prices_1 = (" in code and "prices_2" not in code and "limit" not in code
    assert isinstance(namespace["prices_1"], pl.DataFrame)


@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize("time_dtype", ["Date", "Datetime('ns', 'UTC')"])
def test_saved_whole_series_query_executes_in_notebook(
    tmp_path: Path, backing: str, time_dtype: str
) -> None:
    store = project_with_saved_items(tmp_path)
    recipe = (
        "prices = pl.DataFrame({'ts': pl.Series(range(60001), dtype=pl.Int64)"
        f".cast(pl.{time_dtype}), "
        "'px': pl.Series([n % 17 for n in range(59999)] + [-10000, 2**127 - 1], dtype=pl.Int128)})"
        + (".lazy()" if backing == "polars_lazy" else "")
        + "\n"
    )
    meta = store.get("momentum").datasets[0].model_copy(update={"backing": backing})
    store.write_dataset("momentum", meta, recipe=recipe, raw=recipe)
    query: dict[str, Json] = {
        "dataset": "prices",
        "line_reduce": {"time": "ts", "value": "px", "max_rows": 4},
    }
    store.write_view(
        "momentum",
        store.get("momentum").views[0],
        source=VIEW_SOURCE,
        state={},
        queries=[query],
    )
    doc = notebook(store.get("momentum"), store)
    assert "query 1 could not be rendered" not in sources(doc, "code")[-1]
    namespace = run_code_cells(doc)
    result = namespace["prices_1"]
    assert isinstance(result, pl.DataFrame)
    assert result.height <= 4
    assert result[0, "px"] == 0
    assert result[-1, "px"] == 2**127 - 1
    assert result["px"].min() == -10000
    frame = namespace["prices"]
    assert isinstance(frame, pl.DataFrame | pl.LazyFrame)
    assert result.schema == frame.lazy().collect_schema()


@pytest.mark.parametrize("via_route", [False, True])
def test_notebook_uses_configured_effective_line_budget(tmp_path: Path, via_route: bool) -> None:
    from polars.testing import assert_frame_equal

    from quarry.query import QuerySpec, to_polars

    store = project_with_saved_items(tmp_path)
    (tmp_path / "config.toml").write_text("[data]\nrow_cap = 100\n")
    recipe = (
        "prices = pl.DataFrame({'ts': pl.Series(range(60001), dtype=pl.Int64).cast(pl.Datetime), "
        "'px': [n % 17 for n in range(59999)] + [-10000, 20000]})\n"
    )
    meta = store.get("momentum").datasets[0]
    store.write_dataset("momentum", meta, recipe=recipe, raw=recipe)
    query: dict[str, Json] = {
        "dataset": "prices",
        "line_reduce": {"time": "ts", "value": "px", "max_rows": 50000},
    }
    store.write_view(
        "momentum", store.get("momentum").views[0], source=VIEW_SOURCE, state={}, queries=[query]
    )
    cap = 100
    if via_route:
        from quarry.config import DataConfig, QuarryConfig
        from tests.server.test_app import make_client

        cap = 64  # The active server cap wins over the 100-row config file.
        client = make_client(
            tmp_path, [], config=QuarryConfig(root=tmp_path, data=DataConfig(row_cap=cap))
        )
        document = client.get("/projects/momentum/export.ipynb").json()
    else:
        document = notebook(store.get("momentum"), store)
    namespace = run_code_cells(document)
    frame, result = namespace["prices"], namespace["prices_1"]
    assert isinstance(frame, pl.DataFrame) and isinstance(result, pl.DataFrame)
    assert result.height <= cap
    spec = QuerySpec.model_validate(
        {"dataset": "prices", "line_reduce": {"time": "ts", "value": "px", "max_rows": cap}}
    )
    assert_frame_equal(result, to_polars(spec, frame).collect(), check_exact=True)
