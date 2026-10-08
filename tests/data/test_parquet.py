from pathlib import Path

import duckdb
import polars as pl
import pytest

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


def test_pq_reads_with_hive_partitioning(tmp_path: Path) -> None:
    build_cache(tmp_path)
    catalog = ParquetCatalog(tmp_path, duckdb.connect())
    rel = catalog.pq("prices/**/*.parquet")
    df = rel.filter("year = 2024").pl()
    assert set(df.columns) >= {"ticker", "px", "year", "month"}
    assert df.height == 2


def test_register_and_sql_local() -> None:
    catalog = ParquetCatalog(None, duckdb.connect())
    catalog.register("frame", pl.DataFrame({"a": [1, 2]}))
    assert catalog.sql_local("SELECT sum(a) AS s FROM frame").pl()["s"].to_list() == [3]


def test_pq_without_root_raises() -> None:
    catalog = ParquetCatalog(None, duckdb.connect())
    with pytest.raises(RuntimeError, match="parquet_root"):
        catalog.pq("x/*.parquet")
