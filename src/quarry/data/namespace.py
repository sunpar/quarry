"""The namespace every kernel starts with."""

from __future__ import annotations

import duckdb
import polars as pl

from quarry.config import QuarryConfig
from quarry.data.loaders import load_loaders
from quarry.data.mssql import make_sql
from quarry.data.parquet import ParquetCatalog


def build_namespace(config: QuarryConfig) -> dict[str, object]:
    # One connection for everything: DuckDB cannot scan a relation made on another connection,
    # so `pq`, `sql_local`, `duckdb.sql` and `_conn` must agree on it for step code to mix them.
    conn = duckdb.default_connection()
    # `sql_local` is called from step code, so its query's table names are the step's
    # variables, one frame up from the call DuckDB would otherwise look in.
    conn.execute("SET python_scan_all_frames = true")
    registry = load_loaders(config.root / "loaders.toml")
    catalog = ParquetCatalog(config.data.parquet_root, conn)
    return {
        "pl": pl,
        "duckdb": duckdb,
        "loaders": registry.bound(),
        "sql": make_sql(config.data.mssql_dsn),
        "pq": catalog.pq,
        "sql_local": catalog.sql_local,
        "catalog": catalog,
        "_conn": conn,
        "_registry": registry,
    }
