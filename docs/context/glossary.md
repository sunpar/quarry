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
  is gone and `RpcFailure` when a call fails.
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
  strings, row count, preview, and an error when it cannot be described (§5).
- **Preview**: a dataset's first 20 rows as JSON, computed when a step writes
  it.
- **Dataset snapshot**: a dataset written to a parquet file by the kernel's
  `snapshot` method. Stage 4 uses it for pinned project datasets. Not to be
  confused with a view's state snapshot.
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
- **Recipe**: the self-contained Python a project saves to rebuild a dataset,
  assembled from lineage (§5, Stage 4).

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
- **Project**: a directory of saved datasets and views that a researcher can
  copy, share or commit (§5, Stage 4).
