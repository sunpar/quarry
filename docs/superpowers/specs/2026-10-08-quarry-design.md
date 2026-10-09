# Quarry: agentic data exploration for quant researchers

Date: 2026-10-08
Status: approved design, pending implementation plan

## 1. Summary

Quarry is a tool a quant researcher launches from an SSH session on a shared
development machine. It loads data into memory, then lets the researcher
explore it step by step by prompting an agent that writes and runs the code.
The code stays hidden unless asked for. Results appear in a browser as
interactive views the agent draws with React. The researcher can save
checkpoints, both datasets and views, into named projects and reload them
later.

It replaces the current loop of "SSH in, open Jupyter, hand-write polars and
SQL to look at something."

### Goals

- Shorten the question-to-answer loop for data exploration.
- Keep every result reproducible: any dataset or view can be turned into
  plain Python the researcher could run in a notebook.
- Make large data interactive by never sending full results to the browser.
- Let researchers keep what they find, organized into projects.

### Non-goals (version one)

- Branching step histories. Steps in a session are linear.
- Multi-user shared sessions. One researcher, one server, one session at a
  time.
- A notebook editor. Quarry exports to notebooks; it does not edit them.
- Scheduling, alerting, or anything that runs without a researcher present.

## 2. The researcher's workflow

1. In an SSH terminal: `quarry serve`. It prints an `ssh -L` command and a
   URL containing a one-time token.
2. The researcher pastes the port-forward into a local terminal and opens the
   URL on their desktop browser.
3. They type "load the daily returns for the S&P 500 constituents for 2024."
   The agent calls a registered internal loader, the kernel holds the result
   as a named polars DataFrame, and a data table appears.
4. "Filter to tech sector, then join the factor exposures on ticker and date,
   left join, keep beta and momentum." The agent writes the polars, runs it,
   and draws a table. The researcher sorts and filters in the table directly.
5. "Plot cumulative returns by sector." The agent writes a small TSX
   component against Lightweight Charts, with a sector picker. The researcher
   flips through sectors.
6. They click "save view" into project "tech-momentum-2024". Quarry saves the
   TSX, the picker state, and the full Python lineage of the dataset it
   queries. Tomorrow they open the project, click the view, and it reloads
   with fresh data or a pinned snapshot, their choice at save time.
7. "Show me the code" on any step opens the Python that ran. "To code" on
   any view turns the current filter and sort into a new, editable Python
   step.

## 3. Decisions

| Area              | Decision                                                                                                              |
| ----------------- | --------------------------------------------------------------------------------------------------------------------- |
| Form factor       | Browser UI served from the dev machine on loopback, reached via SSH port-forward.                                     |
| Agent output      | No streaming. A step request returns when the agent finishes.                                                         |
| LLM access        | Researcher supplies an Anthropic or OpenAI API key. Provider is pluggable between the two.                            |
| Dataframes        | polars for in-memory work, DuckDB for out-of-core scans over the parquet cache.                                       |
| Data access       | A registry of internal loaders plus generic SQL Server and Hive-partitioned parquet fallbacks.                        |
| Views             | The agent writes TSX components rendered at runtime in a sandboxed iframe.                                            |
| Design system     | shadcn/ui on Tailwind.                                                                                                |
| Charts, always on | Plotly.js, Apache ECharts, Recharts, TradingView Lightweight Charts, FINOS Perspective, d3.                           |
| Charts, opt-in    | Highcharts Stock and SciChart.js, disabled unless a license key is configured.                                        |
| Tables            | AG Grid Community and TanStack Table. Never AG Grid Enterprise.                                                       |
| Checkpoints       | Projects hold saved datasets (code lineage, live or pinned) and saved views (TSX plus state plus dataset references). |

