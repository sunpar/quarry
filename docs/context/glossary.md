# Glossary

Terms as Quarry's code and docs use them. Section numbers point into the
[design spec](../superpowers/specs/2026-10-08-quarry-design.md).

## Data and execution

- **Root**: the Quarry directory, `~/.quarry` by default, holding `config.toml`,
  `loaders.toml`, sessions, projects and the researcher's component library
  (§11).
- **Kernel**: the subprocess, one per session, that holds the working set and
  does all data work. It speaks JSON-RPC over a Unix socket (§6). Code lives in
  `quarry.kernel`.
- **Client**: `KernelClient`, the handle that spawns a kernel, calls its
  methods, interrupts it and closes it. It raises `KernelDead` when the kernel
  is gone or cannot start, and `RpcFailure` when a call fails.
- **Namespace**: the kernel's module-level globals, where step code runs. It
  starts with `pl`, `duckdb`, `loaders`, `sql`, `pq` and `sql_local`, plus
  `_conn` (the DuckDB connection) and `_registry` (the loader registry).
- **Loader**: a firm function listed in `loaders.toml` and bound as
  `loaders.<name>` (§7).
- **Dataset**: any top-level name bound to a polars `DataFrame` or `LazyFrame`
  or a DuckDB relation, including names that start with `_` (§5).
- **Backing**: how a dataset is held: `polars`, `polars_lazy` or `duckdb`.
- **Relation**: a `duckdb.DuckDBPyRelation`, which `pq()` returns and which is
  held with backing `duckdb`. It is lazy and has no row order.
- **Importable projection**: the projection that lets a relation convert to
  polars. INTERVAL and UNION columns become VARCHAR, and repeated column names
  become unique.
- **`DatasetMeta`**: a dataset's description: backing, schema as polars dtype
  strings, row count, preview, `origin_step` (the step that last wrote it,
  stamped by the server), and an error when it cannot be described (§5).
- **Preview**: a dataset's first 20 rows as JSON, computed when a step writes it
  and kept until the next step.
- **Dataset snapshot**: a dataset written to a parquet file by the kernel's
  `snapshot` method, as a pinned save does. Not to be confused with a view's
  state snapshot.
- **Guarded region**: the parts of a step where SIGINT raises
  `KeyboardInterrupt`: the step's `exec` and the describe of its writes.
  Elsewhere the signal is dropped.

## Steps and lineage

- **Session**: one researcher's scratch run of Quarry, with one kernel and a
  linear list of steps (§5).
- **Step**: one run of code, with its status (`running`, `ok`, `error` or
  `interrupted`), output tails, lineage and dataset metadata. Kinds are
  `prompt`, `manual`, `load` and `recall` (§5).
- **Tail**: the last 4096 characters of a step's stdout or stderr.
- **Lineage**: a step's `reads`, `writes` and `defines`, found by parsing the
  code before it runs and comparing object identities after (§6).

## Queries and views

- **Query spec**: the declarative query a view sends: filters, then group-by
  with aggregates or a pivot, then sort, offset, limit and select, in that order
  (§5). Code: `QuerySpec` in `quarry.query`.
- **Target**: one compiler output for a spec. `to_polars` returns a `LazyFrame`,
  `to_sql` returns DuckDB SQL, and `to_source` returns Python source text (§7).
- **Slice**: the rows a query returns. It is the only dataset content that
  reaches the browser.
- **To code**: turning a view's current specs into an editable Python step
  through `to_source` (§9, Stage 5).
- **View**: one mounted TSX component on one step (§5, Stage 3).
- **State snapshot**: a view's state at one moment, with the specs the view
  issued in that state. It makes to-code deterministic (§5).
- **Component**: a reusable TSX template with a manifest and no data attached
  (§5).

## Server and agent

- **Server**: the FastAPI app that `quarry serve` runs on `127.0.0.1` with a
  per-run bearer token. It owns sessions, their kernels and the agent loop (§4,
  §12). Code lives in `quarry.server`.
- **Provider**: the adapter for one model API, `AnthropicProvider` or
  `OpenAIProvider`, picked by `provider.name` in config (§8). It turns each
  reply into a provider-neutral `AssistantTurn`.
- **Agent loop**: `run_agent_step`, which calls the provider, runs the tool
  calls it asks for, and repeats until the model stops, up to 12 calls (§8).
- **Tools**: the five functions the model can call: `run_python`,
  `describe_dataset`, `search_components`, `render_view` and `write_view` (§8).
- **Repair rule**: a prompt step fails once two `run_python` calls in a row
  fail, which gives the model one try to fix its code (§8).
- **Transcript**: a prompt step's provider-neutral `Message`s: the request, each
  assistant turn and each batch of tool results. Saved on the step for "show
  reasoning" (§5).
- **Summary**: the text that opens each prompt step's request: earlier steps'
  prompts and code, then the datasets in the kernel (§8). Built by
  `build_summary`.
- **Pending view**: the component id, source, initial state and datasets a
  `render_view` or `write_view` call records while a prompt step runs, and that
  a view recall builds from a saved view. `View.from_pending` turns it into the
  step's `View`, adding the source's content hash.
- **Transpile check**: the server-side syntax check `render_view` and
  `write_view` run on generated TSX, through `transpile-check.mjs` under node
  when that file exists, for up to 30 s (§8).
- **Cancel**: a running step's stop signal, set by `/interrupt` for a prompt
  step and by `/restart`. The agent loop checks it before each provider call and
  tool call, and ends the step `interrupted`.
- **Run**: one execution of code in the kernel, saved on its step as
  `{code, status}`: each `run_python` call of a prompt step, or a manual step's
  code.
- **Replay**: rerunning a session's runs in order on a new kernel, which
  `POST /sessions/{id}/restart` does after stopping any running step (§6).

## Projects

- **Project**: a directory, `<root>/projects/<slug>/`, of saved datasets and
  views plus the canvas layout in `project.json`, which a researcher can copy,
  share or commit (§5, §10).
- **Recipe**: the self-contained Python a project saves to rebuild a dataset.
  `recipe.raw.py` joins the `ok` runs of the steps its lineage reaches;
  `recipe.py` is the model's tidied version, or the raw one when there is no
  tidy or it does not validate. `validated` says whether a scratch kernel
  reproduced the dataset from it (§10).
- **Pinned**: the save mode that also writes the dataset's rows to
  `data.parquet`, which recall then reads instead of running the recipe. The
  other mode, `live`, reruns the recipe (§10).
- **Recall step**: a step of kind `recall` that brings a saved dataset or view
  into a session. Its code is the recipe or a `pl.read_parquet` of the pinned
  file, a view recall also mounts the saved view with its saved state, and
  replay reruns it like any other step (§10).
- **Canvas card**: one saved view on a project's canvas, at a grid position and
  size kept in `project.json`. It renders in its own iframe and queries through
  the active session (§10).
- **Linked key**: a view-state key beginning with `shared:`. On the canvas the
  host copies a changed value into every other card; inside a session it stays
  private to its view (§9).
