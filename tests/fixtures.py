"""Helpers for tests that change process-wide state: file modes, the umask and DuckDB's
default connection."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
import pytest

# The settings an uncapped build_namespace changes on DuckDB's default connection.
NAMESPACE_SETTINGS = ("python_scan_all_frames", "TimeZone", "temp_directory")

root_ignores_modes = pytest.mark.skipif(os.geteuid() == 0, reason="root reads any file")


@contextmanager
def chmodded(path: Path, bits: int) -> Iterator[None]:
    """`path` with mode `bits` inside the block, and its old mode back after."""
    previous = stat.S_IMODE(path.stat().st_mode)
    path.chmod(bits)
    try:
        yield
    finally:
        path.chmod(previous)


@contextmanager
def umask(mask: int) -> Iterator[None]:
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


def setting(conn: duckdb.DuckDBPyConnection, name: str) -> object:
    row = conn.sql(f"SELECT current_setting('{name}')").fetchone()
    assert row is not None
    return row[0]


@contextmanager
def kept_default_connection() -> Iterator[None]:
    """build_namespace configures the default connection, which the whole session shares;
    its settings are back as they were after the block."""
    conn = duckdb.default_connection()
    saved = {name: setting(conn, name) for name in NAMESPACE_SETTINGS}
    try:
        yield
    finally:
        for name, value in saved.items():
            conn.execute(f"SET {name} = ?", [value])
