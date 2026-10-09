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
    top = _read_dir(root)
    if top is None:
        return []
    layouts: list[PartitionLayout] = []
    for dataset_dir in top[0]:
        listing = _read_dir(dataset_dir)
        if listing is None:
            continue
        subdirs, parquet_files = listing
        keys = _partition_keys(subdirs)
        if keys or parquet_files:
            layouts.append(PartitionLayout(dataset=dataset_dir.name, keys=keys))
    return layouts


def _partition_keys(subdirs: list[Path]) -> list[str]:
    """The key of the first `key=value` directory in `subdirs` and of the first one inside it.
    The second key comes from the first partition that can be read, and the directories that
    hold it are named but not read: a leaf can hold thousands of files."""
    partitions = _key_value_dirs(subdirs)
    if not partitions:
        return []
    keys = [_key(partitions[0])]
    for partition in partitions:
        listing = _read_dir(partition)
        if listing is not None:
            inner = _key_value_dirs(listing[0])
            if inner:
                keys.append(_key(inner[0]))
            break
    return keys


def _key_value_dirs(dirs: list[Path]) -> list[Path]:
    return [p for p in dirs if "=" in p.name]


def _key(partition: Path) -> str:
    return partition.name.split("=", 1)[0]


def _read_dir(path: Path) -> tuple[list[Path], list[Path]] | None:
    """The subdirectories and the parquet files directly in `path`, sorted; None when `path`
    or anything in it cannot be read."""
    dirs: list[Path] = []
    files: list[Path] = []
    try:
        for entry in sorted(path.iterdir()):
            if entry.is_dir():
                dirs.append(entry)
            elif entry.suffix == ".parquet":
                files.append(entry)
    except OSError:
        return None
    return dirs, files