Licensing notes that drove the opt-in decision: Highcharts has no free tier for
commercial use. SciChart.js Community is for non-commercial use or time-limited
commercial evaluation and carries a permanent watermark. Lightweight Charts is
Apache 2.0 but requires visible TradingView attribution, so its built-in
attribution logo stays enabled. Perspective is Apache 2.0.

## 4. Architecture

Four parts: three processes on the dev machine and the browser on the desktop.

```
 desktop browser                        dev machine (shared, reached by SSH)
 ┌──────────────────────┐   ssh -L     ┌─────────────────────────────────────┐
 │ host app (React)     │◄────────────►│ quarry server (FastAPI, loopback)   │
 │   ┌────────────────┐ │   HTTP+token │   sessions, agent loop, providers,  │
 │   │ iframe runtime │ │              │   projects, persistence             │
 │   │ (generated TSX)│ │              │          │ JSON-RPC / unix socket   │
 │   └────────────────┘ │              │   ┌──────▼──────────────────────┐   │
 │     postMessage only │              │   │ kernel subprocess (1/session)│   │
 └──────────────────────┘              │   │ polars frames, DuckDB conn,  │   │
                                       │   │ loaders, lineage capture     │   │
                                       │   └─────────────────────────────┘   │
                                       └─────────────────────────────────────┘
```

**CLI.** `quarry serve` starts the server on a free loopback port (or
`--port`), generates a session token, and prints the `ssh -L` command and the
URL. `quarry projects list` and `quarry projects export <name>` are the only
other commands in version one.

**Server.** Python 3.11+, FastAPI, run with uvicorn. Owns sessions, the agent
loop, provider clients, projects, and persistence. Holds no dataset contents.
Serves the built frontend as static files. Every request carries the token as
a bearer header.

**Kernel.** One subprocess per session, spawned by the server, speaking
JSON-RPC over a Unix domain socket. Holds the working set and does all data
work. Details in section 6.

**Frontend.** Two Vite entry points built into one static directory that is
packaged inside the Python wheel, so `pip install quarry` (or `uv tool
install`) is the whole deployment. The host app and the iframe runtime share
no JavaScript state. Details in section 9.

**The slices-on-demand rule.** A step produces named datasets that live in
the kernel. Views ask for slices through a query spec. The kernel runs the
query and returns only that slice. The browser never holds a full dataset.
This is what keeps a 30 GB DuckDB-backed table interactive, and the same
query compiler that serves slices also renders view manipulations as Python.

**Request flow for one prompt.**

1. Browser posts the prompt to `POST /sessions/{id}/steps`. The server marks
   the session running and returns the step id.
2. The agent loop runs to completion (section 8). The model writes code via
   `run_python`, the server forwards it to the kernel, the kernel executes and
   reports datasets written. The model then renders or writes a view.
3. The server persists the step and marks the session idle.
4. The browser, which has been polling `GET /sessions/{id}/status`, fetches
   the step and mounts its view in the iframe. The view issues its first
   query over the bridge.

## 5. Data model

### Session

Scratch. Persisted so a reload or crash doesn't lose the transcript, but
disposable.

```
Session {
  id, title, created_at,
  provider: { name: "anthropic" | "openai", model },
  kernel: { status: "starting" | "idle" | "running" | "dead", pid },
  steps: Step[]              // linear, index order
}
```

### Step

```
Step {
  id, index,
  kind: "prompt" | "manual" | "load" | "recall",
  prompt: string | null,     // the researcher's text for prompt steps
  code: string,              // the final Python that ran
  status: "running" | "ok" | "error" | "interrupted",
  error: { type, message, traceback } | null,
  stdout_tail, stderr_tail,  // last 4 KB each
  reads: string[],           // dataset names read (lineage)
  writes: string[],          // dataset names written (lineage)
  defines: string[],         // functions/classes defined at top level
  datasets: DatasetMeta[],   // metadata for everything in `writes`
  view: View | null,
  transcript: Message[] | null,   // agent messages and tool calls, for "show reasoning"
  created_at, duration_ms
}
```

