from collections.abc import Iterator
from pathlib import Path

import duckdb
import polars as pl
import pytest

from quarry.config import DataConfig, QuarryConfig
from quarry.data.loaders import LoaderRegistry
from quarry.data.namespace import build_namespace, configure_connection
from quarry.kernel.datasets import dataset_names
from quarry.kernel.executor import Executor
from quarry.query import Filter, QuerySpec

# Every namespace shares DuckDB's default connection, so names here are unique per test.
# The settings an uncapped build_namespace changes on it.
SETTINGS = ("python_scan_all_frames", "TimeZone", "temp_directory")
UTC_ROWS = (
    "SELECT * FROM (VALUES (1, TIMESTAMPTZ '2024-01-01 00:00:00+00'), "
    "(2, TIMESTAMPTZ '2024-01-01 03:00:00+00'), (3, TIMESTAMPTZ '2024-01-01 06:00:00+00')) t(n, ts)"
)


def setting(conn: duckdb.DuckDBPyConnection, name: str) -> object:
    row = conn.sql(f"SELECT current_setting('{name}')").fetchone()
    assert row is not None
    return row[0]


@pytest.fixture(autouse=True)
def default_connection_restored() -> Iterator[None]:
    """build_namespace configures the default connection, which the whole session shares."""
    conn = duckdb.default_connection()
    saved = {name: setting(conn, name) for name in SETTINGS}
    yield
    for name, value in saved.items():
        conn.execute(f"SET {name} = ?", [value])


def test_connection_spills_under_the_temp_dir(tmp_path: Path) -> None:
    conn = duckdb.connect()
    configure_connection(conn, tmp_path, memory_mb=0, threads=0)
    assert Path(str(setting(conn, "temp_directory"))).parent == tmp_path


def test_memory_limit_is_70_percent_of_the_kernel_cap(tmp_path: Path) -> None:
    conn = duckdb.connect()
    configure_connection(conn, tmp_path, memory_mb=1000, threads=0)
    assert setting(conn, "memory_limit") == "700.0 MiB"


def test_memory_limit_stays_the_default_without_a_cap(tmp_path: Path) -> None:
    conn = duckdb.connect()
    configure_connection(conn, tmp_path, memory_mb=0, threads=0)
    assert setting(conn, "memory_limit") == setting(duckdb.connect(), "memory_limit")


def test_threads_caps_duckdb(tmp_path: Path) -> None:
    conn = duckdb.connect()
    configure_connection(conn, tmp_path, memory_mb=0, threads=2)
    assert setting(conn, "threads") == 2


def test_threads_stay_the_default_without_a_cap(tmp_path: Path) -> None:
    conn = duckdb.connect()
    configure_connection(conn, tmp_path, memory_mb=0, threads=0)
    assert setting(conn, "threads") == setting(duckdb.connect(), "threads")


def test_naive_iso_string_against_timestamptz_reads_as_utc(tmp_path: Path) -> None:
    spec = QuerySpec(
        dataset="t",
        filters=[Filter(col="ts", op="ge", value="2024-01-01T02:00:00")],
        select=["n"],
    )
    configured = duckdb.connect()
    configure_connection(configured, tmp_path, memory_mb=0, threads=0)
    new_york = duckdb.connect()
    new_york.execute("SET TimeZone = 'America/New_York'")
    assert Executor({"t": configured.sql(UTC_ROWS)}, conn=configured, row_cap=10).query(
        spec
    ).rows == [
        {"n": 2},
        {"n": 3},
    ]
    # The setting is what fixes it: in New York the string means 07:00 UTC.
    assert Executor({"t": new_york.sql(UTC_ROWS)}, conn=new_york, row_cap=10).query(spec).rows == []


def test_namespace_has_expected_names(tmp_path: Path) -> None:
    (tmp_path / "loaders.toml").write_text(
        '[[loader]]\nname = "daily_returns"\ndescription = "d"\n'
        'import = "tests.data.fake_firmlib:load_daily"\nsignature = "load_daily(tickers)"\n'
    )
    ns = build_namespace(QuarryConfig(root=tmp_path), tmp_path)
    assert {"pl", "duckdb", "loaders", "sql", "pq", "sql_local"} <= set(ns)
    assert ns["pl"] is pl
    assert ns["loaders"].daily_returns(["X"])["ticker"].to_list() == ["X"]
    # A view it registered shadowed the name's later rebindings; sql_local reads them by name.
    assert "catalog" not in ns


def test_injected_names_are_not_datasets(tmp_path: Path) -> None:
    assert dataset_names(build_namespace(QuarryConfig(root=tmp_path), tmp_path)) == set()


def test_sql_local_sees_step_frames_by_name(tmp_path: Path) -> None:
    ns = build_namespace(QuarryConfig(root=tmp_path), tmp_path)
    ex = Executor(ns, conn=duckdb.default_connection(), row_cap=100)
    ex.execute("df_r18 = pl.DataFrame({'a': [1, 2]})")
    r = ex.execute("s_r18 = sql_local('SELECT sum(a) AS s FROM df_r18').pl()")
    assert r.status == "ok"
    assert ns["s_r18"]["s"].to_list() == [3]
    rebind = ex.execute("df_r18 = None")
    assert rebind.status == "ok"
    gone = ex.execute("t_r18 = sql_local('SELECT sum(a) AS s FROM df_r18').pl()")
    assert gone.status == "error"
    assert gone.error is not None and "df_r18" in gone.error.message


def test_pq_relations_are_visible_to_duckdb_sql(tmp_path: Path) -> None:
    root = tmp_path / "cache"
    (root / "px_r15").mkdir(parents=True)
    pl.DataFrame({"a": [1, 2, 3]}).write_parquet(root / "px_r15" / "part.parquet")
    ns = build_namespace(QuarryConfig(root=tmp_path, data=DataConfig(parquet_root=root)), tmp_path)
    ex = Executor(ns, conn=duckdb.default_connection(), row_cap=100)
    ex.execute("rel_r15 = pq('px_r15/*.parquet')")
    r = ex.execute("n_r15 = duckdb.sql('SELECT count(*) AS n FROM rel_r15').pl()")
    assert r.status == "ok"
    assert ns["n_r15"]["n"].to_list() == [3]


def test_namespace_builds_when_loaders_toml_is_malformed(tmp_path: Path) -> None:
    (tmp_path / "loaders.toml").write_text('[[loader]\nname = "daily_returns"\n')
    ns = build_namespace(QuarryConfig(root=tmp_path), tmp_path)
    registry = ns["_registry"]
    assert isinstance(registry, LoaderRegistry)
    assert [f.name for f in registry.failures] == ["loaders.toml"]
    assert vars(ns["loaders"]) == {}
