import json
import logging
from pathlib import Path

import pytest

from quarry.components import library
from quarry.components.library import (
    COMPONENT_ID_RE,
    ComponentLibrary,
    ComponentManifest,
    dtype_class,
    requirements_for,
    satisfies,
)
from quarry.kernel.datasets import Column, DatasetMeta
from tests.fixtures import chmodded, root_ignores_modes


def write_component(
    root: Path, cid: str, tags: list[str], requires: list[dict[str, object]]
) -> None:
    d = root / cid
    d.mkdir(parents=True, exist_ok=True)
    (d / "component.tsx").write_text("export default function V() { return null }")
    (d / "manifest.json").write_text(
        json.dumps(
            {
                "id": cid,
                "name": cid,
                "description": "",
                "tags": tags,
                "schema": {"requires": requires},
                "origin": "builtin",
                "created_at": "2026-10-08T00:00:00Z",
            }
        )
    )


def write_broken_components(root: Path) -> None:
    """A manifest that fails validation and one that is not JSON, each with a source file."""
    for cid, manifest in (("badschema", '{"id": "badschema"}'), ("badjson", "{not json")):
        d = root / cid
        d.mkdir(parents=True)
        (d / "component.tsx").write_text("export default function V() { return null }")
        (d / "manifest.json").write_text(manifest)


def meta(cols: list[tuple[str, str]]) -> DatasetMeta:
    return DatasetMeta(
        name="d",
        backing="polars",
        schema=[Column(name=n, dtype=t) for n, t in cols],
        rows=1,
        preview=[],
    )


def test_dtype_class() -> None:
    assert dtype_class("Date") == "datetime"
    assert dtype_class("Datetime(time_unit='us', time_zone=None)") == "datetime"
    assert dtype_class("Int64") == "numeric"
    assert dtype_class("Float32") == "numeric"
    assert dtype_class("String") == "string"
    assert dtype_class("Boolean") == "other"


@pytest.mark.parametrize(
    ("requires", "fits"),
    [
        ([("numeric", 1), ("numeric", 1)], False),  # two roles, one numeric column
        ([("datetime", 1), ("any", 3)], False),  # the date column is taken
        ([("datetime", 1), ("any", 1)], True),
        ([("numeric", 1), ("string", 1), ("any", 1)], True),
    ],
)
def test_each_role_needs_its_own_columns(requires: list[tuple[str, int]], fits: bool) -> None:
    manifest = ComponentManifest.model_validate(
        {
            "id": "c",
            "name": "c",
            "description": "",
            "schema": {
                "requires": [
                    {"role": f"r{i}", "dtype": d, "min": n} for i, (d, n) in enumerate(requires)
                ]
            },
            "origin": "builtin",
            "created_at": "",
        }
    )
    dataset = meta([("date", "Date"), ("px", "Float64"), ("ticker", "String")])
    assert satisfies(manifest, dataset) is fits


def test_entries_and_first_root_wins(tmp_path: Path) -> None:
    a, b = tmp_path / "a", tmp_path / "b"
    write_component(a, "table", ["table"], [])
    write_component(b, "table", ["dup"], [])
    write_component(b, "line", ["chart"], [])
    lib = ComponentLibrary([a, b])
    ids = sorted(e.manifest.id for e in lib.entries())
    assert ids == ["line", "table"]
    table = lib.get("table")
    assert table is not None and table.manifest.tags == ["table"]
    assert lib.get("nope") is None


def test_search_filters_by_schema_and_ranks_by_tags(tmp_path: Path) -> None:
    write_component(
        tmp_path,
        "ts",
        ["chart", "time"],
        [{"role": "x", "dtype": "datetime"}, {"role": "y", "dtype": "numeric"}],
    )
    write_component(tmp_path, "table", ["table"], [])
    write_component(tmp_path, "scatter", ["chart"], [{"role": "x", "dtype": "numeric", "min": 2}])
    lib = ComponentLibrary([tmp_path])
    with_dates = meta([("date", "Date"), ("ret", "Float64")])
    assert [m.id for m in lib.search(dataset=with_dates, tags=["chart"])] == ["ts", "table"]
    numeric_only = meta([("a", "Int64"), ("b", "Int64")])
    assert [m.id for m in lib.search(dataset=numeric_only, tags=[])] == ["scatter", "table"]
    assert lib.search(dataset=None, tags=["table"])[0].id == "table"


def test_broken_manifests_are_skipped_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    write_component(tmp_path, "table", ["table"], [])
    write_broken_components(tmp_path)
    lib = ComponentLibrary([tmp_path])
    with caplog.at_level(logging.WARNING, logger="quarry.components.library"):
        assert [e.manifest.id for e in lib.entries()] == ["table"]
    assert "badschema" in caplog.text and "badjson" in caplog.text
    table = lib.get("table")
    assert table is not None
    assert lib.get("badschema") is None
    assert [m.id for m in lib.search(dataset=meta([("a", "Int64")]), tags=[])] == ["table"]


@root_ignores_modes
def test_unreadable_manifest_is_skipped(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    write_component(tmp_path, "good", ["a"], [])
    write_component(tmp_path, "locked", ["a"], [])
    with chmodded(tmp_path / "locked" / "manifest.json", 0o000), caplog.at_level(logging.WARNING):
        entries = ComponentLibrary([tmp_path]).entries()
    assert [e.manifest.id for e in entries] == ["good"]
    assert "locked" in caplog.text


@pytest.mark.parametrize(
    "override",
    [
        {"contract_version": 2},
        {"contract_verison": 2},
        {"schema": {"require": []}},
        {"schema": {"requires": [{"role": "y", "dtype": "numeric", "min": 0}]}},
    ],
)
def test_manifest_quarry_cannot_mount_is_skipped(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, override: dict[str, object]
) -> None:
    write_component(tmp_path, "good", ["a"], [])
    write_component(tmp_path, "future", ["a"], [])
    manifest = tmp_path / "future" / "manifest.json"
    manifest.write_text(json.dumps({**json.loads(manifest.read_text()), **override}))
    with caplog.at_level(logging.WARNING):
        entries = ComponentLibrary([tmp_path]).entries()
    assert [e.manifest.id for e in entries] == ["good"]
    assert "future" in caplog.text


def test_requirements_for_lists_each_dtype_class_present() -> None:
    reqs = requirements_for(
        meta([("date", "Date"), ("ret", "Float64"), ("vol", "Int64"), ("f", "Boolean")])
    )
    assert [(r.role, r.dtype, r.min) for r in reqs] == [
        ("datetime", "datetime", 1),
        ("numeric", "numeric", 2),
    ]
    assert requirements_for(meta([])) == []


def test_write_component_then_library_finds_it(tmp_path: Path) -> None:
    manifest = ComponentManifest(
        id="my-scatter",
        name="My scatter",
        description="",
        tags=["scatter"],
        origin="generated",
        created_at="2026-10-09T00:00:00Z",
    )
    path = library.write_component(
        tmp_path, manifest, "export default function V() { return null }"
    )
    assert path == tmp_path / "my-scatter"
    entry = ComponentLibrary([tmp_path]).get("my-scatter")
    assert entry is not None and entry.manifest.origin == "generated"
    assert entry.source_path.read_text().startswith("export default")


def test_component_id_pattern() -> None:
    assert COMPONENT_ID_RE.match("ok-id-9")
    assert COMPONENT_ID_RE.match("Bad") is None and COMPONENT_ID_RE.match("a/b") is None
    assert COMPONENT_ID_RE.match("ok\n") is None
