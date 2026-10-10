from collections.abc import Iterator
from pathlib import Path

import polars as pl
import pytest

from quarry.kernel.client import KernelClient
from quarry.query import Filter, QuerySpec, Sort, to_source


def build_cache(root: Path) -> None:
    for year in (2023, 2024):
        path = root / "prices" / f"year={year}"
        path.mkdir(parents=True)
        pl.DataFrame({"ticker": ["A", "B"], "px": [1.0 * year, 2.0 * year]}).write_parquet(
            path / "p.parquet"
        )


@pytest.fixture
def kernel(tmp_path: Path) -> Iterator[KernelClient]:
    build_cache(tmp_path / "cache")
    (tmp_path / "config.toml").write_text(
        f'[data]\nparquet_root = "{tmp_path / "cache"}"\nrow_cap = 100\n'
    )
    client = KernelClient.spawn(tmp_path)
    yield client
    client.close()


def test_core_path(kernel: KernelClient, tmp_path: Path) -> None:
    loaded = kernel.execute("prices = pq('prices/**/*.parquet')")
    assert loaded.status == "ok"
    assert loaded.datasets[0].backing == "duckdb"

    recent = kernel.execute("recent = prices.filter('year = 2024').pl()")
    assert recent.reads == ["prices"]
    assert recent.datasets[0].backing == "polars"
    assert recent.datasets[0].rows == 2

    spec = QuerySpec(dataset="recent", filters=[Filter(col="ticker", op="eq", value="B")])
    assert kernel.query(spec).rows == [{"ticker": "B", "px": 4048.0, "year": 2024}]

    spec_rel = QuerySpec(
        dataset="prices",
        filters=[Filter(col="year", op="eq", value=2023)],
        sort=[Sort(col="ticker")],
    )
    assert [r["px"] for r in kernel.query(spec_rel).rows or []] == [2023.0, 4046.0]

    source = to_source(spec, "polars", result_name="only_b")
    materialized = kernel.execute(source)
    assert materialized.status == "ok"
    assert materialized.reads == ["recent"]
    assert materialized.writes == ["only_b"]

    # Generated DuckDB code runs on the relation's own connection, and lineage sees its read.
    rel_source = to_source(spec_rel, "duckdb", result_name="rel_2023")
    rel_step = kernel.execute(rel_source)
    assert rel_step.status == "ok"
    assert rel_step.reads == ["prices"]
    assert rel_step.writes == ["rel_2023"]
    rel_rows = kernel.query(QuerySpec(dataset="rel_2023")).rows or []
    assert [r["px"] for r in rel_rows] == [2023.0, 4046.0]

    # sql_local resolves kernel datasets by name from inside a step.
    total = kernel.execute("tot = sql_local('SELECT sum(px) AS s FROM recent').pl()")
    assert total.status == "ok"
    assert kernel.query(QuerySpec(dataset="tot")).rows == [{"s": 6072.0}]

    meta = kernel.snapshot("only_b", tmp_path / "only_b.parquet")
    assert meta.rows == 1