Step kinds: `prompt` is agent-driven. `manual` is code the researcher wrote
or edited, including the output of "to code". `load` is a dataset loaded
through the UI's loader form rather than a prompt. `recall` is a saved dataset
or view pulled in from a project.

### Dataset

A name in the kernel namespace. Registration is automatic: any top-level
assignment of a `polars.DataFrame`, `polars.LazyFrame`, or
`duckdb.DuckDBPyRelation` becomes a dataset.

```
DatasetMeta {
  name,
  backing: "polars" | "polars_lazy" | "duckdb",
  schema: [{ name, dtype }],       // dtype as polars dtype string
  rows: number | null,             // null for lazy or relation until counted
  preview: Row[],                  // first 20 rows, JSON
  origin_step: step id
}
```

### View

A view is one mounted component on one step.

```
View {
  component_id,          // library id, or "inline" for one-off generated code
  content_hash,          // sha256 of source, so library edits never rewrite history
  source: string,        // frozen TSX
  initial_state: Record<string, Json>,
  snapshots: Snapshot[]  // appended on state change, debounced 300 ms
}
Snapshot { ts, state: Record<string, Json>, queries: QuerySpec[] }
```

`queries` is the set of query specs the component issued while in that
state. This is what makes "to code" deterministic.

### Component (library entry)

Reusable templates with no data attached.

```
<library root>/<component-id>/
  component.tsx
  manifest.json {
    id, name, description, tags: string[],
    contract_version: 1,
    schema: { requires: [{ role, dtype: "datetime" | "numeric" | "string" | "any", min: number }] },
    origin: "builtin" | "generated" | "imported",
    created_at
  }
```

Three libraries, searched in order: built-ins inside the package, the
researcher's library under the Quarry root, and an optional team path from
config.

### Project

Durable checkpoints. A directory the researcher can copy, share, or commit.

```
<quarry root>/projects/<slug>/
  project.json            { name, description, created_at, updated_at,
                            canvas: [{ view: string, x, y, w, h }] }
  datasets/<name>/
    recipe.py             self-contained Python producing the dataset
    recipe.raw.py         the untidied concatenation, kept as fallback
    meta.json             { name, description, schema, rows, mode: "live" | "pinned",
                            saved_at, source_session, source_step, validated: bool }
    data.parquet          present when mode is "pinned"
  views/<name>/
    view.tsx
    state.json            the Snapshot.state at save time
    queries.json          the Snapshot.queries at save time (Stage 5 export renders them)
    meta.json             { name, description, datasets: string[], component_id,
                            saved_at, source_session, source_step }
```

### Query spec

The declarative language under every view and every "to code" action.

```
QuerySpec {
  dataset: string,
  select?: string[],
  filters?: Filter[],
  group_by?: string[],
  aggs?: Agg[],
  pivot?: { index: string[], columns: string, values: string, agg: AggFn },
  sort?: [{ col, desc: boolean }],
  limit?: number,          // default and max: config row_cap (default 50000)
  offset?: number,
  format?: "json" | "arrow" // default json; Perspective uses arrow
}
Filter { col, op: "eq" | "ne" | "lt" | "le" | "gt" | "ge" | "in" | "not_in"
             | "between" | "contains" | "starts_with" | "is_null" | "not_null",
         value?: Json }
Agg { col, fn: AggFn, alias?: string }
AggFn = "sum" | "mean" | "min" | "max" | "count" | "median" | "std" | "first" | "last"
```

Evaluation order is fixed: filters, then group-by with aggs or pivot (never
both), then sort, then offset and limit, then select. A spec with both
`group_by` and `pivot` is rejected. `first` and `last` need a row order, which
a DuckDB relation does not have, so specs on relation-backed datasets reject
them.

## 6. Kernel

A plain Python process, started by the server with the session id and socket
path as arguments. It imports polars and duckdb, builds the data layer
(section 7) into a module-level namespace, and serves JSON-RPC.

