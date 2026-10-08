import json
from pathlib import Path

from quarry.components.library import ComponentLibrary, dtype_class
from quarry.kernel.datasets import Column, DatasetMeta


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
