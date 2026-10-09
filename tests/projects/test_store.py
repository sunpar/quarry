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
    store.write_dataset(
        "p", dataset_meta(), recipe="prices = load()\n", raw="x = 1\nprices = load()\n"
    )
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
    store.write_view(
        "p",
        view_meta(),
        source="export default () => null",
        state={"k": 1},
        queries=[{"dataset": "prices", "limit": 5}],
    )
    saved = store.read_view("p", "closes")
    assert saved.meta.component_id == "time-series"
    assert saved.source == "export default () => null"
    assert saved.state == {"k": 1}
    assert saved.queries == [{"dataset": "prices", "limit": 5}]
    assert (tmp_path / "projects" / "p" / "views" / "closes" / "queries.json").exists()
    with pytest.raises(KeyError):
        store.read_view("p", "nope")
    with pytest.raises(ValueError):
        store.write_view("p", view_meta("Bad Name!"), source="", state={}, queries=[])


def test_set_canvas(tmp_path: Path) -> None:
    store = ProjectStore(tmp_path)
    store.create("p")
    cards = [CanvasCard(view="closes", x=0, y=0, w=6, h=8)]
    assert store.set_canvas("p", cards).canvas == cards
    assert store.meta("p").canvas == cards