### Methods

| Method                 | Behavior                                                                                                                                                                          |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `execute(code)`        | Runs code in the persistent namespace. Returns stdout tail, stderr tail, error or null, reads, writes, defines, and `DatasetMeta` for each write. Never raises across the socket. |
| `interrupt()`          | Sends SIGINT to the executing thread via `signal.pthread_kill`.                                                                                                                   |
| `describe(name)`       | Returns `DatasetMeta`, counting rows for lazy and relation datasets.                                                                                                              |
| `query(spec)`          | Compiles and runs a query spec. Returns rows as JSON or an Arrow IPC buffer plus the result schema.                                                                               |
| `list_datasets()`      | All registered datasets with metadata.                                                                                                                                            |
| `snapshot(name, path)` | Writes the dataset to parquet, collecting lazy frames and materializing relations.                                                                                                |
| `shutdown()`           | Clean exit.                                                                                                                                                                       |

The server treats a broken socket as a dead kernel. Recovery is restart and
replay: a new kernel, then every step's code re-executed in order. Replay
runs as a single "restart" operation with progress in the UI, and stops at
the first failing step.

### Lineage capture

Before executing, the kernel parses the code with `ast` and collects, at
module level only: names in `Store` context (candidate writes), names in
`Load` context including the root of attribute chains (candidate reads), and
function and class definitions (defines). After executing, it diffs the
namespace: objects of the three dataset types that are newly bound or whose
`id()` changed.

- `writes` = candidate writes that are now dataset objects.
- `reads` = candidate reads that were datasets before execution, plus
  candidate reads that match an earlier step's `defines`.
- `defines` = top-level function and class names.

Reads of defined functions are what make a helper defined in step 3 and used
in step 7 appear in step 7's lineage. The server stores reads and writes on
the step; the dependency graph is derived, not stored.

### Resource limits

Optional memory cap from config applied with `resource.setrlimit(RLIMIT_AS)`
at kernel start. Query results are capped at `row_cap` rows regardless of the
spec. Execution has no timeout; the researcher interrupts.

## 7. Data layer

Everything lives in the kernel namespace, so the agent and the researcher use
identical calls.

**Loader registry.** A TOML file at `<quarry root>/loaders.toml` maps names
to importable functions:

```toml
[[loader]]
name = "daily_returns"
description = "Daily total returns by ticker. Returns polars DataFrame with date, ticker, ret."
import = "firmlib.data.returns:load_daily"
signature = "load_daily(tickers: list[str], start: date, end: date) -> pl.DataFrame"
```

At kernel start each loader is imported and bound under `loaders.<name>`.
The list, with descriptions and signatures, goes into the agent's system
prompt. A failed import is reported once in the UI and the loader is skipped.

**SQL Server.** `sql(query: str, *, params=None) -> pl.DataFrame`, built on
`arrow-odbc` so results arrive as Arrow and convert to polars without a
pandas hop. Connection string from config or the `QUARRY_MSSQL_DSN`
environment variable.

**Parquet catalog.** A DuckDB connection with the Hive root from config.
`pq(path_glob: str) -> duckdb.DuckDBPyRelation` wraps `read_parquet` with
`hive_partitioning=true`. Every dataset is also visible to DuckDB SQL by
name: the kernel's connection resolves table names from the step's variables
(`python_scan_all_frames`), so `sql_local("select ...")` runs DuckDB over
in-memory frames and always sees the current binding. At session start the kernel scans the
cache root two levels deep and reports the partition layout (directory names
and partition keys) for the agent's context.

**Query spec compiler.** A pure module, `quarry.query`, with three functions
over a `QuerySpec` and a backing kind:

- `to_polars(spec, frame_or_lazy)` returns a `LazyFrame`.
- `to_sql(spec, relation_name)` returns a DuckDB SQL string.
- `to_source(spec, backing)` returns Python source text that a researcher can
  read and run, in polars for polars-backed datasets and DuckDB SQL wrapped in
  Python for relation-backed ones.

