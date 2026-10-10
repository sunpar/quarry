import json
from collections.abc import Mapping
from pathlib import Path

import nbformat
import polars as pl

from quarry.kernel.datasets import Column
from quarry.projects.export import dataset_script, notebook, notebook_json
from quarry.projects.models import SavedDatasetMeta, SavedViewMeta
from quarry.projects.store import ProjectStore

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


def run_code_cells(doc: Mapping[str, object]) -> dict[str, object]:
    namespace: dict[str, object] = {}
    cells = doc["cells"]
    assert isinstance(cells, list)
    for cell in cells:
        if cell["cell_type"] == "code":
            exec(cell["source"], namespace)  # the test executes exported code on purpose
    return namespace


def test_notebook_validates_and_runs(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    doc = notebook(store.get("momentum"), store)
    nbformat.validate(nbformat.from_dict(doc))
    cells = [(c["cell_type"], c["source"]) for c in doc["cells"]]
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
    code = doc["cells"][4]["source"]
    assert code.startswith("# Rendered from the saved view's queries without a schema")
    assert "prices_1 = (" in code and "# query 2 could not be rendered:" in code
    namespace = run_code_cells(doc)
    assert isinstance(namespace["prices_1"], pl.DataFrame)
    assert len({c["id"] for c in doc["cells"]}) == len(doc["cells"])
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
    code = [c["source"] for c in doc["cells"] if c["cell_type"] == "code"]
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
    since = {"dataset": "prices", "filters": [{"col": "ts", "op": "ge", "value": "2024-01-01"}]}
    store.write_view(
        "momentum",
        store.get("momentum").views[0],
        source=VIEW_SOURCE,
        state={},
        queries=[since, {"dataset": "prices", "limit": 1}],
    )
    doc = notebook(store.get("momentum"), store)
    code = doc["cells"][-2]["source"]
    assert "# query 1 could not be rendered: dataset 'date' would be shadowed" in code
    # The failed query keeps its position number.
    assert "from datetime import" not in code and "prices_2 = (" in code
    namespace = run_code_cells(doc)
    saved = namespace["date"]
    assert isinstance(saved, pl.DataFrame) and saved["a"].to_list() == [1]


def test_an_unrendered_query_stays_a_comment_whatever_its_error_says(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    hostile = {"dataset": "prices", "x\rimport sys; sys.exit(3)\n": 1}
    store.write_view(
        "momentum", store.get("momentum").views[0], source=VIEW_SOURCE, state={}, queries=[hostile]
    )
    doc = notebook(store.get("momentum"), store)
    code = doc["cells"][-2]["source"]
    assert "# query 1 could not be rendered:" in code
    run_code_cells(doc)  # the key's line breaks would have run the rest of it as code


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
                "description": "two\rlines",
                "validated": False,
                "validation_error": "rows differ\nraise SystemExit(3)",
            }
        )
    )
    store.write_dataset("momentum", saved, recipe=RECIPE, raw=RECIPE)
    script = dataset_script(store.get("momentum"), store, "prices")
    assert script.startswith("# prices: two lines\n")
    assert "# Not validated: rows differ raise SystemExit(3)\n" in script
    exec(script, {})  # the test executes exported code on purpose
