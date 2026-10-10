# Quarry

Agentic data exploration for quant researchers. See the
[design spec](docs/superpowers/specs/2026-10-08-quarry-design.md).

Project docs, starting with the current working state, are indexed in
[docs/README.md](docs/README.md).

## Development

```bash
uv sync --all-extras
uv run pytest
uv run ruff check src tests && uv run ruff format --check src tests
uv run mypy src tests
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
(`reads`, `writes`, `defines`) and metadata for the datasets it wrote. The
client also has `describe`, `list_datasets`, `query`, `interrupt` and
`snapshot`. `shutdown()` stops the kernel, and `close()` then releases its
socket directory.

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

## Using the browser UI (Stage 3)

Build the UI once, then serve:

```bash
cd web && npm ci && npm run build && cd ..
uv run quarry serve
```

Open the printed link (it carries the token after `#`). From a laptop, forward
the port first with the `ssh -L` line the banner prints.

The server checks each generated view's syntax with `node` before saving it.
Without `node` on `PATH` it logs a warning at startup and skips that check; a
broken view then fails in the browser, where "Fix this view" sends it back to
the agent.

### Developing the UI

```bash
uv run quarry serve --port 8765          # terminal 1
cd web && QUARRY_PORT=8765 npm run dev    # terminal 2, open http://localhost:5173/#token=<token>
```

Vite proxies `/sessions`, `/projects`, `/components`, `/libraries`, `/libs` and
`/healthz` to the Python server. `npm run check`, `npm test`, and
`npm run build` must pass before a commit; the Playwright tests under
`tests/e2e` run only when `src/quarry/static/index.html` exists. They need a
browser, installed once with `uv run playwright install chromium`; without it
they error whenever a build exists.

## Projects (Stage 4)

A project keeps what a session produced. Create one with "New project" in the
rail, then:

- **Save** a dataset with "Save" beside its chip, or a view with "Save view"
  under its frame. A dataset is saved as a recipe, the code that made it, tidied
  by the model and checked in a fresh kernel. A view is saved with its TSX, its
  latest state and the datasets it reads, which are saved first. "Pinned copy"
  also keeps today's rows as parquet. A recipe that does not reproduce the data
  is still saved, marked unvalidated with the reason.
- **Recall** by clicking a project in the rail to list what it holds, then a
  dataset or view. The recall runs as a step in the open session, replacing a
  dataset of the same name after you confirm, and a restart replays it like any
  other step.
- **Canvas**: "Pin to canvas" saves a view and adds it as a card. "Open" on a
  project shows its Saved and Canvas tabs. Cards drag by their title bar, resize
  from the corner, and query through the open session; a card whose datasets the
  session lacks offers "Load". Cards that share a `shared:` state key stay in
  step.

Each project is a directory under the Quarry root, `~/.quarry/projects/<slug>/`,
with `project.json` (name and canvas layout), `datasets/<name>/` and
`views/<name>/`; the
[design spec](docs/superpowers/specs/2026-10-08-quarry-design.md#project) lists
every file. Everything is plain text except pinned parquet. Files are
owner-only, so `chmod` a project before sharing it in place.

### Export

"Export notebook" on a project page downloads `<slug>.ipynb`: each saved
dataset's recipe, then each saved view's queries as Python and its TSX.
"Download recipe" beside a saved dataset downloads its `recipe.py`. The command
line writes the same notebook and needs no running server:

```bash
quarry projects list --root ~/.quarry                       # slug, name, last update
quarry projects export momentum --root ~/.quarry            # writes ./momentum.ipynb
quarry projects export momentum --out ~/notebooks/mom.ipynb
```

An exported view's queries render without the dataset's schema, which only a
live session has, and the cell says so; "To code" under the view in a session
renders them exactly.

## Libraries

Highcharts Stock and SciChart.js are licensed, so Quarry never bundles them.
Install the package yourself, then name its folder and your key in
`config.toml`:

```toml
[libraries]
highcharts_license = "your_highcharts_license_key"
highcharts_path = "/path/to/node_modules/highcharts"
scichart_license = "your_scichart_license_key"
scichart_path = "/path/to/node_modules/scichart"
```

A library is enabled only when its key and path are both set and the path holds
its entry file, `highstock.js` or `index.min.mjs`; a key without a usable path
logs one warning at startup. The server then serves that folder under
`/libs/<id>/` to any origin, so each `*_path` must be the library's package
folder itself, never a broad folder such as `~` or `~/Downloads`. A relative
path resolves under the root. `GET /libraries` reports each library's status,
and the agent's library guide lists only the enabled ones. Restart the server
after installing or moving a package.
