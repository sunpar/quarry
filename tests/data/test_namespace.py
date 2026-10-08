from pathlib import Path

import polars as pl

from quarry.config import DataConfig, QuarryConfig
from quarry.data.loaders import LoaderRegistry
from quarry.data.namespace import build_namespace
from quarry.kernel.executor import Executor

# Every namespace shares DuckDB's default connection, so names here are unique per test.


def test_namespace_has_expected_names(tmp_path: Path) -> None:
    (tmp_path / "loaders.toml").write_text(
        '[[loader]]\nname = "daily_returns"\ndescription = "d"\n'
        'import = "tests.data.fake_firmlib:load_daily"\nsignature = "load_daily(tickers)"\n'
    )
    ns = build_namespace(QuarryConfig(root=tmp_path))
    assert {"pl", "duckdb", "loaders", "sql", "pq", "sql_local", "catalog"} <= set(ns)
    assert ns["pl"] is pl
    assert ns["loaders"].daily_returns(["X"])["ticker"].to_list() == ["X"]


def test_registered_frames_are_visible_to_sql_local(tmp_path: Path) -> None:
    ns = build_namespace(QuarryConfig(root=tmp_path))
    ns["catalog"].register("f_ns_registered", pl.DataFrame({"a": [4]}))
    assert ns["sql_local"]("SELECT a FROM f_ns_registered").pl()["a"].to_list() == [4]


def test_sql_local_sees_step_frames_by_name(tmp_path: Path) -> None:
    ns = build_namespace(QuarryConfig(root=tmp_path))
    ex = Executor(ns, row_cap=100)
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
    ns = build_namespace(QuarryConfig(root=tmp_path, data=DataConfig(parquet_root=root)))
    ex = Executor(ns, row_cap=100)
    ex.execute("rel_r15 = pq('px_r15/*.parquet')")
    r = ex.execute("n_r15 = duckdb.sql('SELECT count(*) AS n FROM rel_r15').pl()")
    assert r.status == "ok"
    assert ns["n_r15"]["n"].to_list() == [3]


def test_namespace_builds_when_loaders_toml_is_malformed(tmp_path: Path) -> None:
    (tmp_path / "loaders.toml").write_text('[[loader]\nname = "daily_returns"\n')
    ns = build_namespace(QuarryConfig(root=tmp_path))
    registry = ns["_registry"]
    assert isinstance(registry, LoaderRegistry)
    assert [f.name for f in registry.failures] == ["loaders.toml"]
    assert vars(ns["loaders"]) == {}
