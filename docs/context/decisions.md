# Decisions

This file records calls made during the build where the spec and plan were
silent, ambiguous or wrong, and deliberate departures from them. The
[design spec](../superpowers/specs/2026-10-08-quarry-design.md) stays the design
authority. Append new decisions to the matching section as later stages make
them.

## Query compiler

- **SQL aggregate semantics on both targets**: `sum` over no non-null values is
  null on the polars target, as in SQL, and polars pivots aggregate through
  `pl.element()` expressions. polars 2.0 summed nothing to 0 and rejected
  `"count"` as a pivot aggregate. Cost if wrong: an absent pivot cell shows null
  for `sum` where a reader might expect 0.
- **Nulls sort first**: both targets put nulls first in ascending and descending
  sorts, so the SQL target emits `NULLS FIRST`. A probe showed DuckDB sorts
  nulls last by default and polars first. Cost if wrong: nulls show at the top
  of sorted views.
- **Exact integer sums**: the polars target sums integer columns of up to 64
  bits as `Decimal(38, 0)`, matching DuckDB's HUGEINT sums. polars sums Int64 in
  Int64 and wraps silently on overflow; 128-bit integers, which can exceed the
  decimal, sum natively. Cost: these sums measured 1.3 to 1.8 times slower.
- **Literals take the column's type**: `coerce_literal` converts filter literals
  to the column dtype for `to_polars` and for schema-aware `to_source`. JSON
  from JavaScript drops the `.0` of whole floats, and polars 2.0 `is_in` is
  strictly typed, so `ret in [0]` failed on a float column. A fractional number
  against an integer column compares as Float64.
- **One column-reference check**: `quarry/query/columns.py` checks every column
  a spec names, for every target, since two copies would drift. A pivot's sort
  and select are checked against the pivoted frame, because its columns come
  from the data.
- **Sorted pivot columns**: polars pivots pass `sort_columns=True`, so new
  columns come out in the order DuckDB `PIVOT` gives them.
- **Relation pivots split between DuckDB and polars**: DuckDB filters the
  relation and projects the pivot's inputs, then polars pivots. DuckDB 1.5.6
  cannot run `PIVOT` without an `IN` list through `relation.query`, and an `IN`
  list would freeze pivot values into saved code. Projecting only the inputs cut
  a 3M-row benchmark from 377 to 35 ms and peak memory from 3.5 to 1.9 GB.
- **No `first` or `last` on relations**: `to_sql` and `split_for_relation`
  reject them, as aggregates and as the pivot aggregate. A relation has no row
  order: on a 20M-row file, three runs gave three different answers. The spec is
  amended; researchers use `min` or `max`, or convert with `.pl()` first.
- **Specs reject unknown keys**: every query spec model sets `extra="forbid"`.
  Agent-written views send these specs, and a misspelled `filtr` would return
  unfiltered data. Cost if wrong: a client sending extra keys gets a validation
  error.
- **Filter values are checked by shape**: comparisons need a scalar, `contains`
  and `starts_with` a string, and `in` or `not_in` a non-empty list without
  nulls. SQL `NOT IN (1, NULL)` is never true, while polars ignores the null.
  Non-finite floats are rejected at any depth, since JSON cannot carry them.
- **No empty lists**: `select`, `group_by` and `Pivot.index` need at least one
  entry, so global aggregates are out of scope. Empty lists caused DuckDB parser
  errors and differences between targets. Cost: a client omits a key rather than
  sending `[]`.
- **Output names are unique, ignoring case**: a spec is rejected when its group
  keys and aggregate names repeat a name, or when `select` does. polars raises
  on a duplicate, DuckDB renames it or returns it twice, and DuckDB identifiers
  ignore case. Cost: a polars frame cannot select two names that differ only in
  case.
- **`Pivot.agg` takes every aggregate**: `std` is allowed, as spec §5 says. The
  plan narrowed the list only because polars string pivot aggregates lacked
  `std`, and `pl.element()` expressions close that gap.
- **A naive ISO string against a zoned column means UTC**: both targets read it
  as UTC and compare in the column's zone. The kernel's DuckDB session runs in
  UTC, so every host agrees.