Both execution targets run against one shared fixture set in tests and must
produce identical results. Pivot uses `polars.pivot` on a collected frame and
DuckDB `PIVOT`.

## 8. Agent loop

### Provider interface

```python
class Provider(Protocol):
    def complete(self, *, system: str, messages: list[Message], tools: list[ToolDef]) -> AssistantTurn: ...
```

Two implementations, Anthropic and OpenAI, each a thin adapter over the
vendor SDK. No streaming. Rate-limit and network errors retry twice with
backoff, then fail the step with the provider's message.

### Loop

1. Build the system prompt and the session summary (below).
2. Append the researcher's prompt.
3. Call the provider. If the turn has no tool calls, the step is done and the
   assistant text becomes the step's note.
4. Dispatch each tool call, append results, go to 3.
5. Hard cap of 12 iterations per step, after which the step fails with the
   partial transcript saved.

### Tools

| Tool                | Input                                       | Result                                                                           |
| ------------------- | ------------------------------------------- | -------------------------------------------------------------------------------- |
| `run_python`        | `code`                                      | stdout, stderr, error, and `DatasetMeta` for each dataset written                |
| `describe_dataset`  | `name`                                      | `DatasetMeta` with a full row count                                              |
| `search_components` | `tags?`, `dataset?`                         | Manifests whose schema requirements the dataset satisfies, ranked by tag overlap |
| `render_view`       | `component_id`, `datasets`, `initial_state` | Mount result: ok, or the mount error                                             |
| `write_view`        | `source`, `initial_state`                   | Mount result: ok, or the transpile or mount error                                |

`render_view` and `write_view` run a server-side transpile check with Sucrase
before accepting, so syntax errors come back without a browser round trip.
Mount errors from the browser are not available synchronously (the agent loop
is finished before the browser mounts), so the first mount is optimistic. If
the browser reports a mount error, the host offers "fix this" which starts a
new agent step with the error as context. Repair is one attempt; a second
failure stays visible.

### Context

System prompt, assembled once per session and cached: the component contract
and the three hooks, the library guide (which chart library for what, listing
only enabled libraries), registered loaders with signatures, the parquet
layout, the names of the data layer helpers, and the rule that computation
belongs in Python and in query specs, not in component JavaScript.

Session summary, rebuilt per step: for each prior step, its prompt and the
code that ran, plus the current dataset list with schemas. Once the summary
exceeds a configured token budget, steps older than the last eight collapse
to prompt and datasets written only. Full transcripts are never replayed.

### Library guide, as given to the model

- Lightweight Charts: price and return series, OHLC, when speed and a clean
  look matter more than annotations.
- Plotly: scatter, heatmap, 3D, statistical plots, anything general.
- ECharts: series with more than about 100k points, calendar and sankey.
- Recharts: small aggregated bar and line charts inside shadcn layouts.
- Perspective: when the researcher should drive pivots and filters directly.
- AG Grid: tables with column filters and resizing. TanStack Table: tables
  that need custom cell rendering inside shadcn styling.
- d3: only when nothing above fits.
- Highcharts Stock and SciChart.js appear only when enabled in config.

## 9. Frontend

### Host app

React 19, TypeScript strict, Vite, React Query v5, shadcn/ui, Tailwind. Three
regions:

- **Left rail.** Sessions list. Below it, the open project's saved datasets
  and views. Clicking a saved item creates a recall step.
- **Main column.** The step history. Each step shows its prompt, a status
  line, the view if any, dataset chips for what it wrote, and a collapsed
  code drawer. Dataset chips have "save dataset". Views have "save view",
  "to code", and a history scrubber over snapshots.
- **Prompt box.** Pinned at the bottom. Disabled while a step is running,
  with an interrupt button.

