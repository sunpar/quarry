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
  provider: { name, model } | null,  // the model a prompt step called
  code: string,              // the final Python that ran
  runs: { code, status }[],  // each execution in order, for replay
  status: "running" | "ok" | "error" | "interrupted",
  error: { type, message, traceback } | null,
  stdout_tail, stderr_tail,  // last 4 KB each
  reads: string[],           // datasets and earlier defines read (lineage)
  writes: string[],          // dataset names written (lineage)
  defines: string[],         // other names bound at top level (lineage)
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
  origin_step: step id | null      // the step that last wrote it
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
    meta.json             { name, description, backing, schema, rows,
                            mode: "live" | "pinned", saved_at, source_session,
                            source_step, validated: bool,
                            validation_error: the reason when not validated }
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
  line_reduce?: { time: string, value: string, max_rows?: number },
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
both), then sort, then offset and limit, then select. Grouped and pivoted rows
sort by `sort`, then by each group key or pivot index column it leaves out,
ascending with nulls first, so paging through them is stable. A spec with both
`group_by` and `pivot` is rejected. `first` and `last` need a row order, which
a DuckDB relation does not have, so specs on relation-backed datasets reject
them.

`line_reduce` replaces grouping, pivot, sort, select, offset and limit. Filters
define the full requested domain; the output contains the two axis columns.
`time` is Date or Datetime and `value` is numeric. All backings and generated
source enforce axis types, including empty and fully filtered domains. Missing times are omitted;
non-finite values become null. Rows sort by time, then value with nulls first.
Exact duplicate pairs are interchangeable. When rows exceed `max_rows` (default
50,000, capped by `row_cap`), reduction first reserves both endpoints of every
null run, then divides the full time range into equal-width bins, retaining each
bin's first, last, minimum and maximum rows. Extrema ties choose the earliest
ordered row. Constant times use one bin. Budgets that cannot fit all gap markers
and one four-row bin fail; all-null inputs need only their run endpoints. Inputs
within budget keep every ordered row. Results report `source_row_count` after
missing-time removal and `reduced` when representatives omit rows, independently
of prefix `truncated`.

This is a lossy line overview, not raw-data reconstruction or a promise of
pixel-identical rendering at every zoom level. "To code" uses the same effective
budget as the query. Notebook exports capture the active server cap when
generated; standalone exports use the project configuration. The large-series
view preserves null breaks and does no
additional browser sampling. Polars materializes only the filtered axis columns
on the server, then uses the shared DuckDB reducer on a private connection with
one thread, a 256 MiB memory limit and no disk spill. Relation-backed reduction
uses its existing connection. Oversized in-memory reductions fail rather than
increase resource limits.

Polars sends time as integer ticks in its original unit, and 128-bit values as
decimal strings, restoring both axis dtypes after reduction. This preserves
zoned nanosecond timestamps and the full integer range. Polars `to_source`
restores its runtime axis dtypes inside an isolated execution scope. Supplied
schemas validate axes and coerce filter literals before rendering; schema-less
exports retain the compiler's documented literal-coercion limits. DuckDB
relation output uses the relation's existing temporal precision and UTC timezone
schema.

## 6. Kernel

A plain Python process, started by the server with its socket path, the
quarry root and a private temp directory as arguments. It imports polars and
duckdb, builds the data layer (section 7) into a module-level namespace, and
serves JSON-RPC.

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
replay: a new kernel, then every step's runs re-executed in order, one at a
time. A run that failed the first time may fail again, so its partial effects
come back; interrupted runs are skipped. Replay runs as a single "restart"
operation with progress in the UI, and stops at the first run that succeeded
before and fails now, or that is interrupted. A restart while a step runs
cancels the step and kills the kernel first, and saves the step as interrupted.

### Lineage capture

Before executing, the kernel parses the code with `ast` and collects, at
module level only: names in `Store` context (candidate bindings), names in
`Load` context including the root of attribute chains (candidate reads),
function and class definitions, and the roots of method calls whose result a
statement drops, such as `params.update(...)` (effects). After executing, it
diffs the namespace: names that are newly bound or that hold another object
than before. Together with the candidate bindings and effects, on names that
do not hold the same module as before (effects also skip datasets), these are
the step's bound names.
When the code raises or is interrupted, only the namespace diff counts, since
a store may never have run.

