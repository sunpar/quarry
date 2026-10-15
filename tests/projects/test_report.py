import tracemalloc
from html.parser import HTMLParser
from pathlib import Path

import polars as pl
import pytest

from quarry.projects.report import ReportError, report_html
from tests.projects.test_export import project_with_saved_items, save_another_dataset


class ReportMarkup(HTMLParser):
    def __init__(self, text: str) -> None:
        super().__init__()
        self.tags: list[str] = []
        self.attributes: list[tuple[str, str | None]] = []
        self.text: list[str] = []
        self.feed(text)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.tags.append(tag)
        self.attributes.extend(attrs)

    def handle_data(self, data: str) -> None:
        self.text.append(data)


def test_report_reads_only_saved_artifacts_and_bounds_pinned_preview(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    marker = tmp_path / "executed"
    recipe = f"from pathlib import Path\nPath({str(marker)!r}).touch()\n"
    live = store.get("momentum").datasets[0]
    store.write_dataset("momentum", live, recipe=recipe, raw=recipe)
    # An abandoned live file is not a persisted result and must never be read.
    store.parquet_path("momentum", "prices").write_text("not parquet")
    pinned = live.model_copy(update={"name": "frozen", "mode": "pinned", "rows": 25})
    pl.DataFrame({"label": [f"row-{n:02}" for n in range(25)]}).write_parquet(
        store.staging_path("momentum", "frozen")
    )
    store.write_dataset("momentum", pinned, recipe=recipe, raw=recipe)

    text = report_html(store.get("momentum"), store)

    assert not marker.exists()
    assert "row-00" in text and "row-19" in text and "row-20" not in text
    assert "Live results unavailable" in text
    assert "View results unavailable" in text
    assert "20 rows" in text and "preview" in text.lower()
    assert "Upstream freshness unavailable" in text
    assert "2026-10-09T00:00:00Z" in text
    assert "source_session" in text and "source_step" in text
    assert "Saved state" in text and "Saved query specs" in text
    assert report_html(store.get("momentum"), store) == text


def test_report_escapes_every_saved_content_surface(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    attack = '<script src="https://invalid.example/x.js">alert(1)</script>'
    project = store.get("momentum")
    project.meta.name = attack
    project.meta.description = attack
    dataset = project.datasets[0].model_copy(update={"description": attack, "mode": "pinned"})
    pl.DataFrame({attack: [attack]}).write_parquet(store.staging_path("momentum", "prices"))
    store.write_dataset("momentum", dataset, recipe=attack, raw=attack)
    view = project.views[0].model_copy(update={"description": attack, "component_id": attack})
    store.write_view(
        "momentum", view, source=attack, state={"payload": attack}, queries=[{"payload": attack}]
    )
    project.datasets = [dataset]
    project.views = [view]

    markup = ReportMarkup(report_html(project, store))

    assert "script" not in markup.tags and "img" not in markup.tags
    assert not any(name in {"src", "href", "onclick"} for name, _ in markup.attributes)
    assert sum(attack in part for part in markup.text) >= 8


@pytest.mark.parametrize("artifact", ["recipe.py", "view.tsx", "state.json", "queries.json"])
def test_report_rejects_missing_saved_artifacts(tmp_path: Path, artifact: str) -> None:
    store = project_with_saved_items(tmp_path)
    folder = "datasets/prices" if artifact == "recipe.py" else "views/table"
    (tmp_path / "projects/momentum" / folder / artifact).unlink()
    with pytest.raises(ReportError, match="saved artifact"):
        report_html(store.get("momentum"), store)


@pytest.mark.parametrize("contents", [None, b"not parquet"])
def test_report_rejects_missing_or_corrupt_pinned_rows(
    tmp_path: Path, contents: bytes | None
) -> None:
    store = project_with_saved_items(tmp_path)
    pinned = store.get("momentum").datasets[0].model_copy(update={"mode": "pinned"})
    store.staging_path("momentum", "prices").write_bytes(b"not parquet")
    store.write_dataset("momentum", pinned, recipe="prices = 1", raw="prices = 1")
    path = store.parquet_path("momentum", "prices")
    if contents is None:
        path.unlink()
    with pytest.raises(ReportError, match=r"pinned rows.*prices"):
        report_html(store.get("momentum"), store)


def test_report_rejects_corrupt_view_state(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    (tmp_path / "projects/momentum/views/table/state.json").write_text("[]")
    with pytest.raises(ReportError, match="saved artifact"):
        report_html(store.get("momentum"), store)


@pytest.mark.parametrize("description", ["&" * 1_100_000, "数" * 1_800_000])
def test_report_limit_counts_escaped_utf8_bytes(tmp_path: Path, description: str) -> None:
    store = project_with_saved_items(tmp_path)
    project = store.get("momentum")
    project.meta.description = description
    with pytest.raises(ReportError, match="5 MiB"):
        report_html(project, store)


def test_report_limit_covers_the_whole_document(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    dataset = store.get("momentum").datasets[0]
    recipe = "#" * 3_000_000
    store.write_dataset("momentum", dataset, recipe=recipe, raw=recipe)
    store.write_dataset(
        "momentum", dataset.model_copy(update={"name": "other"}), recipe=recipe, raw=recipe
    )
    with pytest.raises(ReportError, match="5 MiB"):
        report_html(store.get("momentum"), store)


def test_report_escapes_large_fields_with_bounded_intermediate_memory(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    project = store.get("momentum")
    project.meta.description = "&" * 2_000_000
    tracemalloc.start()
    try:
        with pytest.raises(ReportError, match="5 MiB"):
            report_html(project, store)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 10 * 1024 * 1024


def test_report_bounds_json_fields_before_the_encoder_expands_them(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = project_with_saved_items(tmp_path)
    project = store.get("momentum")
    saved = store.read_view("momentum", "table")
    saved.state = {"large": {"items": ["\0" * 2_000_000]}}
    # Isolate rendering from loading the already-created saved record.
    monkeypatch.setattr(store, "read_view", lambda slug, name: saved)
    tracemalloc.start()
    try:
        with pytest.raises(ReportError, match="5 MiB"):
            report_html(project, store)
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 10 * 1024 * 1024


@pytest.mark.parametrize("missing", ["directory", "metadata"])
def test_report_rejects_missing_view_dependencies_with_a_valid_sibling(
    tmp_path: Path, missing: str
) -> None:
    store = project_with_saved_items(tmp_path)
    save_another_dataset(store, "valid", "valid = 1\n")
    directory = tmp_path / "projects/momentum/datasets/prices"
    if missing == "directory":
        directory.rename(tmp_path / "moved-prices")
    else:
        (directory / "meta.json").unlink()
    project = store.get("momentum")
    assert [dataset.name for dataset in project.datasets] == ["valid"]
    with pytest.raises(ReportError, match=r"saved artifact.*prices.*table"):
        report_html(project, store)
    assert store.read_recipe("momentum", "valid") == "valid = 1\n"