Presentational components under `components/` take props only. Containers
under `pages/` and `containers/` own React Query calls and compose them.
Query keys come from one factory module. Files stay under 250 lines.

### Iframe runtime

A second Vite entry built to its own HTML page, served with a Content
Security Policy that forbids all network access (`default-src 'none'` with
`script-src 'self'` and `style-src 'self' 'unsafe-inline'`). It loads once
per view slot and stays mounted. Its bundle contains React, shadcn, Tailwind,
the bridge, and Sucrase. Each chart library is a separate chunk loaded by the
runtime's import resolver the first time a component imports it. The opt-in
licensed libraries are not bundled in the wheel. When a license key and an
install path are configured, the server serves that locally installed package
as an extra chunk and adds it to the allowlist. The resolver refuses imports
for anything not in the allowlist.

On `mount`, the runtime transpiles the TSX with Sucrase (`jsx`, `typescript`
transforms), evaluates it with a `require` bound to the allowlist and the
hooks module, and renders the default export inside an error boundary.

### Bridge

postMessage with correlation ids. Every message carries `viewId`.

Host to runtime: `mount { source, initialState, datasets }`,
`restore { state }`, `queryResult { id, ok, schema, rows | arrow | error }`,
`schemaResult { id, ok, schema | error }`.

Runtime to host: `ready`, `query { id, spec }`, `schema { id, dataset }`,
`stateChanged { state, queries }`, `error { message, stack }`.

That is the entire surface. The host serves `query` by calling
`POST /sessions/{id}/query`, which forwards to the kernel. The host is the
only party holding the token.

### Hooks exposed to generated code

```ts
useQuery(spec: QuerySpec): { status: "loading" }
                          | { status: "success"; rows: Row[]; schema: Column[] }
                          | { status: "error"; message: string }
useViewState<T extends Json>(key: string, initial: T): [T, (next: T) => void]
useDatasetSchema(name: string): Column[] | null
```

`useViewState` posts `stateChanged` debounced at 300 ms, with the query specs
issued since the last change. Nothing else is importable from the hooks
module.

A `key` beginning with `shared:` is a linked key. On the project canvas the
host keeps one value per linked key across every mounted view, so a date
range or ticker chosen in one card re-queries every card that reads the same
key. Inside a session each view's linked keys are private to that view.

### Built-in components

Shipped in the package with manifests: data table (AG Grid), data table
(TanStack), time series line (Lightweight Charts), OHLC (Lightweight Charts),
bar and line (Recharts), scatter (Plotly), heatmap (Plotly), large series
(ECharts), pivot (Perspective). Each built-in exposes its filters and
groupings through `useViewState` and pushes them into its query specs, so
every built-in supports "to code" out of the box.

The Perspective built-in converts the viewer's saved config (group_by,
split_by, columns, filter, sort, aggregates) into a query spec before
reporting state, so Perspective manipulations translate deterministically like
everything else. It requests `format: "arrow"` and receives an Arrow IPC
buffer over the bridge.

### To code

The host sends the current snapshot's query specs to
`POST /sessions/{id}/to-code`. The server renders each with `to_source` and
returns Python. The host creates a `manual` step with that code in an
editable drawer. Running it executes in the kernel like any other step, so
its outputs join the lineage graph.

## 10. Projects

### Save dataset

1. The server walks the session's dependency graph backward from the dataset:
   every step whose writes or defines are reachable through reads, in step
   order. Their code is concatenated into `recipe.raw.py`.
2. One provider call tidies it into a self-contained script: remove unused
   loads and dead assignments, keep behavior identical, end with the dataset
   bound to its name. The instruction forbids changing any loader call,
   filter, join, or aggregation.
3. Validation: a scratch kernel runs the tidied script. The output schema must
   equal the live dataset's schema exactly and the row count must match. On
   success it is written as `recipe.py` and `validated` is true. On failure
   `recipe.py` is a copy of the raw concatenation, `validated` is false, and
   the UI says so.