- `writes` = bound names that are now dataset objects.
- `defines` = every other bound name: helpers, imports, and parameters such
  as `params = {...}`. A `def` or `class` is not a candidate binding: one that
  ran made a new object, and one that never ran left its name alone.
- `reads` = candidate reads that were datasets before execution or match an
  earlier step's `defines`. A load after a statement directly in the module
  body binds the name is not a candidate read, since it sees the step's own
  binding. A candidate binding inside a block of such a name that still holds
  the same object is a read too, since its store may never have run.

Reads of earlier `defines` are what make a helper or a parameter bound in
step 3 and used in step 7 appear in step 7's lineage. The server stores
reads, writes and defines on the step; the dependency graph is derived, not
stored.

### Resource limits

Optional memory cap from config applied with
`resource.setrlimit(RLIMIT_DATA)` at kernel start, and an optional thread cap
for polars and DuckDB. Query results are capped at `row_cap` rows regardless
of the spec. Execution has no timeout; the researcher interrupts.

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

### Runtime interface

The server selects an `AgentRuntime` for both prompt steps and recipe tidying:

```python
class AgentRuntime(Protocol):
    def run_step(self, *, prompt: str, system: str, summary: str, tools: ToolExecutor, cancel: threading.Event) -> StepOutcome: ...
    def complete_text(self, *, system: str, prompt: str, cancel: threading.Event) -> AssistantTurn: ...
```

`ApiRuntime` owns Quarry's loop for Anthropic and OpenAI. Codex app-server and
the Claude Agent SDK own their native loops, with a fresh conversation for each
operation. All modes dispatch Quarry tools through the same execution policy.
The runtime releases its transport when an operation succeeds, fails or is
cancelled. A callback already executing in the kernel settles before the step
saves its runs.

### API provider interface

```python
class Provider(Protocol):
    def complete(self, *, system: str, messages: list[Message], tools: list[ToolDef]) -> AssistantTurn: ...
```

Anthropic and OpenAI implement this interface as thin adapters over their vendor
SDKs. No streaming. Rate-limit and network errors retry twice with backoff, then
fail the step with the provider's message. Native modes use the runtime
interface directly and never fall back to an API provider.

### Loop

1. Build the system prompt and the session summary (below).
2. Append the researcher's prompt.
3. Call the provider. If the turn has no tool calls, the step is done and the
   assistant text becomes the step's note.
4. Dispatch each tool call, append results, go to 3.
5. API mode permits 12 `Provider.complete` calls per step, then fails with the
   partial transcript saved. Native mode permits 12 Quarry tool calls, then
   fails before another tool executes. Native internal model calls are not
   counted as API iterations.

Native adapters restrict tools to Quarry's five tools. Native shell, file
writes, subagents, hooks and inherited MCP tools cannot perform step work. The
supported CLI and SDK controls must enforce that boundary; an unsupported
runtime fails rather than relying on prompt instructions. Codex selects direct
tool dispatch through a private per-operation model catalog, preserving the
requested model ID without changing your normal Codex configuration. Claude's
in-process MCP server advertises the same schemas but sends argument validation
to Quarry, so malformed requests still count toward repair and call budgets.

### Tools

| Tool                | Input                                       | Result                                                                           |
| ------------------- | ------------------------------------------- | -------------------------------------------------------------------------------- |
| `run_python`        | `code`                                      | stdout, stderr, error, and `DatasetMeta` for each dataset written                |
| `describe_dataset`  | `name`                                      | `DatasetMeta` with a full row count                                              |
| `search_components` | `tags`, `dataset` (`""` for none)           | Manifests whose schema requirements the dataset satisfies, ranked by tag overlap |
| `render_view`       | `component_id`, `datasets`, `initial_state` | Mount result: ok, or the mount error                                             |
| `write_view`        | `source`, `datasets`, `initial_state`       | Mount result: ok, or the transpile or mount error                                |

