import os
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
import polars as pl
import pytest

from quarry.data import parquet
from quarry.data.parquet import ParquetCatalog, scan_layout


def build_cache(root: Path) -> None:
    for year in (2023, 2024):
        for month in (1, 2):
            path = root / "prices" / f"year={year}" / f"month={month}"
            path.mkdir(parents=True)
            frame = pl.DataFrame({"ticker": ["A"], "px": [float(year + month)]})
            frame.write_parquet(path / "part.parquet")
    (root / "notes.txt").write_text("ignored")


def test_scan_layout_reports_partition_keys(tmp_path: Path) -> None:
    build_cache(tmp_path)
    layout = scan_layout(tmp_path)
    assert [(entry.dataset, entry.keys) for entry in layout] == [("prices", ["year", "month"])]


def test_scan_layout_of_missing_root_is_empty(tmp_path: Path) -> None:
    assert scan_layout(tmp_path / "missing") == []


def write_frame(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pl.DataFrame({"ticker": ["A"]}).write_parquet(path)


@contextmanager
def mode(path: Path, bits: int) -> Iterator[None]:
    path.chmod(bits)
    try:
        yield
    finally:
        path.chmod(0o755)


root_ignores_modes = pytest.mark.skipif(os.geteuid() == 0, reason="root reads any directory")


def test_scan_layout_lists_an_unpartitioned_dataset_with_no_keys(tmp_path: Path) -> None:
    build_cache(tmp_path)
    write_frame(tmp_path / "flat" / "part.parquet")
    (tmp_path / "empty").mkdir()
    (tmp_path / "other" / "docs").mkdir(parents=True)
    (tmp_path / "other" / "readme.txt").write_text("not parquet")
    layout = scan_layout(tmp_path)
    assert [(entry.dataset, entry.keys) for entry in layout] == [
        ("flat", []),
        ("prices", ["year", "month"]),
    ]


@root_ignores_modes
def test_scan_layout_skips_an_unreadable_dataset(tmp_path: Path) -> None:
    build_cache(tmp_path)
    write_frame(tmp_path / "locked" / "part.parquet")
    with mode(tmp_path / "locked", 0o000):
        layout = scan_layout(tmp_path)
    assert [entry.dataset for entry in layout] == ["prices"]


@root_ignores_modes
def test_scan_layout_skips_a_dataset_whose_entries_cannot_be_inspected(tmp_path: Path) -> None:
    # r-- on a directory lists its names but forbids stat on them, which is where is_dir() raises.
    build_cache(tmp_path)
    write_frame(tmp_path / "listed" / "part.parquet")
    with mode(tmp_path / "listed", 0o444):
        layout = scan_layout(tmp_path)
    assert [entry.dataset for entry in layout] == ["prices"]


@root_ignores_modes
def test_scan_layout_takes_the_next_key_from_the_sibling_of_an_unreadable_partition(
    tmp_path: Path,
) -> None:
    build_cache(tmp_path)
    with mode(tmp_path / "prices" / "year=2023", 0o000):
        layout = scan_layout(tmp_path)
    assert [(entry.dataset, entry.keys) for entry in layout] == [("prices", ["year", "month"])]


@root_ignores_modes
def test_scan_layout_keeps_the_first_key_when_no_partition_can_be_read(tmp_path: Path) -> None:
    build_cache(tmp_path)
    with mode(tmp_path / "prices" / "year=2023", 0o000), mode(tmp_path / "prices" / "year=2024", 0):
        layout = scan_layout(tmp_path)
    assert [(entry.dataset, entry.keys) for entry in layout] == [("prices", ["year"])]


def test_scan_layout_does_not_read_the_leaf_partitions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    build_cache(tmp_path)
    read: list[str] = []
    list_dir = parquet._read_dir

    def spy(path: Path) -> tuple[list[Path], list[Path]] | None:
        read.append(path.name)
        return list_dir(path)

    monkeypatch.setattr(parquet, "_read_dir", spy)
    assert [entry.keys for entry in scan_layout(tmp_path)] == [["year", "month"]]
    assert not [name for name in read if name.startswith("month=")]


@root_ignores_modes
def test_scan_layout_of_unreadable_root_is_empty(tmp_path: Path) -> None:
    build_cache(tmp_path)
    with mode(tmp_path, 0o000):
        assert scan_layout(tmp_path) == []


def test_scan_layout_of_a_file_root_is_empty(tmp_path: Path) -> None:
    (tmp_path / "cache").write_text("not a directory")
    assert scan_layout(tmp_path / "cache") == []


def test_pq_reads_an_unpartitioned_dataset_with_the_layout_glob(tmp_path: Path) -> None:
    write_frame(tmp_path / "flat" / "part.parquet")
    catalog = ParquetCatalog(tmp_path, duckdb.connect())
    assert catalog.pq("flat/**/*.parquet").pl().height == 1


def test_pq_reads_with_hive_partitioning(tmp_path: Path) -> None:
    build_cache(tmp_path)
    catalog = ParquetCatalog(tmp_path, duckdb.connect())
    rel = catalog.pq("prices/**/*.parquet")
    df = rel.filter("year = 2024").pl()
    assert set(df.columns) >= {"ticker", "px", "year", "month"}
    assert df.height == 2


def test_pq_without_root_raises() -> None:
    catalog = ParquetCatalog(None, duckdb.connect())
    with pytest.raises(RuntimeError, match="parquet_root"):
        catalog.pq("x/*.parquet")