4. If the researcher chose pinned, the kernel snapshots the dataset to
   `data.parquet`.

### Save view

Saves the step's frozen TSX, the current snapshot's state, and the
component id. For each dataset the view's queries reference, saves that
dataset into the project first if it isn't already there, prompting once for
live versus pinned. The view's `meta.json` lists those dataset names.

### Canvas

Each project has a canvas tab: a snap-to-grid dashboard of saved views, each
in its own iframe slot, draggable and resizable. Positions and sizes live in
`project.json` under `canvas`. "Pin to canvas" on a step's view saves the
view (if not already saved) and appends a card. The canvas is a grid, not an
infinite pan-and-zoom surface, because data views need to render at legible
native size. The session's step column stays linear and chronological; the
canvas is the curated arrangement, the step column is the record. Linked
keys (section 9, hooks) make cards cross-filter.

### Recall

Recalling a dataset creates a `recall` step whose code is the recipe (live)
or a `pl.read_parquet` of the pinned file, executed in the session kernel.
Recalling a view recalls its datasets, then mounts the view with the saved
state. Because recall is a real step with real code, anything derived from it
later has correct lineage.

### Export

`quarry projects export <name>` and the UI's export button produce a Jupyter
notebook: for each saved dataset, a markdown cell with name and description
and a code cell with the recipe; for each saved view, a markdown cell with
its description, its dataset recipes if not already emitted, a code cell with
the `to_source` rendering of its saved queries, and the TSX in a fenced block
for reference. A saved dataset also exports alone as a `.py` script.

## 11. Persistence layout

```
<quarry root>  (default ~/.quarry, override with --root or config)
  config.toml
  loaders.toml
  sessions/<session-id>/
    session.json
    steps/0001.json, 0002.json, ...
  projects/<slug>/...        (section 5)
  components/<id>/...        (researcher's library, section 5)
```

Steps are written once on completion. A crash loses at most the in-flight
step. Everything is plain text except pinned parquet.

### Config

```toml
[provider]
name = "anthropic"            # or "openai"
model = "claude-sonnet-5-5"
# api key from QUARRY_ANTHROPIC_API_KEY / QUARRY_OPENAI_API_KEY, or:
api_key_file = "~/.quarry/anthropic.key"   # owner-only permissions enforced

[data]
parquet_root = "/data/cache"
mssql_dsn = ""                # or QUARRY_MSSQL_DSN
row_cap = 50000
kernel_memory_mb = 0          # 0 = unlimited

[libraries]
team_components = ""          # optional shared library path
highcharts_license = ""       # enables Highcharts Stock when set, with:
highcharts_path = ""          # path to a locally installed highcharts npm package
scichart_license = ""         # enables SciChart.js when set, with:
scichart_path = ""            # path to a locally installed scichart npm package
```

## 12. Security

- Server binds `127.0.0.1` only.
- A random 32-byte token is generated per `quarry serve`, printed once, and
  required as a bearer header on every request. The printed URL carries it in
  the fragment; the host app reads it on load and keeps it in memory only.
- The kernel runs as the researcher's own user. It executes their code on
  their behalf, exactly as a notebook kernel does.
- Generated TSX runs only in the iframe with a no-network CSP. The bridge is
  the only path out and has three request types.
- API keys come from environment variables or an owner-only file. The server
  refuses a key file with group or world permissions and never logs key
  values.
- Generated code and query specs are never evaluated in the host page.

## 13. Error handling

