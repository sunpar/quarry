"""DuckDB over the Hive-partitioned parquet cache, plus local frame registration."""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl
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
            raise RuntimeError("parquet_root is not configured")
        pattern = str(self._root / relative_glob).replace("'", "''")
        return self._conn.sql(f"SELECT * FROM read_parquet('{pattern}', hive_partitioning = true)")

    def sql_local(self, query: str) -> duckdb.DuckDBPyRelation:
        return self._conn.sql(query)

    def register(self, name: str, frame: pl.DataFrame) -> None:
        self._conn.register(name, frame)


def scan_layout(root: Path) -> list[PartitionLayout]:
    if not root.is_dir():
        return []
    layouts: list[PartitionLayout] = []
    for dataset_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        keys: list[str] = []
        current = dataset_dir
        for _ in range(2):
            children = sorted(p for p in current.iterdir() if p.is_dir() and "=" in p.name)
            if not children:
                break
            keys.append(children[0].name.split("=", 1)[0])
            current = children[0]
        if keys:
            layouts.append(PartitionLayout(dataset=dataset_dir.name, keys=keys))
    return layouts