Tool schemas are strict, so every input is required and `initial_state` is a
JSON object encoded as a string.

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
code that ran, plus the current dataset list with schemas. The dataset list
counts against a token budget of 24,000 estimated tokens first; if it alone
exceeds the budget, each dataset keeps only its column count. Once the steps
exceed what is left, steps older than the last eight collapse to prompt and
datasets written only. Full transcripts are never replayed.

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
Security Policy that allows nothing but the Quarry server's own static files
(`default-src 'none'`, `script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'`,
`worker-src blob:` for Perspective's engine worker, `connect-src 'self'` for
wasm and chunk fetches, `style-src 'self' 'unsafe-inline'`). It loads once
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

postMessage with correlation ids. Every view-specific message carries `viewId`.

Host to runtime: `connect { id }`, `mount { source, initialState, datasets }`,
`restore { state }`, `queryResult { id, ok, schema, rows | arrow | error }`,
`schemaResult { id, ok, schema | error }`.

Runtime to host: `ready { id }`, `query { id, spec }`, `schema { id, dataset }`,
`stateChanged { state, queries }`, `error { message, stack }`.

The host installs its listener before `connect`; the runtime acknowledges with
`ready` echoing the connection ID, and the host consumes that acknowledgment once
before sending its queued mount. Content changes reuse the bridge. History restores
and linked changes wait for the mount; the latest full restore replaces earlier
queued linked changes, and later linked changes follow it.
The host serves concurrent identical `query` specs in the same session and data
generation through one in-flight `POST /sessions/{id}/query`, which forwards to
the kernel. Settled host results are discarded; runtime caches and state remain
per view. The host is the only party holding the token.

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
2. The selected runtime's `complete_text` tidies it without tools into a
   self-contained script: remove unused loads and dead assignments, keep
   behavior identical, end with the dataset bound to its name. The instruction
   forbids changing any loader call, filter, join, or aggregation. API mode
   makes one provider call; native mode starts a fresh conversation. Missing
   login or an unavailable runtime leaves the raw recipe for local validation.
   No provider mode is required to save.
3. Validation: a scratch kernel runs the tidied script. The output schema must
   equal the live dataset's schema exactly and the row count must match. On
   success it is written as `recipe.py` and `validated` is true. When the tidied
   script fails or no tidy is available, the raw concatenation is validated in
   its place, and on success it is `recipe.py` with `validated` true. Only when
   neither reproduces the dataset is the save unvalidated: `recipe.py` is the
   raw concatenation, `validated` is false, `validation_error` gives the reason,
   and the UI says so.
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
code that renders its saved queries with `to_source` against the rebuilt
datasets' schema and backing, displays that Python and executes it, and the
TSX in a fenced block for reference. Rendering runs after every dataset recipe;
export generation runs no recipes or live queries. Notebook metadata records
Quarry, Python, Polars and DuckDB versions from the export environment, without
pinning input data or installing dependencies. A saved dataset also exports
alone as a `.py` script.

`--format html` and "Export HTML report" produce a self-contained, script-free
report from saved metadata, recipes, views, state, query specs and the first
20 pinned dataset rows. They execute no recipe, query or view. Live dataset
results and rendered view results are marked unavailable because they are not
persisted. Saved timestamps describe Quarry saves, not upstream freshness.
The escaped UTF-8 document is capped at 5 MiB; missing or corrupt saved
artifacts fail the export. CLI notebook and HTML outputs are private atomic
writes.

## 11. Persistence layout

