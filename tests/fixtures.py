"""Helpers for tests that change process-wide state: file modes, the umask, `os.fsync` and
DuckDB's default connection."""

import os
import stat
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import duckdb
import pytest

# The settings build_namespace changes on DuckDB's default connection, but memory_limit, which
# is reset instead: current_setting rounds it, and setting 19.1 GiB back reads 19.0 GiB (probed).
NAMESPACE_SETTINGS = ("python_scan_all_frames", "TimeZone", "temp_directory", "threads")

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


def mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


@contextmanager
def umask(mask: int) -> Iterator[None]:
    previous = os.umask(mask)
    try:
        yield
    finally:
        os.umask(previous)


def record_fsyncs(monkeypatch: pytest.MonkeyPatch) -> list[os.stat_result]:
    """Each file `os.fsync` is given from now on, as `fstat` saw it."""
    synced: list[os.stat_result] = []
    fsync = os.fsync

    def recording_fsync(fd: int) -> None:
        synced.append(os.fstat(fd))
        fsync(fd)

    monkeypatch.setattr(os, "fsync", recording_fsync)
    return synced


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
        # Nothing else sets the default connection's memory_limit, so its default is the value
        # the block started with.
        conn.execute("RESET memory_limit")
