"""The namespace every kernel starts with."""

from __future__ import annotations

from pathlib import Path

import duckdb
import polars as pl

from quarry.config import QuarryConfig
from quarry.data.loaders import load_loaders
from quarry.data.mssql import make_sql
from quarry.data.parquet import ParquetCatalog


def build_namespace(config: QuarryConfig, temp_dir: Path) -> dict[str, object]:
    """The starting namespace; DuckDB spills under `temp_dir`, which the caller owns."""
    # One connection for everything: DuckDB cannot scan a relation made on another connection,
    # so `pq`, `sql_local`, `duckdb.sql` and `_conn` must agree on it for step code to mix them.
    conn = duckdb.default_connection()
    configure_connection(conn, temp_dir, config.data.kernel_memory_mb, config.data.kernel_threads)
    registry = load_loaders(config.root / "loaders.toml")
    catalog = ParquetCatalog(config.data.parquet_root, conn)
    return {
        "pl": pl,
        "duckdb": duckdb,
        "loaders": registry.bound(),
        "sql": make_sql(config.data.mssql_dsn),
        "pq": catalog.pq,
        "sql_local": catalog.sql_local,
        "_conn": conn,
        "_registry": registry,
    }


def configure_connection(
    conn: duckdb.DuckDBPyConnection, temp_dir: Path, memory_mb: int, threads: int
) -> None:
    """Set `conn` up as the kernel's connection, in a kernel capped at `memory_mb` and `threads`.

    Each cap of 0 leaves DuckDB's default.
    """
    # `sql_local` is called from step code, so its query's table names are the step's
    # variables, one frame up from the call DuckDB would otherwise look in.
    conn.execute("SET python_scan_all_frames = true")
    # A naive ISO string compared with a TIMESTAMPTZ reads in the session zone, the host's by
    # default; in UTC it means the same instant on every host.
    conn.execute("SET TimeZone = 'UTC'")
    # DuckDB's default is `.tmp` under the working directory, with umask permissions.
    conn.execute("SET temp_directory = ?", [str(temp_dir / "spill")])
    if memory_mb > 0:
        # DuckDB's default, 80% of RAM, ignores the cap: past the cap it fails instead of spilling.
        conn.execute("SET memory_limit = ?", [f"{memory_mb * 7 // 10}MiB"])
    if threads > 0:
        conn.execute("SET threads = ?", [threads])