- **An offset ISO string against a naive column follows DuckDB**: a nanosecond
  column converts it to UTC, while microsecond and millisecond columns drop the
  offset and keep the wall clock. DuckDB 1.5.6 casts this way, and equivalence
  tests pin it. Cost: a DuckDB upgrade could change the rule, which is an
  [open question](../open-items.md#open-questions).
- **Schema-aware generated source**: `to_source` takes an optional `schema`, and
  with it, literals and integer sums match `to_polars` exactly. Without it, a
  string becomes a date or datetime only when the whole string is valid ISO, and
  numbers render as given.
- **Safe generated literals**: strings render through `json.dumps` with every
  non-printable character escaped, and indentation splits on `\n` only. Raw
  U+2028 or U+0085 split literals across lines and changed filter values, and
  raw bidi controls make code read differently from what runs.
- **Relation source reads the dataset by name**: `to_source(spec, "duckdb")`
  renders `{dataset}.query("_quarry_{dataset}", sql).pl()`, not
  `duckdb.sql(...)`. Lineage then records the read, and the query runs on the
  relation's own connection. The `_quarry_` prefix avoids DuckDB's infinite
  recursion over a same-named table.
- **Generated relation code drops its view**: it drops `_quarry_<dataset>` in a
  `finally`, through the relation, so a failed query releases it too. The name
  stays deterministic because to-code output must be, and `_quarry_` is reserved
  for Quarry. Kept after review; the executor uses unique names instead.
- **Generated code stays plain Python**: to-code output needs only `pl`, the
  dataset and the standard library, so it runs in a notebook, as spec §2 and §5
  require. Only Quarry's own projection converts INTERVAL output, since `.pl()`
  and `pl.from_arrow` both fail. Kept after review; cost: to-code on interval
  output fails loudly until Stage 5.
- **Clashing names are rejected**: relation to-code needs a result name other
  than the dataset's, because the view drop runs through the dataset afterwards.
  A polars dataset named `date`, `datetime` or `ZoneInfo` is rejected when a
  generated import would rebind it.

## Kernel and executor

- **One thread touches the namespace**: `execute`, `describe`, `query`,
  `list_datasets` and `snapshot` run in order on the kernel's main thread. The
  reader thread frames requests and answers only `interrupt` and `shutdown`. A
  query on the reader thread had cut a running step's DuckDB stream to 399k of
  3M rows, with status `ok`. Cost: queries wait while a step runs.
- **The kernel never raises across the socket**: the service turns every failure
  into an `RpcError` named for its class. It catches `BaseException` but
  re-raises `KeyboardInterrupt`, `SystemExit` and `GeneratorExit`, because
  pyo3's `PanicException` is a `BaseException` (probed) and a polars panic would
  otherwise kill the kernel.
- **`execute` never raises**: if describing a written dataset fails, the step's
  status becomes `error`. Messages survive an exception whose `__str__` fails,
  and non-string namespace keys are ignored. `globals()[1] = 1` had made every
  later step fail before running.
- **Dataset detection uses `type(obj)`**: never `obj.__class__`, which a proxy
  can make raise. Such a proxy failed every later step.
- **Exact truncation**: `query` fetches `row_cap + 1` rows and reports
  `truncated` only when more than `row_cap` came back. The plan's heuristic
  marked an exactly full result as truncated.
- **Bounded output tails**: step stdout and stderr go to a writer that keeps at
  most `tail_bytes` characters while the step runs. A runaway print loop had
  grown memory by about 50 MB/s.
- **`SystemExit` in a step is an error**: a step calling `exit()` gets an error
  result, and the kernel keeps running. Shutdown therefore never relies on
  raising it.
- **Relation queries see the types describe reports**: the executor runs a
  spec's SQL on the importable projection, with INTERVAL and UNION as VARCHAR
  and repeated names made unique. Filters then match the advertised schema.
  Cost: interval columns of relations filter and sort as text.
- **Per-query view names**: each relation query registers
  `_quarry_<dataset>_<hex>` and drops it afterwards, on success or failure.
  `relation.query` replaces any temp view of the same name, so a fixed name
  could destroy one the researcher made. An undropped view pins the relation's
  data.
- **Polars dtype strings for every backing**: `DatasetMeta` takes dtypes from
  the preview frame's polars schema, relations included, as spec §5 says.
- **Snapshots stream and are atomic**: a snapshot writes a temp file beside the
  target and renames it into place. Relations stream through DuckDB's Arrow
  reader into pyarrow's `ParquetWriter`, since DuckDB's `write_parquet` stored a
  HUGEINT sum as Float64 and UUID as binary. The metadata describes the written
  file under the source dataset's backing.
- **Startup failures surface at once**: `spawn` notices a kernel that exits
  before connecting and raises `KernelDead` with its exit code. A bad
  `config.toml` used to cost the full startup timeout.
- **Malformed lines never kill a reader**: the kernel answers an undecodable
  request with an `RpcError` when it can recover an integer id, and otherwise
  logs it to stderr. The client treats an undecodable response as a dead kernel.
  A dead reader thread had hung every pending call forever.
- **Kernel output is inherited, not piped**: the kernel writes to the server's
  stdout and stderr. C-level output from user code goes to those file
  descriptors, and an undrained pipe would block the kernel once full.

## Interrupts

- **SIGINT lands only in guarded regions**: the handler raises
  `KeyboardInterrupt` only inside a step's `exec` or one describe of its writes,
  and drops the signal elsewhere. The reader delivers it to the main thread with
  `signal.pthread_kill`, as spec §6 says. A late signal anywhere else would kill
  the kernel.
- **`interrupt` reports delivery**: it answers `{"delivered": bool}`, true only
  when it hit a running step. An early interrupt is dropped rather than saved
  for the next step, so callers retry until delivered.
- **An interrupted step reports `interrupted`**: once the handler fires, the
  status is `interrupted` whatever the step raised next, including DuckDB's own
  "Query interrupted" error. Cost: a step that catches the interrupt and
  finishes still reports interrupted.
- **Interrupted steps skip their previews**: describing a step's writes can be
  interrupted, and once a step is interrupted none of its writes is described.
  Each carries the error `interrupted`, and `list_datasets` describes them
  later. The researcher asked for control back, and a preview can be the slow
  part.
- **Interrupts also stop DuckDB**: the handler calls `interrupt()` on the
  kernel's DuckDB connection before raising. In a probe, an interrupted `.pl()`
  left workers running and the next query waited 1.88 s; with the call it waited
  0.00 s. Cost: relations on a researcher's own `duckdb.connect()` keep running.
- **The kernel runs in its own session**: it is spawned with
  `start_new_session=True`, so a terminal Ctrl-C aimed at the server never
  interrupts a step. The server owns interrupts.
- **`POST /interrupt` passes delivery through**: it answers `{"ok": delivered}`
  with the kernel's flag, so a client knows when to retry. The plan's
  `{"ok": true}` hid an interrupt that hit nothing.

## Lineage

- **Module level only**: function, lambda and comprehension scopes contribute
  only their free names as reads, never stores, and a `del` target is neither. A
  false write of a common name like `df` would put wrong steps into saved
  recipes.
- **Syntactic stores count as writes**: a successful step writes every dataset
  name it stores, plus names newly bound or rebound to another object. polars
  in-place methods return the same object (`df.extend(...) is df`, probed), so
  identity alone misses `df = df.extend(other)`. Kept after review; cost: a
  store that never ran, as in `if x is None: x = ...`, reports a false write.
- **Failed steps report only identity changes**: on error or interrupt the store
  term is dropped, because a store may not have run. Kept after review; cost: a
  failed step's in-place mutation is not a write.
- **Identity through weak references**: rebinding is detected against
  `weakref.ref` snapshots taken before the step, falling back to `id()` only for
  types that refuse weak references. Plain `id()` missed a write when a freed
  object's address was reused, which a reviewer reproduced deterministically.
- **Class-body reads stay over-reported**: every name a class body loads counts
  as a read, even one the body binds first. An extra read only adds a dependency
  to a recipe, never drops one, while exact handling needs execution-order
  analysis. Kept after review.
- **`defines` are names the step bound**: a function or class name counts only
  when the step newly bound or rebound it, so a `def` that never ran is not a
  define. A helper is forgotten once its name is rebound or deleted, so later
  reads are not credited to it.
- **Exception aliases are not datasets**: a module-level `except ... as name`
  does not store `name`, and loading it in the handler is not a read. Python
  deletes the alias when the handler ends.
- **No recursion limit**: the analyzer walks the AST with an explicit work
  stack, so code CPython compiles, such as 3000 chained operands, never raises
  `RecursionError`. Errors from `ast.parse` itself become a structured step
  error.

## Datasets and JSON

- **Decimals are exact strings**: JSON rows carry Decimal values, nested ones
  too, as decimal strings such as `"900"`, so every integer sum arrives as a
  string. Float64 would silently change `Decimal("9007199254740993")` while the
  schema still said Decimal. The arrow format keeps native decimals.
- **Non-finite floats are null**: inf, -inf and NaN become JSON null at any
  depth, which keeps each column's JSON type uniform. The arrow format keeps
  them, and the Stage 3 renderer may choose sentinels.
- **JSON rows never panic**: Binary becomes base64, Object becomes `str`, naive
  datetimes get an ISO `T`, and dates outside chrono's range become null. polars
  `write_json` panicked on Binary and on DuckDB's `'infinity'`, a common
  end-of-validity marker.
- **INTERVAL and UNION become text**: one helper projects these columns, at any
  depth, as VARCHAR before `.pl()` and reports them as String. `.pl()` rejects
  INTERVAL, nested INTERVAL panics, and polars' environment-variable import path
  segfaulted. Cost: intervals arrive as DuckDB text such as `"1 day 02:00:00"`.
- **Repeated relation names are made unique**: describe, query and snapshot
  rename repeats as DuckDB's `.pl()` does, ignoring case, so `a, a, A` become
  `a, a_1, A_2`. Columns are projected by position, so each name reads the right
  column.
- **Underscore names are datasets**: `_tmp` is a dataset like any other name,
  since spec §5 counts any top-level assignment. The plan excluded `_`-prefixed
  names, which dropped intermediates from lineage. Cost: underscore
  intermediates appear in `list_datasets`.
- **Broken datasets stay listed**: `DatasetMeta` has an optional `error`, and a
  dataset that cannot be described is listed with it and an empty schema. One
  broken LazyFrame had made every `list_datasets` call fail, and omitting it
  would hide it. An explicit `describe(name)` still raises.

## Data layer and config

- **One DuckDB connection**: `pq`, `sql_local`, `duckdb.sql` and `_conn` all use
  `duckdb.default_connection()`. Replacement scans across connections raise
  `InvalidInputException` (probed), so step code could not mix them otherwise.
  Cost: tests in one process share its state, and open result streams get cut
  short.
- **`sql_local` uses replacement scans**: the connection runs
  `SET python_scan_all_frames = true`, so DuckDB resolves dataset names from the
  calling step's variables. The spec's `duckdb.register` was dropped because
  registered views returned stale data after a rebind. `catalog` left the
  namespace for the same reason, and the spec is amended.
- **`loaders.toml` never stops the kernel**: a syntax error, a malformed or
  duplicate entry, a non-identifier name or a failed import each becomes a
  `LoaderFailure`, and the rest still bind. A loader raising `SystemExit` at
  import counts as failed, while `KeyboardInterrupt` propagates. One typo had
  killed every kernel.
- **`sql()` keeps the schema on zero rows**: it reads arrow-odbc's pyarrow
  `RecordBatchReader` with `read_all()`, which carries the schema when no rows
  return. Parameters are sent as text, because arrow-odbc binds every parameter
  as VARCHAR.
- **`pq()` reads without `union_by_name`**: it wraps `read_parquet` with
  `hive_partitioning = true`, the exact call the spec names. A schema mismatch
  across files fails loudly.
- **Blank config paths mean unset**: `""` in a path field becomes `None`. The
  spec's example config writes `team_components = ""`, which the plan's code
  turned into `Path(".")`.
- **Config rejects unknown keys**: every config model sets `extra="forbid"` and
  models every key in the spec §11 template. A misspelled `kernel_memorry_mb`
  had left the kernel uncapped without a word. Cost: a new key needs its model
  before it can appear in `config.toml`.
- **Config ranges**: `row_cap` must be at least 1, and `kernel_memory_mb` at
  least 0, where 0 means unlimited. A zero `row_cap` returned no rows from every
  query.
- **A `root` key in `config.toml` overrides the root argument**: spec §11 says
  the root can be overridden "with --root or config". Precedence against
  `--root` is an [open question](../open-items.md#open-questions). Cost: setting
  the key redirects every root-relative resource.

## Shared-machine safety

- **DuckDB spills to a private directory**: the client creates a 0700 temp
  directory per kernel, passes it as `--temp-dir`, and removes it on close.
  DuckDB's default `.tmp` under the server's working directory wrote researcher
  data with umask permissions.
- **DuckDB memory follows the kernel cap**: with `kernel_memory_mb` set,
  DuckDB's `memory_limit` is 70% of it. DuckDB's default of 80% of RAM ignores
  `RLIMIT_AS`, so DuckDB would fail past the cap instead of spilling. Cost: 70%
  is an unmeasured heuristic.
- **The memory cap is skipped where the OS refuses it**: macOS rejects
  `RLIMIT_AS`, so the kernel writes a warning to stderr and runs uncapped.
  Target machines run Linux, where the cap applies.
- **The kernel dies with its server**: on socket EOF the kernel flushes and
  calls `os._exit(0)`, even mid-step. An orphaned kernel can hold tens of GB,
  and nobody is left to receive the step's result.
- **Shutdown is prompt and final**: `shutdown` answers, interrupts a running
  step, refuses queued requests with `KernelShutdown`, and ends with
  `os._exit(0)`. A shutdown mid-step had left later calls hung, and a step's
  thread kept a stopped kernel alive.
- **Close kills the whole process group**: `close()` and a startup timeout
  SIGKILL the group the kernel leads, so processes a step started die too. The
  client kills the group in the call that first sees the kernel exit, never
  later, since a reaped pid can be reused. Cost: a child that calls `setsid`
  escapes.
- **Secrets stay out of step code**: `spawn` removes provider API keys from the
  kernel's environment, and the kernel drops `QUARRY_MSSQL_DSN` once config has
  read it. Step code can print its environment into a persisted result.
- **Readable DSN passwords warn**: `load_config` warns when a group- or
  world-readable `config.toml` holds a DSN with `PWD=` or `Password=`. It warns
  rather than refuses, since most DSNs carry no password.

## Server and agent

- **Anthropic request shape**: the adapter calls `client.beta.messages.create`
  with model `claude-opus-5-5`, `max_tokens=16000`,
  `output_config={"effort": "high"}`, the `server-side-fallback-2026-07-01` beta
  and `fallbacks="default"`. It sends no `thinking` parameter and leaves
  `tool_choice` at auto. These come from the Stage 2 plan's global constraints
  and have not yet run against the live API; see
  [open questions](../open-items.md#open-questions).
- **Strict tool schemas**: every tool is `strict` with
  `additionalProperties: false`. Strict mode needs every property required and
  no open nested object, so `initial_state` travels as a JSON string, and `tags`
  and `datasets` are required arrays that may be empty. Spec §8's tool table is
  amended.
- **An empty dataset searches by tags**: `search_components` takes `dataset: ""`
  to skip the schema filter. Strict mode made `dataset` required, which left no
  way to search before a dataset existed.
- **Only written views are transpile-checked**: `render_view` mounts a library
  component without the check, since library components are files a person wrote
  rather than model output. Spec §8 is amended. Cost: a broken library component
  fails only at mount.
- **`write_view` names its datasets**: it takes `datasets` as `render_view`
  does, so a written view records the datasets it reads. Spec §8 is amended.
- **A prompt step's code is the blocks that ran**: `Step.code` joins only the
  `run_python` calls that succeeded, read as spec §5's "the final Python that
  ran". The plan joined every call, so replaying a step in which the model had
  fixed an error reran the error. Failed attempts stay in the transcript. Cost:
  a replayed block can depend on a failed block's partial side effects.
- **Replay skips only failed manual steps**: restart reruns each manual step
  that ended `ok` and every prompt step with code, whatever its status. A prompt
  step that ended in error still holds blocks that ran, and skipping it broke
  the steps after it: a probe's replay stopped at step 1 with
  `NameError: name 'df' is not defined`. A failed manual step would only stop
  the replay where the researcher already saw it fail. Spec §6 is amended.
- **Replay reports instead of raising**: replay stops at the first failing step
  and returns a `ReplayReport` naming it, and a kernel that dies mid-replay
  counts as that step failing. `/restart` answers 503 only when the new kernel
  cannot start.
- **Prompt-step lineage is a fold**: `step_lineage` combines the `ExecResult` of
  each `run_python` call. Reads are names a call read before an earlier call in
  the step wrote them, writes and defines are unions, and each dataset's
  metadata comes from the last call that wrote it. A call that reads and rebinds
  a name keeps its read.
- **Stop reasons**: Anthropic's `model_context_window_exceeded` and OpenAI's
  `length` end the step as `max_tokens`, and OpenAI's `content_filter` as a
  refusal. The OpenAI adapter checks for truncation before it parses tool
  arguments. A truncated call had raised `JSONDecodeError` out of the loop, and
  a filtered reply had ended the step as `ok`.
- **Each step thread has one boundary**: the prompt and manual step threads turn
  any `Exception` into a failed step, and the session is freed even when saving
  the step or starting the thread fails. An escaped exception had left the
  session answering 409 for good.
- **One step or replay at a time**: a step posted while another step or a replay
  runs gets 409, and so does a restart while a step runs. Cost: a hung step can
  be escaped only by killing the kernel; see
  [open questions](../open-items.md#open-questions).
- **HTTP errors**: an invalid query spec is 400 rather than FastAPI's 422,
  because the route validates the body itself. A kernel that fails to start
  during `/query`, `/datasets` or `/restart` is 503.
- **Reads respawn a dead kernel**: `/query`, `/datasets` and `/interrupt` start
  a kernel when the session has none or it died. Its namespace is empty, as
  after a server restart, until `/restart` replays the steps.
- **Session reads take the service lock**: `get` reads the step files and the
  running step under the lock that saving a step holds. Unlocked reads tore in
  56 of 1000 tries in a probe, and `/status` returned 500 once in 400 polls
  through `TestClient`. Cost: every poll parses every step file under that lock.
- **Only health and the UI are open**: `GET /healthz`, `GET /` and the static
  files need no token, since a browser loading the page cannot send it. Spec §12
  is amended. The OpenAPI schema and docs pages are off, since `/openapi.json`
  had listed every route without a token. Tokens are compared as bytes, because
  `compare_digest` raises on a non-ASCII `str`.
- **Session files**: a step is saved once, when it finishes, as 0-based
  `steps/NNNN.json` through a temp file and `Path.replace`. Transcripts hold
  provider-neutral `Message`s.
- **The summary budget is a code default**: `build_summary` collapses steps
  older than the last eight once the summary passes 24,000 estimated tokens,
  with no config key. Spec §8 is amended.
- **A broken component manifest is skipped**: the library logs a warning and
  loads the rest. One bad manifest had made every component search fail.

## Packaging and CI

- **Built for polars 2 and DuckDB 1.5**: polars 2.0.0 and DuckDB 1.5.6 resolved
  under the plan's `>=` pins, so the code is adapted to their APIs. The plan was
  written against polars 1.x.
- **Floors match what was probed**: runtime pins are `polars>=2.0,<3` and
  `duckdb>=1.5,<2`, and the pydantic floor is the oldest release with every API
  the code uses. The `mssql` extra needs `arrow-odbc>=10`, the only version
  whose call signature was checked. Cost: old environments hit conflicts at
  install time rather than wrong results.
- **`anthropic>=1.12`**: the beta request arguments `output_config` and
  `fallbacks` were checked only on 1.12.1, so the floor is that release line.
- **CI installs from the lock**: CI runs `uv sync --locked`, so a stale
  `uv.lock` fails instead of re-resolving.
- **Local Python matches CI**: `.python-version` pins 3.11. The local venv had
  resolved 3.14, so failures specific to 3.11 surfaced only in CI.
- **Tests are annotated**: ruff's ANN rules apply to tests as well as `src`,
  where the plan had a per-file ignore.
