# Quarry

Agentic data exploration for quant researchers. See the [design spec](docs/superpowers/specs/2026-10-08-quarry-design.md).

Project docs, starting with the current working state, are indexed in
[docs/README.md](docs/README.md).

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src
```

## Using the core from a REPL (Stage 1)

The snippet assumes `config.toml` under the root (`~/.quarry` here) sets
`data.parquet_root`.

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
starts with:

- `pl` and `duckdb`
- `loaders.<name>` for every valid entry in the root's `loaders.toml`
- `sql(query)` for SQL Server: set `data.mssql_dsn` or `QUARRY_MSSQL_DSN` and
  install the `mssql` extra
- `pq(glob)` for a DuckDB relation over the Hive-partitioned parquet cache under
  `data.parquet_root`
- `sql_local(query)` for DuckDB SQL that reads the kernel's datasets by name

`pq`, `sql_local` and `duckdb.sql` share DuckDB's default connection, so
`duckdb.sql` sees `pq` relations too.

`execute` returns the step's status, the tails of its output, its lineage
(`reads`, `writes`, `defines`) and metadata for the datasets it wrote. The client
also has `describe`, `list_datasets`, `query`, `interrupt` and `snapshot`.
`shutdown()` stops the kernel, and `close()` then releases its socket directory.

## Driving the server from curl (Stage 2)

```bash
export QUARRY_ANTHROPIC_API_KEY=...   # or QUARRY_OPENAI_API_KEY, with provider.name = "openai" and provider.model = "gpt-5" in config.toml
quarry serve --root ~/.quarry          # prints the port and token
T="Bearer <token>"; U=http://127.0.0.1:<port>
SID=$(curl -s -X POST $U/sessions -H "Authorization: $T" -H 'Content-Type: application/json' -d '{"title":"demo"}' | jq -r .id)
curl -s -X POST $U/sessions/$SID/steps -H "Authorization: $T" -H 'Content-Type: application/json' -d '{"prompt":"load the parquet cache prices for 2024 and show the first rows"}'
curl -s $U/sessions/$SID/status -H "Authorization: $T"          # poll until running_step is null
curl -s $U/sessions/$SID -H "Authorization: $T" | jq '.steps[-1] | {status, note, writes}'
curl -s -X POST $U/sessions/$SID/query -H "Authorization: $T" -H 'Content-Type: application/json' -d '{"dataset":"prices","limit":5}'
```

Server-side refusal fallbacks are enabled by default on Anthropic requests.