| Failure                          | Behavior                                                                                                                                      |
| -------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- |
| Python error in a step           | Returned as a structured tool result. The agent gets one repair attempt. A second failure ends the step with the traceback shown in the step. |
| Kernel crash                     | Broken socket marks the kernel dead and fails the step. The UI offers restart and replay.                                                     |
| Provider error                   | Two retries on rate limit and network faults, then the step fails with the provider's message.                                                |
| Transpile error in generated TSX | Caught server-side, returned to the agent as the tool result.                                                                                 |
| Mount error in the browser       | Error boundary shows the message in place of the view. "Fix this" starts a repair step with the error as context.                             |
| Query spec rejected              | 400 with the validation message; the view shows the error state.                                                                              |
| Save validation failure          | Raw concatenation saved, `validated: false`, UI badge explains.                                                                               |
| Loader import failure            | Reported once at session start, loader omitted from context.                                                                                  |

## 14. Testing

Pure modules get the most coverage because they must not drift.

- **Query compiler.** One fixture set of specs and frames. Every spec runs
  through `to_polars` and `to_sql` and the results must be equal. `to_source`
  output is executed and compared too.
- **Lineage.** Code snippets with expected reads, writes, and defines,
  including attribute chains, rebinding, and helper functions used across
  steps.
- **Agent loop.** A fake provider that replays scripted turns. Covers tool
  dispatch, the iteration cap, repair-once, and summary collapse.
- **Kernel.** Run as a real subprocess over the socket: execute, interrupt a
  busy loop, describe, query, snapshot, crash detection.
- **Projects.** Save dataset with a scripted tidy response, validation pass
  and fail paths, pinned snapshot, recall as a step, export structure.
- **Frontend.** Vitest for the bridge, the hooks, and the built-in table and
  Lightweight Charts components. One Playwright test boots the server with a
  fake provider, mounts a built-in view, and exercises a query round trip.
- **Providers.** A live smoke test per provider, skipped unless an API key
  environment variable is set.

Python: pytest, ruff format and check, type checking treated as a gate.
TypeScript: vitest, prettier, `tsc --noEmit` in strict mode.

## 15. Build order

Each stage is usable on its own before the next starts.

1. **Core.** Python package layout, kernel subprocess and protocol, data
   layer, query compiler, lineage capture. Usable from a REPL. Fully tested.
2. **Server and agent.** FastAPI app, session persistence, provider adapters,
   the five tools, the agent loop, status polling. Usable from curl with a
   real key.
3. **First UI.** Host app, iframe runtime, bridge, hooks, the AG Grid table
   and the Lightweight Charts time series built-ins, code drawer, interrupt.
   This is the milestone to put in front of a researcher.
4. **Projects.** Save dataset with tidy and validation, pinned snapshots,
   save view, recall, project browser in the rail, the canvas tab with
   drag and resize, pin to canvas, linked keys across cards.
5. **Breadth.** Remaining built-ins, researcher and team libraries,
   `search_components`, to-code, Perspective with Arrow transport, export, the
   opt-in licensed libraries, CLI project commands.

## 16. Deferred

Recorded so they are not rediscovered as gaps: branching histories,
Perspective server mode (its own WebSocket protocol, not agent streaming),
Arrow transport for all views rather than only Perspective, sharing projects
beyond copying a directory, multiple concurrent sessions per server, and a
step timeout.

## 17. Repository layout

```
quarry/
  pyproject.toml              uv-managed, Python 3.11+
  src/quarry/
    cli.py
    server/      FastAPI app, routes, session store, project store
    kernel/      subprocess entry, JSON-RPC, lineage, data layer bindings
    query/       QuerySpec model, to_polars, to_sql, to_source
    agent/       providers, loop, tools, context builder
    projects/    save, recall, export
    static/      built frontend, produced by `npm run build` in web/
    components/  built-in TSX and manifests
  web/
    package.json
    src/host/    host app
    src/runtime/ iframe runtime, bridge, hooks
    src/shared/  types shared by host and runtime (QuerySpec, bridge messages)
  tests/
  docs/superpowers/specs/
```

Conventions follow the user's global rules: strict TypeScript with no `any`,
files under 250 lines, presentational and container split, typed Python with
built-in generics, ruff and prettier on every file.
