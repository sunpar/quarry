import copy
import json
from collections.abc import Mapping
from pathlib import Path
from typing import NamedTuple

import nbformat
import polars as pl

from quarry.kernel.datasets import Column
from quarry.projects.export import dataset_script, notebook, notebook_json
from quarry.projects.models import SavedDatasetMeta, SavedViewMeta
from quarry.projects.store import ProjectStore
from quarry.query import Json

RECIPE = "import polars as pl\nprices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})\n"
VIEW_SOURCE = "export default function V() { return null }"


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


def test_notebook_validates_and_runs(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    doc = notebook(store.get("momentum"), store)
    # A copy: validate repairs what it can in place, such as a repeated cell id.
    nbformat.validate(copy.deepcopy(doc))
    cells = [(c.kind, c.source) for c in cells_of(doc)]
    expected = [
        ("markdown", "# Momentum\n\na study"),
        ("markdown", "## prices\n\nclosing prices"),
        ("code", "import polars as pl"),
        ("markdown", "## View: table\n\nthe table"),
        ("code", "# Rendered from"),
        ("markdown", "```tsx\nexport default"),
    ]
    assert len(cells) == len(expected)
    for (kind, source), (want_kind, prefix) in zip(cells, expected, strict=True):
        assert kind == want_kind and source.startswith(prefix), (kind, source[:40])
    code = cells_of(doc)[4].source
    assert code.startswith("# Rendered from the saved view's queries without a schema")
    assert "prices_1 = (" in code and "# query 2 could not be rendered:" in code
    namespace = run_code_cells(doc)
    assert isinstance(namespace["prices_1"], pl.DataFrame)
    ids = [c.id for c in cells_of(doc)]
    assert len(set(ids)) == len(ids)
    assert notebook(store.get("momentum"), store) == doc  # an export is reproducible
    assert json.loads(notebook_json(store.get("momentum"), store))["nbformat"] == 4


def test_a_result_name_never_overwrites_a_saved_dataset(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    save_another_dataset(
        store, "prices_1", "import polars as pl\nprices_1 = pl.DataFrame({'a': [9]})\n"
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
    code = sources(doc, "code")
    # chart sorts before table: its query skips the saved prices_1, and table's skips chart's too.
    assert "prices_2 = (" in code[2] and "prices_3 = (" in code[3]
    namespace = run_code_cells(doc)
    saved = namespace["prices_1"]
    assert isinstance(saved, pl.DataFrame) and saved["a"].to_list() == [9]
    assert isinstance(namespace["prices_3"], pl.DataFrame)


def test_a_query_whose_import_would_rebind_a_saved_dataset_is_not_rendered(
    tmp_path: Path,
) -> None:
    store = project_with_saved_items(tmp_path)
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
    code = cells_of(doc)[-2].source
    assert "# query 1 could not be rendered: dataset 'date' would be shadowed" in code
    # The failed query keeps its position number.
    assert "from datetime import" not in code and "prices_2 = (" in code
    namespace = run_code_cells(doc)
    saved = namespace["date"]
    assert isinstance(saved, pl.DataFrame) and saved["a"].to_list() == [1]


def test_an_unrendered_query_stays_a_comment_whatever_its_error_says(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    hostile: dict[str, Json] = {"dataset": "prices", "x\rimport sys; sys.exit(3)\n\x00\u202e": 1}
    store.write_view(
        "momentum", store.get("momentum").views[0], source=VIEW_SOURCE, state={}, queries=[hostile]
    )
    doc = notebook(store.get("momentum"), store)
    code = cells_of(doc)[-2].source
    assert "# query 1 could not be rendered:" in code
    assert "\\u0000\\u202e" in code and "\x00" not in code
    # The key's line breaks would have run the rest of it as code, and a NUL stops it compiling.
    run_code_cells(doc)


def test_dataset_script_has_a_header_and_the_recipe(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    script = dataset_script(store.get("momentum"), store, "prices")
    assert script.startswith("# prices: closing prices\n# Saved from Quarry project Momentum")
    assert script.endswith(RECIPE)
    namespace: dict[str, object] = {}
    exec(script, namespace)  # the test executes exported code on purpose
    assert isinstance(namespace["prices"], pl.DataFrame)


def test_pinned_dataset_script_mentions_the_parquet(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    saved = store.get("momentum").datasets[0].model_copy(update={"mode": "pinned"})
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


def test_recipes_in_a_cycle_keep_saved_order_and_say_what_they_rebind(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    save_another_dataset(store, "left", "left = 1\nright = 2\n")
    save_another_dataset(store, "right", "right = 2\nleft = 1\n")
    save_another_dataset(store, "zeta", "left = (\n")  # does not parse, so constrains nothing
    doc = notebook(store.get("momentum"), store)
    code = sources(doc, "code")[:4]
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
    code = sources(doc, "code")
    assert code[3].startswith("# This recipe also assigns alpha, which an earlier cell loaded")
    assert not any(source.startswith("# This recipe") for source in code[:3])
