# Quarry

Agentic data exploration for quant researchers. Design: `docs/superpowers/specs/2026-10-08-quarry-design.md`.

## Development

    uv sync --all-extras
    uv run pytest
    uv run ruff check src tests && uv run ruff format --check src tests
    uv run mypy src

## Using the core from a REPL (Stage 1)

```python
from pathlib import Path
from quarry.kernel.client import KernelClient
from quarry.query import QuerySpec, Filter, to_source

k = KernelClient.spawn(Path("~/.quarry").expanduser())
k.execute("prices = pq('prices/**/*.parquet')")
k.execute("recent = prices.filter('year = 2024').pl()")
k.query(QuerySpec(dataset="recent", filters=[Filter(col="ticker", op="eq", value="B")])).rows
print(to_source(QuerySpec(dataset="recent", limit=10), "polars"))
k.shutdown()
k.close()
```

The kernel reads `config.toml` from the root it is spawned with. Its namespace
starts with `pl`, `duckdb`, `loaders.<name>` for every valid entry in the root's
`loaders.toml`, `sql(query)` for SQL Server (set `data.mssql_dsn` or
`QUARRY_MSSQL_DSN` and install the `mssql` extra), `pq(glob)` for a DuckDB
relation over the Hive-partitioned parquet cache under `data.parquet_root`,
`sql_local(query)` for DuckDB SQL that reads the kernel's datasets by name, and
`catalog`, whose `register(name, frame)` makes a frame visible to DuckDB. All of
them share DuckDB's default connection, so `duckdb.sql` sees `pq` relations too.
`shutdown()` stops the kernel; `close()` then releases its socket directory.