```
<quarry root>  (default ~/.quarry, override with --root)
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
name = "anthropic"            # or "openai", "codex", "claude-code"
model = "claude-opus-5-5"
# api key from QUARRY_ANTHROPIC_API_KEY / QUARRY_OPENAI_API_KEY, or:
api_key_file = "~/.quarry/anthropic.key"   # owner-only permissions enforced
# Native modes use CLI login, require an explicit model, and reject api_key_file.
# cli_path = "/path/to/provider-cli"       # optional, otherwise use PATH

[data]
parquet_root = "/data/cache"
mssql_dsn = ""                # or QUARRY_MSSQL_DSN
row_cap = 50000
kernel_memory_mb = 0          # 0 = unlimited
kernel_threads = 0            # 0 = every core

[libraries]
team_components = ""          # optional shared library path
highcharts_license = ""       # enables Highcharts Stock when set, with:
highcharts_path = ""          # path to a locally installed highcharts npm package
scichart_license = ""         # enables SciChart.js when set, with:
scichart_path = ""            # path to a locally installed scichart npm package
```

Each library `*_path` is served whole to any origin, so it must be the package
folder itself, never a broad folder such as `~` or `~/Downloads`. `cli_path`
names an executable and is never served. All paths expand `~` and resolve
relative to the Quarry root.

## 12. Security

- Server binds `127.0.0.1` only.
- A random 32-byte token is generated per `quarry serve`, printed once, and
  required as a bearer header on every API request. The health check and the
  host app's static files are open, since a browser loading the page cannot send
  the header. The printed URL carries the token in the fragment; the host app
  reads it on load and keeps it in memory only.
- The kernel runs as the researcher's own user. It executes their code on their
  behalf, exactly as a notebook kernel does.
- Generated TSX runs only in the iframe, whose CSP reaches nothing but the
  server's own static files; API routes need the bearer token the frame never
  holds. The bridge is the only path to data and has three request types.
- `quarry serve` creates a missing quarry root owner-only, and the server
  creates session directories and writes session files owner-only, since several
  researchers share each machine.
- API keys come from environment variables or an owner-only file. The server
  refuses a key file with group or world permissions and never logs key values.
- Codex and Claude Code own native login and credential storage under the
  server's OS user. Quarry invokes their installed CLIs without extracting
  tokens. Authentication or quota failures never trigger API billing.
- Generated code and query specs are never evaluated in the host page.

## 13. Error handling

| Failure                          | Behavior                                                                                                                                                |
| -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------- |
| Python error in a step           | Returned as a structured tool result. The agent gets one repair attempt. A second failure ends the step with the traceback shown in the step.           |
| Kernel crash                     | Broken socket marks the kernel dead and fails the step. The UI offers restart and replay.                                                               |
| Provider error                   | API modes retry rate limit and network faults twice. Native authentication, quota and protocol failures fail the step and retain completed Python runs. |
| Transpile error in generated TSX | Caught server-side, returned to the agent as the tool result.                                                                                           |
| Mount error in the browser       | Error boundary shows the message in place of the view. "Fix this" starts a repair step with the error as context.                                       |
| Query spec rejected              | 400 with the validation message; the view shows the error state.                                                                                        |
| Save validation failure          | Raw concatenation validated if the tidy fails or is absent; if neither reproduces the data, raw saved, `validated: false`, UI badge explains.           |
| Loader import failure            | Reported once at session start, loader omitted from context.                                                                                            |

## 14. Testing

Pure modules get the most coverage because they must not drift.

- **Query compiler.** One fixture set of specs and frames. Every spec runs
  through `to_polars` and `to_sql` and the results must be equal. `to_source`
  output is executed and compared too.
- **Lineage.** Code snippets with expected reads, writes, and defines, including
  attribute chains, rebinding, and helper functions used across steps.
- **Agent loop.** A fake provider that replays scripted turns. Covers tool
  dispatch, the iteration cap, repair-once, and summary collapse.
- **Kernel.** Run as a real subprocess over the socket: execute, interrupt a
  busy loop, describe, query, snapshot, crash detection.
- **Projects.** Save dataset with a scripted tidy response, validation pass and
  fail paths, pinned snapshot, recall as a step, export structure.
- **Frontend.** Vitest for the bridge, the hooks, and the built-in table and
  Lightweight Charts components. One Playwright test boots the server with a
  fake provider, mounts a built-in view, and exercises a query round trip.
- **Providers.** API live smoke tests require an API key. Native contract tests
  use fake transports and real local kernels; live native probes require an
  explicit opt-in and the provider's login on the server.

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
