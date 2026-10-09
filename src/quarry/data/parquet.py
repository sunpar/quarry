"""DuckDB over the Hive-partitioned parquet cache, and DuckDB SQL over local datasets."""

from __future__ import annotations

from pathlib import Path

import duckdb
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
            raise RuntimeError("parquet cache not configured: set data.parquet_root")
        pattern = str(self._root / relative_glob).replace("'", "''")
        return self._conn.sql(f"SELECT * FROM read_parquet('{pattern}', hive_partitioning = true)")

    def sql_local(self, query: str) -> duckdb.DuckDBPyRelation:
        return self._conn.sql(query)


def scan_layout(root: Path) -> list[PartitionLayout]:
    """The datasets under `root` with their partition keys, none for a dataset that has none.
    Never raises: a directory that cannot be read is left out, so an unreadable `root` gives []."""
    layouts: list[PartitionLayout] = []
    for dataset_dir in _read_dir(root)[0]:
        subdirs, parquet_files = _read_dir(dataset_dir)
        keys: list[str] = []
        for _ in range(2):
            partitions = [p for p in subdirs if "=" in p.name]
            if not partitions:
                break
            keys.append(partitions[0].name.split("=", 1)[0])
            subdirs = _read_dir(partitions[0])[0]
        if keys or parquet_files:
            layouts.append(PartitionLayout(dataset=dataset_dir.name, keys=keys))
    return layouts


def _read_dir(path: Path) -> tuple[list[Path], list[Path]]:
    """The subdirectories and the parquet files directly in `path`, sorted; both empty when
    `path` or anything in it cannot be read."""
    dirs: list[Path] = []
    files: list[Path] = []
    try:
        for entry in sorted(path.iterdir()):
            if entry.is_dir():
                dirs.append(entry)
            elif entry.suffix == ".parquet":
                files.append(entry)
    except OSError:
        return [], []
    return dirs, files
