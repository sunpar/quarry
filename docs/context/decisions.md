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
  and `pl.from_arrow` both fail: given `relation_projection`, the importable
  projection the kernel reads the relation through, relation source starts from
  `rel.project(...)`, so INTERVAL and UNION columns arrive as text, as views see
  them.
- **Generated identifiers are ASCII**: `to_source` takes a dataset or result
  name only when it is `[A-Za-z_][A-Za-z0-9_]*` and not a keyword. Python folds
  identifiers to NFKC when it parses them, so `ｔrades` passed `isidentifier()`
  and ran as `trades`; the ASCII rule makes an NFKC check unnecessary.
- **`to_source` raises only `QueryError`**: a bad identifier, a clashing name
  and a literal the column's dtype cannot take all raise `QueryError`, and a
  filter literal's error names the column and the value. They had raised
  `ValueError` or `TypeError`, which callers did not expect.
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
- **Two client failure types**: every client failure is `KernelDead` or
  `RpcFailure`. An `OSError` while starting, from the temp directory, the socket
  or `Popen`, is `KernelDead`, and `spawn` kills the kernel and frees what it
  made on any exception, Ctrl-C included. A result that fails validation is an
  `RpcFailure` of type `InvalidResult`. Cost: `/query` maps `RpcFailure` to 400,
  so a kernel bug there reads as a bad request.
- **`close()` never raises**: it SIGKILLs the group, waits 5 s, and leaves a
  kernel that outlives that to the OS with one stderr line. It removes the temp
  directory with `ignore_cleanup_errors`, since a child outside the group can
  keep writing into it. Cost: such a kernel stays unreaped, and such a directory
  stays on disk, silently.
- **Dataset metadata lasts until the next step**: `execute` caches the metadata
  of its writes, and `list_datasets` reuses it and caches what it describes.
  Every `execute` clears the cache first, since a step can change a dataset
  without naming it, through a helper, an alias or `globals()`. The server lists
  datasets on every prompt step, view mount and `/datasets` request, and
  previews run plans. `describe` still counts rows and ignores the cache. Cost:
  a source changed outside a step, such as a rewritten parquet file under a
  LazyFrame, shows a stale preview until the next step.
- **Malformed lines never kill a reader**: the kernel answers an undecodable
  request with an `RpcError` when it can recover an integer id, and otherwise
  logs it to stderr. The client treats an undecodable response as a dead kernel.
  A dead reader thread had hung every pending call forever.
- **Kernel output is inherited, not piped**: the kernel writes to the server's
  stdout and stderr. C-level output from user code goes to those file
  descriptors, and an undrained pipe would block the kernel once full.
- **"To code" renders in the kernel**: the `to_code` RPC renders each spec with
  `to_source` against its dataset's live schema, so literals coerce as
  `to_polars` coerces them, and a relation through its importable projection.
  Each result is `<dataset>_<n>`, n being the spec's position, with the suffix
  raised past every name the namespace binds, every spec's dataset and the names
  chosen before it, because the output runs as a step and the plan's bare names
  overwrote a researcher's `df_1`. A generated import (`date`, `datetime`,
  `ZoneInfo`) that would rebind a dataset anywhere in the joined code is a
  `QueryError`, since the import binds the name for every later block. Cost: a
  `df_1_2` style name when `df_1` is taken, and a 400 for datasets with those
  names.

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
- **`POST /interrupt` reports whether it stopped something**: it cancels a
  running prompt step, then interrupts the kernel, and answers
  `{"ok": delivered or cancelled}`, so a client knows when to retry. The plan's
  `{"ok": true}` hid an interrupt that hit nothing. The cancel comes first, so
  it holds even when a dead kernel makes the route answer 503.
- **Steps take a cancel**: `run_agent_step` checks a cancel event before each
  provider call, when the model answers, and before each tool call, and ends the
  step `interrupted`, even on the last turn the 12-call cap allows. A step
  waiting on the model takes no kernel interrupt. Cost: the provider call in
  flight still runs to completion.

## Lineage

- **Module level only**: function, lambda and comprehension scopes contribute
  only their free names as reads, never stores, and a `del` of a plain name is
  neither. A false write of a common name like `df` would put wrong steps into
  saved recipes.
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
- **SQL string literals are parsed for table names**: a string literal passed
  first to `sql_local(...)` or any `.sql(...)` goes through DuckDB's
  `json_serialize_sql`, and each base table it names that was a dataset before
  the step is a read. The parser binds nothing and reads no files. Binding with
  `get_table_names` failed on any `JOIN ... USING`, `ASOF JOIN` or `UNPIVOT`
  over tables it could not see, losing every read in the literal, and it globbed
  parquet and sniffed CSVs after the step (probed). A literal that does not
  parse silently adds no reads. Cost: a literal that is not SELECT statements
  (PIVOT, CREATE TABLE AS) adds no reads, a CTE that shares a dataset's name
  counts as a read of it, and SQL built at run time (an f-string, a variable) is
  not read.
- **In-place assignment stores its root name**: at module level, assigning to or
  deleting an attribute or subscript (`df.columns = ...`, `df["k"] = ...`,
  `del df["k"]`, also as an unpacking, `for` or `with` target) stores the name
  the chain starts from, so the step writes that dataset. Outside module scope
  it is only a read of the name. Cost: a bare annotation such as `df.x: int`,
  which assigns nothing, also counts as a store.

## Datasets and JSON

- **Decimals are exact strings**: JSON rows carry Decimal values, nested ones
  too, as decimal strings such as `"900"`, so every sum over integers of up to
  64 bits arrives as a string. A 128-bit sum keeps its integer type and arrives
  as a number. Float64 would silently change `Decimal("9007199254740993")` while
  the schema still said Decimal. The arrow format casts them to Float64.
- **Non-finite floats are null**: inf, -inf and NaN become JSON null at any
  depth, which keeps each column's JSON type uniform. The arrow format keeps
  them, and the Stage 3 renderer may choose sentinels.
- **JSON rows never panic**: Binary becomes base64, Object becomes `str`, naive
  datetimes get an ISO `T`, and dates outside chrono's range become null. polars
  `write_json` panicked on Binary and on DuckDB's `'infinity'`, a common
  end-of-validity marker.
- **Arrow is a display transport**: `format: "arrow"` answers with an Arrow IPC
  stream, not a file, written at `CompatLevel.oldest()` after `for_viewer` casts
  each column to a type Perspective's reader takes: primitives, `string`,
  `date32`, `timestamp` and `bool`. Decimal and 128-bit integers become Float64,
  since pyarrow cannot read polars' Int128; Categorical, Enum and Time become
  strings, Duration polars' own text such as `1d 2h`, Binary base64 and nested
  values JSON strings; and `large_string` is narrowed to `string`. Cost:
  decimals and large integers can lose precision in Arrow, so JSON rows stay the
  exact form.
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
- **`loaders.toml` never stops the kernel**: an unreadable file, a syntax error,
  a malformed or duplicate entry, a non-identifier name or a failed import each
  becomes a `LoaderFailure`, and the rest still bind. A loader raising
  `SystemExit` at import counts as failed, while `KeyboardInterrupt` propagates.
  One typo had killed every kernel.
- **A slow loader import is named, not stopped**: an import still running after
  10 s prints a notice naming the loader to stderr, and the import goes on.
  Cost: a loader that hangs still hangs the server at startup.
- **A missing `mssql` extra says so**: `sql()` without `arrow_odbc` raises
  `ModuleNotFoundError` with the install command. Any other missing module
  re-raises unchanged.
- **An unreadable cache path is skipped**: `scan_layout` never raises. It drops
  an unreadable root or dataset, lists a directory holding parquet files
  directly as `not partitioned`, and reads only the dataset directory and its
  first-level partitions, taking the second key from the first readable one. An
  unreadable cache had stopped `quarry serve`. Cost: an unreadable cache looks
  empty to the agent, with no log line.
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
- **Config errors never echo input**: every config model sets
  `hide_input_in_errors`, and `mssql_dsn` and the license keys stay out of
  reprs. A misspelled DSN key had printed its password at startup. Cost:
  validation errors omit the offending value, and `ValidationError.errors()`
  still includes it, so code that shows those errors must pass
  `include_input=False`.
- **Config ranges**: `row_cap` must be at least 1, and `kernel_memory_mb` and
  `kernel_threads` at least 0, where 0 means no limit. A zero `row_cap` returned
  no rows from every query.
- **Only `--root` sets the root**: a `root` key in `config.toml` is a
  `ConfigError`. The key lives inside the root it would override, and it
  silently redirected every root-relative resource. Spec §11 is amended. Cost: a
  config that set `root` fails at startup.
- **Config paths are absolute**: a `QuarryConfig` validator makes the root
  absolute, expands `~` in every path field and resolves a relative one against
  the root, so the server and kernels agree whatever their working directories.
  An unknown `~user` is a `ConfigError`. Cost: a new `Path` field is anchored at
  the root automatically.
- **The API key file is read once**: `api_key` checks the permissions of the
  open file with `fstat` and reads that same file, and every failure is a
  `ConfigError`. A non-UTF-8 key file's error leaves out the decode message,
  which quotes a byte of the key.

## Shared-machine safety

- **DuckDB spills to a private directory**: the client creates a 0700 temp
  directory per kernel, passes it as `--temp-dir`, and removes it on close.
  DuckDB's default `.tmp` under the server's working directory wrote researcher
  data with umask permissions.
- **The memory cap is `RLIMIT_DATA`**: `kernel_memory_mb` caps the kernel's data
  segment. `RLIMIT_AS` counted mmapped parquet, thread stacks and malloc arenas,
  so a cap near the working set broke polars and DuckDB in confusing ways. Cost:
  Linux still counts thread stacks against it, so a 256 MB cap killed a kernel
  on 14 cores at polars start, while `kernel_threads = 2` survived.
- **DuckDB memory follows the kernel cap**: with `kernel_memory_mb` set,
  DuckDB's `memory_limit` is 70% of it. DuckDB's default of 80% of RAM ignores
  the rlimit, so DuckDB would fail past the cap instead of spilling. Cost: 70%
  is an unmeasured heuristic.
- **The memory cap is skipped where the OS refuses it**: macOS rejects
  `RLIMIT_DATA`, so the kernel writes a warning to stderr and runs uncapped.
  Target machines run Linux, where the cap applies.
- **Threads per kernel are opt-in**: `data.kernel_threads`, 0 by default for
  every core, caps polars and DuckDB. `KernelClient.spawn` sets
  `POLARS_MAX_THREADS`, because polars reads it at import, before the kernel
  reads its config, and the kernel runs `SET threads` from its own config. The
  scratch kernel that validates a recipe takes the same cap. Cost: two processes
  read the one value, and a kernel started outside the client caps DuckDB only.
- **The kernel dies with its server**: on socket EOF the kernel flushes and
  calls `os._exit(0)`, even mid-step. An orphaned kernel can hold tens of GB,
  and nobody is left to receive the step's result.
- **Shutdown is prompt and final**: `shutdown` answers, stops the executor,
  interrupts a running step, refuses queued requests with `KernelShutdown`, and
  ends with `os._exit(0)`. A stopped executor ends any step or describe of a
  write that starts after the stop, which a request already taken but not yet
  running had escaped. A shutdown mid-step had left later calls hung, and a
  step's thread kept a stopped kernel alive.
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
  and `fallbacks="default"`. It sends no `thinking` parameter, leaves
  `tool_choice` at auto, and omits `tools` when the list is empty, as the recipe
  tidy call's is. These come from the Stage 2 plan's global constraints and have
  not yet run against the live API; see
  [open questions](../open-items.md#open-questions).
- **Strict tool schemas**: every tool is `strict` with
  `additionalProperties: false`. Strict mode needs every property required and
  no open nested object, so `initial_state` travels as a JSON string, and `tags`
  and `datasets` are required arrays that may be empty. Spec §8's tool table is
  amended.
- **An empty dataset searches by tags**: `search_components` takes `dataset: ""`
  to skip the schema filter. Strict mode made `dataset` required, which left no
  way to search before a dataset existed.
- **`write_view` names its datasets**: it takes `datasets` as `render_view`
  does, so a written view records the datasets it reads. Spec §8 is amended.
- **A prompt step's code is the blocks that ran**: `Step.code` joins only the
  `run_python` calls that succeeded, read as spec §5's "the final Python that
  ran". It is for reading; replay uses `runs`. The output tails join every run's
  tails, keeping the last 4096 characters.
- **Replay reruns every execution**: each step keeps `runs`, one
  `{code, status}` per execution: every `run_python` call of a prompt step, or a
  manual step's code. Restart reruns them one by one, so a failed run's partial
  effects come back. `df = ...; 1 / 0` leaves `df` behind for a later repair to
  use, and replaying only the repair failed with `NameError`. Separate runs also
  keep a later `from __future__` import valid. A run that failed may fail again,
  and an interrupted run is skipped. Spec §5 and §6 are amended. Cost: a run
  that failed before and succeeds now leaves state the session never had.
- **Replay reports instead of raising**: replay stops at the first run that was
  `ok` and now is not, that is interrupted whatever it saved, or that kills the
  kernel, and returns a `ReplayReport` naming its step. `/restart` answers 503
  only when the new kernel cannot start.
- **Each prompt step records its model**: a prompt step saves the provider and
  model it called, since `config.toml` can change between a session's steps
  while the session keeps the provider it began with. The maintainer chose this
  over using the session's provider or refusing a mismatch. Spec §5 is amended.
- **The server stamps `origin_step`**: the kernel has no step ids, so a finished
  step's datasets carry its id, and `/datasets` takes each name's latest writer
  from the saved steps, or null when no step wrote it. The kernel takes no
  session id, and spec §5 and §6 are amended. Cost: until a step is saved, its
  datasets carry null in the agent's tools and summary, and `/datasets` names
  the previous writer or null.
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
  any `BaseException` into a failed step, since a polars panic or a
  `KeyboardInterrupt` raised by firm code is not an `Exception`. The session is
  freed even when saving the step or starting the thread fails. An escaped
  exception had left the session answering 409 for good. A crashed prompt step
  keeps the runs recorded before the crash and their lineage, so restart replays
  them and `/datasets` credits the step.
- **A step that fails to save kills the kernel**: the kernel ran code the
  session's files lack, so it stays dead until a restart rebuilds it from them.
  Later steps had built on state that no restart could bring back. Cost: the
  unsaved step's work is lost.
- **One step, restart or save at a time**: a step posted while another step, a
  restart or a save runs gets 409, and so does a restart during a save or
  another restart. `/query`, `/datasets` and `/interrupt` get 409 during a
  restart too, since a half-replayed namespace is not the session's. The kernel
  manager also refuses the kernel while the replay runs, so a read that passed
  the check just before the restart never gets a half-replayed kernel. Holding
  the service lock across the lookup would have done the same, but a lookup can
  start a kernel, which stalls every session.
- **A save holds the idle kernel**: `SessionService.hold` lends a session's
  kernel to a project save or a view recall's dataset check. It raises
  `SessionBusy` at once while a step, a restart or another hold runs, and
  reports the kernel `running` until it ends. `hold`, `_begin` and `restart`
  share one `_busy` check, but `restart` lets a running step through to cancel
  it. The plan's version refused a running step, which would have undone Stage
  2's restart that stops one. Cost if wrong: a restart clicked during the
  seconds a save holds the kernel answers 409 and must be retried.
- **The prompt locks while the server holds the session**: the prompt box is
  disabled while a step this page knows is running, and also when
  `SessionStatus.busy` is true and `running_step` is not one of the page's
  steps. That covers a save hold and a restart, which report
  `running_step: None` (`running_step` comes only from steps begun by `_begin`;
  `restart` waits for them to end before it replays, and `hold` touches only
  `_holds`), and a step started from another tab or the CLI. Plain `busy` was
  the plan's rule, but the server also reports `busy` while a step runs, and the
  status poll slows from 750 ms to 5 s once the page sees its step end, so its
  last answer, taken while the step ran, locked the prompt for up to 5 s after
  many steps.
- **Recall is a manual step**: `start_recall` creates a `recall` step, carrying
  the saved view for a view recall, and runs it on the manual-step path, so
  `runs` is filled, lineage records the writes and restart replays it. `_begin`
  takes the view; the plan's calls used signatures the Stage 2 service lacks.
- **Shutdown stops and saves running steps**: it cancels every running step,
  closes the kernels, refuses to start new ones, and waits up to 10 s for the
  steps to save as `interrupted`. A step running at shutdown was never saved
  before. Cost: a step still waiting on the model after 10 s is lost, as in a
  crash.
- **Restart stops a running step**: `/restart` while a step runs cancels it,
  kills the kernel's process group, waits for the step to save itself, then
  replays. The step ends `interrupted` with the error "stopped by a restart" and
  keeps the runs that finished. Some code takes no interrupt, such as a long
  polars `collect()`, and the researcher chose restart as the way to always get
  control back. Cost: a step waiting on the model holds `/restart` until the
  provider answers, and under uvicorn that also delays a graceful Ctrl-C.
- **Transpile checks time out**: `CommandTranspiler` gives up after 30 s and
  reports a transpile error to the model, and the step goes on. A hung check
  would otherwise hold the step, and a restart waiting on it.
- **The repair rule is checked after each call**: the second failed `run_python`
  call in a row ends the step at once, even mid-turn, so later calls in the same
  turn never run. Their tool results are left out of the transcript, which no
  provider sees again.
- **HTTP errors**: an invalid query spec is 400 rather than FastAPI's 422,
  because the route validates the body itself. A dead kernel, or one that fails
  to start, is 503 from `/query`, `/datasets`, `/interrupt` and `/restart`.
- **A dead kernel stays dead until restart**: reads answer 503 and new steps
  fail at once, so `/status` keeps reporting `dead` and the client can offer
  restart and replay, as spec §13 says. Starting an empty kernel instead had
  turned the status back to `idle` and made later queries fail on missing
  datasets. A session with no kernel yet, as after a server restart, starts one
  on first use. A restart whose new kernel fails to start keeps the old, closed
  kernel, so the session stays dead rather than getting an empty kernel that
  skipped the replay.
- **Component search skips the row count**: `search_components` takes its
  dataset's schema from `list_datasets`, which never counts rows, since matching
  needs only the schema. `describe` counts, which runs a lazy plan or scans a
  relation in full. `describe_dataset` still counts.
- **Failed loaders are reported**: the server logs each loader that failed to
  load and lists them in the system prompt, so the agent can say why a
  configured loader is missing.
- **Each prompt step builds the system prompt**: the loaders and the cache can
  change while the server runs. One prompt built at server start had told later
  sessions about loaders their kernels did not have, and left out ones they did.
  Cost: an edit to `loaders.toml` reaches the prompt at once but a running
  kernel only at its next restart.
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
  `steps/NNNN.json`, and read back in index order, since `10000.json` sorts
  before `1001.json` by name. Files are UTF-8 whatever the locale. Transcripts
  hold provider-neutral `Message`s.
- **Session files are private and durable**: `quarry serve` creates a missing
  root 0700, and the store creates `sessions/`, each session and its
  `steps/` 0700. The store writes every file 0600 to a temp file, fsyncs it,
  moves it into place with `Path.replace`, and fsyncs its directory. Creating a
  session also fsyncs `sessions/` and the root, which gained its entries. Other
  researchers on the machine could read prompts and code, and a crash could lose
  a finished step. Cost: an existing root keeps its mode, macOS `fsync` does not
  flush the drive cache, and a filesystem that refuses a directory fsync fails
  the save after the file is already in place.
- **The summary budget is a code default**: `build_summary` collapses steps
  older than the last eight once the summary passes 24,000 estimated tokens,
  with no config key. Spec §8 is amended.
- **Datasets come first in the summary budget**: the dataset list counts against
  the 24,000 tokens before any step does, since the agent needs it to write
  code. If the list alone passes the budget, each dataset keeps only its column
  count, and `describe_dataset` gives the columns. Wide datasets had pushed the
  summary far past the budget.
- **A broken component manifest is skipped**: an unreadable, malformed or
  invalid manifest gets a logged warning, and the library loads the rest. One
  bad manifest had made every component search fail. A manifest whose
  `contract_version` is not 1 is skipped too, since 1 is the only contract the
  runtime mounts, and so is one with a key the spec does not list: a misspelled
  key had fallen back to its default. A schema requirement's `min` must be at
  least 1, since 0 matched datasets without the column.
- **Each component role needs its own columns**: a dataset fits a component when
  it has enough columns of each dtype for all its typed roles together, and
  enough left over for its `any` roles. Each requirement had been checked alone,
  so one numeric column met both an `x` and a `y` role.
- **A saved component gets a folder of its own**: `POST /components` creates
  `<root>/components/<id>/` exclusively, 0700, and answers 409 when a folder of
  that name exists. The library skips a folder whose manifest is invalid and
  lists one whose manifest names another id under that id, so the check against
  the library alone had let a save replace files a researcher wrote. It writes
  `component.tsx`, then `manifest.json`: the library lists a component only once
  both exist, so a crash between them leaves nothing listed. Cost: that crash,
  or any failed write after the folder exists, leaves a folder that refuses the
  id until it is removed. The id pattern ends in `\Z`, not the plan's `$`, which
  in Python also matches before a trailing newline.
- **Licensed library status lives in `quarry/libraries.py`**: `LibraryStatus`
  and `licensed_libraries` import only the config and pydantic, because
  `enabled_libraries` in `quarry.agent` needs them and `quarry.server` already
  imports `quarry.agent`. The plan put them in `quarry.server.libraries`.
  `create_app` computes the statuses once: it mounts each enabled library at
  `/libs/<id>`, serves the same list from `GET /libraries`, and logs one warning
  for each library with a key but no usable install, naming the setting, never
  the key. The plan logged inside the status check, which warned twice at
  startup and again on every request. Cost: an install added after startup needs
  a restart. The mount serves every file under `*_path` to any origin, so the
  path must be the library's package folder itself, never a broad folder such as
  `~` or `~/Downloads`; there is no guard in code.
- **Licensed libraries come from the researcher's install, key and all**:
  Highcharts and SciChart are never bundled or listed in `web/package.json`; the
  server serves the installed package under `/libs/<id>/` once both its key and
  its path are set and the entry file exists. An enabled status carries the key
  to the host through `GET /libraries`, behind the bearer token, and the host
  passes SciChart's into the frame's `mount`, since SciChart takes it at load
  time. The key is never logged, and `LibraryStatus` leaves it out of its
  `repr`. Cost: whoever holds the server's token can read both keys.
- **The library guide follows the installed packages**: every import a section
  names resolves through the runtime's module table, checked against the
  installed exports. TanStack Table v9 sorts only with `createSortedRowModel`
  beside `rowSortingFeature`, and core rows render over `row.getAllCells()`, so
  the guide says both; the plan named the feature alone. The current guide's
  lightweight-charts `addSeries` and ag-grid `registerModules` sentences stay.

## First UI

- **Web build lives in the wheel as an artifact**: `[tool.hatch.build]` lists
  `artifacts = ["src/quarry/static/**"]`, at the build level rather than the
  wheel target, because `uv build` makes the wheel from the sdist and the
  gitignored static files were dropped otherwise. The web build must run before
  `uv build`; CI does.
- **Static assets answer with `Access-Control-Allow-Origin: *`**: the view
  iframe is `sandbox="allow-scripts"`, so its origin is opaque and Chromium
  fetches its module scripts, CSS and fonts in CORS mode. Only the static mount
  is wrapped in `CORSMiddleware`; API routes send no CORS header and the sandbox
  and CSP stay as the plan set them. The plan's loopback CSP fallback was not
  needed: no CSP violation was logged. Approved by the maintainer. This already
  meets the plan's later Step 2b, which names `/assets/`, `/runtime.html` and
  `/libs/`: the mount-level wrapper covers those and every other static file, so
  no second middleware is needed.
- **The frame may fetch from the Quarry server, and only there**: the runtime
  CSP is
  `default-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; worker-src blob:; style-src 'self' 'unsafe-inline'; img-src data: blob:; font-src 'self'; connect-src 'self'`,
  since Perspective fetches its wasm and starts its engine from a Blob URL.
  `'self'` is the server's origin. That opens nothing the bridge did not already
  mediate: every API route needs the bearer token, which the frame never holds,
  and API routes send no CORS header, so the opaque-origin frame can neither
  authenticate nor read an answer. What it can read, the static files and
  `/libs/`, is open to any page anyway. Spec §9 and §12 carry the amendment.
- **The host page frames only its own origin**: the sandbox blocks forms, popups
  and top navigation, but not `location.href = ...` inside the frame, which no
  directive of the frame's own CSP covers. `web/index.html` therefore sets
  `frame-src 'self'`, which Chromium checks on every navigation of the view
  frame, the frame's own included, so a view cannot carry rows out in another
  site's URL, and the next `mount`, which `HostBridge` must post to `"*"` since
  the frame's origin is opaque, reaches only a Quarry page. A Playwright test
  pins the refusal. The bridge being the only path to data (spec §12) is still
  defence in depth, not a guarantee: WebRTC and DNS prefetch stay
  [open](../open-items.md#known-problems), and the kernel already has the
  network.
- **The token stays in the URL fragment and in memory**: the host reads
  `#token=` once into state, never stores it, and writes the active session id
  back as `#token=...&session=...` with `replaceState` so a reload keeps both. A
  `hashchange` whose token differs reloads the page, since re-pasting a link
  from a restarted server is a same-document change.
- **`replay_needed` on kernel status**: `KernelManager.get` records a session
  whose kernel it spawned while the session already had steps, and `restart`
  clears it only once a replay runs through; `status` reports it from the
  persisted steps before the kernel starts, and `restart` sets it for any
  session with steps. A session reopened after a server restart gets an empty
  kernel on its first read and never offered "Restart kernel". The banner shows
  on `dead` or `replay_needed` and reports a replay that stopped early; the
  prompt stays enabled, since a fresh kernel is sometimes what the researcher
  wants.
- **The host checks every field of a frame message**: generated code can call
  `parent.postMessage` itself, so `isRuntimeMessage` validates each message's
  fields and types, not only `type`. A malformed `error` can no longer put an
  object into host React state and take down the UI.
- **Node is a soft prerequisite**: the server checks generated TSX with `node`.
  Without it, startup logs a warning and the check is skipped; the browser still
  reports a broken view and "Fix this view" repairs it. Shipping a Node runtime
  in the wheel was judged too heavy for that fallback.
- **The server owns row order**: the data table pushes its sort into the query
  spec and gives every grid column a comparator that returns 0, so AG Grid keeps
  the server's order instead of comparing Decimal strings as text.
- **A dead kernel locks the prompt**: the server keeps a dead kernel dead until
  restart, so a prompt would only add a failed step. `replay_needed` alone
  leaves the prompt open.
- **Snapshots record the queries a view holds**: each mounted `useQuery` hook
  holds its spec, counted per spec, from a layout effect until it unmounts or
  its spec changes, and a snapshot carries the held specs. When they differ from
  the last report, the runtime schedules the same debounced report a state
  change does, so a view reports its queries on mount and again when a late
  schema replaces a placeholder. Stage 3 recorded every spec a render asked for
  and Stage 5 flushed once 300 ms after mount, so a placeholder such as
  `{dataset, limit: 1}` reached "To code" beside the real query, or alone when
  the schema came later. A restored state's queries are not reported, since that
  state is a snapshot already on record and a report would append a copy and fan
  `shared:` keys out again, and a replaced view reports nothing as its hooks let
  go. Schemas come from the live kernel, as queries do, not from the step that
  wrote the dataset.
- **Mounted views refetch when kernel data may change**: the host sends
  `refresh` when a step finishes or the kernel's pid changes. The view's cache
  marks every answer stale and keeps showing it until the refetch lands, so a
  long-lived view follows a rebound dataset without flashing to "Loading". Each
  request carries a ticket, and only the newest per key may write, so an answer
  from before the refresh cannot overwrite one from after. A saved sort on a
  column the live schema lacks is dropped from the query.
- **Views may ask for Arrow**: `useQuery` with `format: "arrow"` returns the IPC
  stream bytes as an `ArrayBuffer` in `arrow`, with `rows` empty, for
  Perspective.
- **Perspective's engine is a classic Blob worker**: Chromium refuses a module
  worker from a `blob:` URL in the opaque-origin frame, and a worker served from
  `/assets/` throws a `SecurityError` there, so the plan's bundled-worker
  fallback cannot work. `ensureEngine` starts Perspective's own worker script as
  a classic worker from a Blob URL, which `worker-src blob:` admits; the CSP is
  the planned one.
- **The frame's `load` event is the mount fallback**: the runtime posts `ready`
  once while loading, which can beat the host's listener;
  `HostBridge.frameLoaded` sends the queued mount if `ready` was missed. The
  `onLoad` handler is wired on the iframe element itself and remembered, so a
  frame that loaded before the bridge existed mounts as soon as the effect runs.
  A `ready` that arrives after `load` mounts a second time, which the runtime
  tolerates; the double mount is a
  [known problem](../open-items.md#known-problems).
- **A repair step keeps the researcher's prompt**: the view source and browser
  error go only to the agent; the persisted step shows "Fix the view so it
  mounts." The plan stored the composed text as the step prompt, which put a
  wall of TSX in the step column.
- **`row_count` is the number of rows returned**: `truncated` compares with
  `row_cap`, not the spec's `limit`, so the built-in table shows "Showing the
  first N rows." whenever a page is full. AG Grid's client-side filters are off,
  since a filter over one page gives wrong answers; filters belong in the query
  spec (spec §9).
- **Loader keeps unused imports**: Sucrase runs with `keepUnusedImports`, so a
  refused module is refused even when nothing uses it. A type-only value import
  of a non-allowlisted path is refused too. The allowlist is checked with
  `Object.hasOwn`, so `import x from "constructor"` is refused like any other.
- **Mount is queued and resent**: the host sends `mount` only after the runtime
  posts `ready`, keeps the spec and resends it on every later `ready`; the
  runtime drops a mount that an even newer mount has overtaken. A reloaded frame
  therefore remounts, and a slow first load cannot clobber a second.
- **The time series drops what it cannot plot**: rows whose time does not parse
  or whose value is not finite are skipped, equal seconds collapse to the last
  row, and a naive ISO datetime is read as UTC because the kernel's DuckDB
  session is UTC. Lightweight Charts throws on NaN or repeated times.
- **The runtime manifest gates the guide**: the web build writes
  `runtime-manifest.json` naming the libraries the bundle resolves (`ag-grid`,
  `lightweight-charts`), and `enabled_libraries` intersects with it. A corrupt
  manifest fails startup loudly, since the build writes it.
- **Built-ins live outside `web/`**:
  `src/quarry/components/builtin/*/component.tsx` resolve `react`, `ag-grid-*`,
  `lightweight-charts`, `@tanstack/react-table`, `recharts` and
  `echarts-for-react` through a regex alias to `web/node_modules` in the vite
  and vitest configs and through `paths` in `tsconfig.app.json`, and the
  prettier scripts include that directory. `react-plotly.js` has an exact alias
  of its own, since the app imports `react-plotly.js/factory` through the
  package's exports map, which a path alias would bypass. Its `paths` entry
  takes the package's own v4 types; `plotly.js` maps to `@types/plotly.js`,
  because the npm override puts `plotly.js-dist-min`, which has no types, at
  `node_modules/plotly.js`.
- **TypeScript config departures**: `erasableSyntaxOnly` is off because the
  plan's classes use constructor parameter properties, and `baseUrl` is dropped
  because TypeScript 6 rejects it (TS5101); `paths` resolve relative to the
  tsconfig.
- **One `FakeProvider` per e2e server**: the service calls the provider factory
  on every step, so the fixture returns the same scripted instance from the
  factory or the repair step would replay the first turns.
- **Snapshots**: the server keeps the last 500 per view, appends under the
  service lock, and answers 409 while that step is still running.
- **One `ViewHost` for step views and canvas cards**: `ViewHost` owns the
  bridge, the mount, refreshes and hub registration for both. It keys its mount
  on `viewId`, `sessionId` and `contentKey`, a step view's `content_hash` or a
  saved view's `saved_at`, and reads the source, state and datasets through a
  ref. Schemas always come from a fresh `/datasets` fetch. `fill` makes a card's
  frame fill its cell instead of the fixed 420 px, and without `onFix` the error
  overlay has no "Fix this view" button. The plan memoised on `content_hash`,
  which relied on every caller memoising too, and took schemas from an
  `ownDatasets` prop of step metadata, which would have brought stale schemas
  back. Cost if wrong: one extra datasets fetch per schema request.
- **The snapshot scrubber follows the latest**: `SnapshotScrubber` keeps the
  researcher's pick only while the snapshot count it was made at holds, then
  moves to the latest. Each posted snapshot is appended to the cached session,
  so new snapshots reach it during a visit without a refetch. The plan's
  scrubber read the count once, so a view that gained snapshots while mounted
  showed "1 of N". Cost if wrong: the cached list can pass the server's cap of
  500 until the next refetch.
- **The dev proxy forwards `/projects`**: `web/vite.config.ts` proxies it beside
  `/sessions` and `/healthz`. The plan added project routes without it, so
  `npm run dev` answered 404. Stage 5 adds `/components`, `/libraries` and
  `/libs` the same way.
- **Views mount once the libraries answer is in**: `ViewHost` creates its bridge
  only after the first `GET /libraries` answer, success or error, and mounts
  once with the enabled licensed libraries; a failed answer mounts with none. It
  keys on React Query's `isFetched`, which stays true through any refetch, and
  `useLibraries` does not retry. A `ready` sent before then is covered by the
  frame's `load`. The plan mounted at once and remounted on a late answer, which
  would reset the view to its initial state. Cost: the app's first view waits
  for one request. Only SciChart's key goes into the frame, since Highcharts
  reads none at runtime.
- **Licensed loaders forget a failure**: `loadHighstock` and `loadScichart`
  cache their promise, but clear it when the load fails, so the next view that
  imports the library tries again instead of seeing the cached error.
  `loadHighstock` also removes the failed `<script>`, so retries leave one tag.

## Projects

- **The tidied recipe is validated first, the raw one in its place**: a save
  validates the tidied script, and when the tidy fails, is unavailable or does
  not reproduce the dataset, validates `recipe.raw.py` instead. `recipe.py` is
  whichever validated, and the save is unvalidated only when neither reproduces
  the dataset. A bad tidy must not mark a correct raw recipe unvalidated. The
  plan's test expected a rejected tidy to leave the save unvalidated, and spec
  §10 and §13 are amended. Cost if wrong: a researcher never learns a tidy was
  rejected when the raw recipe validated, since no `validation_error` is kept.
- **A save never needs a provider**: building the provider is part of the tidy
  attempt, so a `ConfigError` such as a missing API key means no tidy, and the
  raw recipe is validated. In the plan that error failed the whole save, after a
  pinned parquet was already written.
- **Validation compares two describes**: the scratch kernel's `describe(name)`
  must match the session kernel's, taken at save time, in column names and
  dtypes, in order, and in row count. `step.datasets` is never used, since its
  `rows` can be null. Cost: `describe` counts rows, so a save runs a lazy plan
  or scans a relation once in each kernel.
- **Recipes take only `ok` runs**: `raw_recipe` joins each lineage step's runs
  that finished `ok`, so a failed run's in-place mutation never enters a recipe,
  while an earlier successful run's does. A recipe must be code that worked.
  Cost if wrong: a dataset that depends on a failed run's side effect gets a
  recipe that does not reproduce it, which validation then reports.
- **Project files are private and durable**: `quarry.projects.files` holds the
  session store's atomic writer, which both stores now import, so project files
  are written 0600, fsynced and renamed into place. `ProjectStore` creates each
  project directory and each dataset and view directory 0700; the intermediate
  `projects/`, `datasets/` and `views/` follow the umask, which the 0700 root
  and project directory cover. A pinned save creates its dataset directory
  before the kernel's snapshot, whose own `mkdir` would follow the kernel's
  umask, and makes `data.parquet` 0600 once the snapshot returns. The plan's
  helper made directories and wrote text in place, while recipes hold the same
  code that made session files private. One lock in `ProjectStore` covers every
  read-modify-write of `project.json` and the slug choice in `create`, so a
  save's `updated_at` touch cannot drop a canvas write made at the same moment.
  A slug, view name or session id from a request joins its directory through
  `child`, which accepts one path segment only, so a body field cannot reach
  another directory's files. Cost if wrong: a researcher must `chmod` a project
  to share it in place, and the fsyncs add a little save latency.
- **Projects list by name, then slug**: `ProjectStore.list` sorts by lowercased
  name with the slug breaking ties, since "Momentum" and "momentum" share a
  lowercased name and `iterdir` order is arbitrary. The plan sorted by name
  alone and defined a second `now_iso`; the store imports the server's.
- **A save looks the session up first**: `save_dataset` reads the session before
  it holds the kernel, so an unknown session is 404 and never starts a kernel,
  since `KernelManager.get` spawns one for any id.
- **A save waits for the replay**: `save_dataset` answers 400 with "restart the
  session so its steps replay before saving" while the session's kernel status
  is `replay_needed`, before it holds the kernel. A session reopened after a
  server restart otherwise got an empty kernel and a 404 for the dataset its
  step card shows. `save_view` reaches the check through each dataset it saves,
  and needs no kernel when all are saved. Cost if wrong: a dataset loaded on the
  fresh kernel cannot be saved until a restart replays every step.
- **Pinned data is read by absolute path**: a pinned save snapshots to the
  absolute `data.parquet` path, and recall generates `pl.read_parquet` of that
  path at recall time rather than storing it in the project. That settles the
  kernel's working directory and relative snapshot paths for projects. Cost if
  wrong: a session that recalled pinned data replays only while the project
  stays where it was.
- **Recall asks before it runs**: a recall from the rail always asks first, and
  the prompt says what it changes: a dataset recall replaces an existing dataset
  of that name, and a view recall loads the view and any of its datasets the
  session lacks. A confirmed dataset recall rebinds the name, and since the
  recall is a real step, the overwrite is on the record. The canvas "Load" does
  not ask, because a view recall loads only the datasets the session lacks. Cost
  if wrong: the session's own binding is gone until the step that made it runs
  again.
- **View recall checks the kernel inside a hold**: a view recall lists the
  session's datasets inside `hold`, so it answers 409 at once while a step,
  restart or save runs, and its step loads only the datasets the session lacks.
  The plan listed them before taking the session, which waited on the kernel
  behind a running step. Cost if wrong: a recall during a save also answers 409.
- **Save buttons use the existing slots**: "Save view" and "Pin to canvas" sit
  in `ViewFrameContainer`'s `actions` row and a dataset chip's "Save" comes
  through `renderAction`, all rendered by `StepActions`, which owns the dialog.
  Save and recall errors, a 409 included, show in the notice line or under the
  rail. The plan split this between an `onSave` prop and
  `renderActions(step, dataset?)`, with no single owner of the dialog.
- **A save shows that it runs**: `StepActions` posts "Saving <name>…" in the
  notice line before the request and disables its buttons until the save and any
  pin finish; the result then replaces the notice. A save is a provider call and
  one or two scratch kernels per dataset, which can take a minute, and a second
  click started a second save of the same files.
- **A view is on a canvas once**: cards are keyed by view name, so `set_canvas`
  answers 400 for a canvas that repeats a view, and "Pin to canvas" adds a card
  only for a view the project's canvas lacks, read from the project rather than
  the list. Pinning a saved view again refreshes its card through `saved_at`. A
  second pin had added a duplicate card, and Remove then dropped both.
- **The canvas binds to the active session**: cards query through its kernel,
  and a card whose datasets the session lacks shows "Load", which recalls the
  view as a step. Only the layout lives in `project.json`; a card's state lasts
  for the visit, and "Save view" again freezes a new one. There is no hidden
  project kernel. Cost if wrong: a canvas needs an open session.
- **The canvas shows its own busy state and errors**: a card's "Load" is
  disabled while a recall is pending or the session's last step runs, and recall
  and layout-save errors show above the cards. A recall then would only answer
  409, and the project page has no notice line of its own.
- **`shared:` keys link only on the canvas**: `SharedStateHub` sends each other
  card `restore` with its last known state merged with the changed card's
  `shared:` keys. Nothing is seeded on load, so the first change wins. Inside a
  session a view's `shared:` keys stay private, by design, since the step column
  is the record. Cost if wrong: cards saved with different values disagree until
  one changes.
- **The project page replaces the session column**: `SessionPage` renders
  `ProjectPage`, keyed by slug, in the session column's place, so the rails stay
  and choosing or creating a session goes back; each project gets its own hub.
  The plan lifted `activeId` and the hash sync into `App`, but the page needs
  `SessionPage`'s current session. Cost if wrong: `App` has no page state for
  Stage 5 to extend.
- **Canvas layout writes are debounced**: a drag or resize writes `project.json`
  500 ms after the last change, a pending write is flushed when the page
  unmounts, and Remove writes at once. The grid measures its width before it
  mounts, so cards open at their saved size, and drags never start on a button.
  Cost if wrong: closing the tab within 500 ms of a drag loses it.
- **`react-grid-layout` 2 with its own types**: the canvas uses
  `react-grid-layout` 2.3, which ships its types, so `@types/react-grid-layout`,
  written for v1, is not installed. `react-resizable` is pinned to `^3.2.0`, the
  range the grid depends on, since a bare install added 4.0.2 as a second copy.
  Cost if wrong: moving to `react-resizable` 4 waits on the grid.
- **The notebook is built by hand and validated only in tests**:
  `quarry.projects.export` writes nbformat 4.5 JSON itself, with cell ids,
  `kernelspec` and `language_info`, and `nbformat` is a dev dependency that the
  export tests validate against. The wheel then needs no Jupyter package. Saved
  queries render without a schema, since only dtype strings are on disk; the
  cell's first comment says so. Cost if wrong: a format change goes unnoticed
  until a test validates it.
- **Export names results across the whole notebook**: a view's queries assign
  `<dataset>_<n>`, n being the query's position in its view, through
  `result_names` in `quarry.query.source_target`, which "To code" uses too. The
  suffix rises past every saved dataset and every name an earlier view took, so
  no result overwrites what a later cell reads, and a query that fails
  validation keeps its number. A query whose generated import, such as
  `from datetime import date`, would rebind a saved dataset stays a
  `# query N could not be rendered` comment naming it, as "To code" refuses one.
  Free text in an exported comment, such as a description, a validation error or
  a pydantic message quoting a raw JSON key, goes through `py_comment`, which
  `raw_recipe` shares: line breaks become spaces and anything else unprintable
  is escaped, so a line break cannot run the rest as code, a NUL cannot stop the
  cell compiling, and a bidi control cannot disguise it. The plan named results
  with no check and put the multi-line pydantic message into a comment. Cost if
  wrong: such a query is missing from the export until the dataset is renamed,
  and a view's result numbers depend on the views that sort before it.
- **Exported recipes run in dependency order**: a raw recipe replays its
  upstream steps, so the recipe of `returns`, derived before a later step
  filtered `prices`, also rebinds `prices` to the unfiltered frame. The notebook
  therefore runs a recipe that assigns another saved dataset, by
  `analyze(recipe).stores`, before that dataset's own recipe, and keeps saved
  order wherever nothing constrains it; each dataset's heading moves with its
  recipe, and every dataset still precedes every view. Recipes in a cycle, which
  assign each other directly or around it, run in saved order among themselves,
  even when a recipe outside the cycle must run before one of them, and a recipe
  that runs after a saved dataset it assigns opens with a comment naming it. A
  recipe that does not parse constrains nothing. The plan emitted recipes in
  saved order. Cost if wrong: datasets no longer appear in name order, and a
  cycle's warning asks the researcher to sort it out.

## Views

### Perspective

- **Perspective's config maps to a query spec, and the mapping is lossy**:
  `perspectiveToSpec` turns the viewer's saved config into a `QuerySpec` the
  kernel accepts and lists what the spec cannot say in `dropped`, which the
  pivot built-in keeps in view state for "to code". Filters `==`, `!=`, `<`,
  `<=`, `>` and `>=` become `eq`, `ne`, `lt`, `le`, `gt` and `ge`; `in` and
  `not in` become `in` and `not_in`; `contains` and `begins with` become
  `contains` and `starts_with`; `is null` and `is not null` become `is_null` and
  `not_null`. Any other operator, such as `ends with` or `is true`, is dropped.
  Under `group_by`, each other column becomes one `Agg`: `sum`, `mean`, `min`,
  `max`, `count`, `median`, `first` and `last` keep their names, `avg` becomes
  `mean`, `high` becomes `max` and `low` becomes `min`; any other aggregate is
  dropped. `stddev` is dropped too, though the spec has `std`: Perspective's is
  the population figure (1.5 for 1 and 4) and the kernel's the sample one
  (2.12), so "to code" would print different numbers. A column with no aggregate
  set takes Perspective's default, which the saved config leaves out
  (`aggregates` stays `{}`; the defaults go only into the copy passed to
  `table.view()`): `sum` for a numeric dtype, matched as the other built-ins
  match it (`/^(Int|UInt|Float|Decimal)/`, and Decimal and 128-bit integers
  reach Perspective as floats), and `count` for everything else; Perspective
  3.8.0 counts Boolean, Date and Datetime columns too. A column missing from the
  schema counts. Exactly one `split_by` with exactly one aggregated column
  becomes a `pivot` indexed by the group keys; two or more `split_by`, or a
  split over several aggregated columns, drops the split and keeps the grouping.
  When every column is a group key, the spec counts the first key, since
  `group_by` needs an aggregate. Without `group_by`, `columns` becomes `select`,
  skipping nulls and expression names, and any `split_by` is dropped.
  Expressions are dropped, and so are filters, sorts, group keys and split keys
  on them.
- **Sorts name output columns**: sort and select run on the grouped output, so
  under `group_by` a sort on an aggregated column becomes that aggregate's
  output name (`v_sum`), a sort on a group key stays, and any other sort is
  dropped. Under a pivot only sorts on index keys stay. Only `asc` and `desc`
  carry over; `col asc`, `desc abs`, `none` and the other directions are
  dropped.
- **Filter terms are typed as the viewer means them**: the dtypes come from the
  arrow result's schema, which holds the dtypes from before the arrow casts. The
  viewer writes every `in` list as strings, so items become numbers on numeric
  columns (an Int column drops an item that is not a whole number, since the
  engine's `stoll` would truncate it) and booleans as the engine reads them
  (`"true"` is true, anything else false). A Date term stays a `YYYY-MM-DD`
  string, and epoch milliseconds become their UTC day, as the engine's `gmtime`
  reads them; any other Date string is dropped. A Datetime term is epoch
  milliseconds (`str_to_utc_posix`), which becomes a naive UTC ISO string: a
  naive column holds UTC wall clocks and the kernel reads a naive string on a
  zoned column as UTC. A Datetime string term is dropped, since the kernel reads
  an offset by time unit and the engine by its own parser. `in` on a Decimal
  column is dropped: polars `is_in` refuses Float64 items there.
- **Filters the spec cannot carry are listed**: a filter with no term yet, which
  is what dropping a column on the filter bar creates, and an `in` list that is
  missing, empty or holds a null are listed and left out. Neither the viewer
  (`drag_drop_update.rs`) nor the engine (`fill_fterm`) removes a null-term
  filter, and the engine applies one (`==` matches no row, `!=` every row), so
  these are listed rather than skipped silently. They do not count toward
  `filter_op: "or"`, which the spec's list of filters cannot say: under "or",
  two or more remaining filters are all dropped, listed once as
  `filter_op "or"`, and a lone filter maps as under "and".
- **The pivot shows 50,000 rows and probes the mapped spec**: Perspective shows
  up to 50,000 rows; the probe query with `limit: 1` is how the kernel validates
  the mapped spec and how it reaches lineage. Until the arrow rows arrive the
  probe repeats the arrow query, so no spec mapped without dtypes is recorded. A
  probe the kernel refuses shows its error above the viewer.
- **The viewer restores a changed `config` only after its first load**: the
  plan's effect restored on mount, before any table was loaded, racing the load.
  The load path restores the latest config itself and records it, as it records
  each config the viewer saves, so neither that config nor the viewer's own echo
  is restored a second time. A viewer unmounted while its table loads restores
  nothing.
- **The saved config is a `JsonObject` in view state**: Perspective's types
  allow `undefined` values, which `useViewState`'s `Json` bound refuses, so the
  pivot casts at the boundary, as the plan allowed.
- **A view may publish its to-code spec under `spec`**: "To code" renders
  `[spec]` when the latest snapshot's state holds a `spec` object with a string
  `dataset`, for any view, and the snapshot's queries otherwise. The pivot
  publishes its mapped spec there, without `limit`, written beside `dropped`;
  its queries are the 50,000-row arrow load and the one-row probe, which would
  render as `.head(1)`. A saved view's export still renders the recorded
  queries.

### TanStack table and OHLC

- **Built-ins inline their column helpers**: the plan's `_shared/columns.ts`
  would load as `require("@builtin/_shared/columns")`, which the runtime cannot
  serve, so each built-in keeps its own `isTime` and `isNumeric` and
  `time-series` is unchanged.
- **The TanStack table registers no sorting feature**: the query spec sorts on
  the server and `header.column.id` is core in v9, so the plan's
  `rowSortingFeature` and `enableSorting: false` are gone; v9's `TableOptions`
  refuses `enableSorting` without that feature. The numeric flag is typed
  through the `columnMeta: metaHelper<…>()` slot instead of a cast. As the AG
  Grid table does, it drops a saved sort on a column the live schema lacks and
  shows "Showing the first N rows." when a page is full; the plan's "N of M
  rows" would repeat the page size, since `row_count` counts the rows returned.
- **OHLC reads times and prices as the time series does**: naive ISO datetimes
  are UTC, Decimal strings become numbers, a candle whose time or any price is
  not finite is dropped, and rows on the same second keep the last, because
  Lightweight Charts throws on those. The plan's bare `Date.parse` read a naive
  datetime as local time.
- **OHLC never guesses one column for two roles**: a saved column counts only
  while the live schema has it with a fitting dtype; each remaining price role
  then takes the first free numeric column named like it, then the first free
  numeric column. A column the researcher picks for two roles keeps both, and
  the query selects it once, since the kernel refuses a repeated `select` name.
  The chart effect is keyed on the rows and the five names, so a re-render with
  the same result keeps the chart.

### Recharts, Plotly and ECharts

- **No invented zeros**: the bar and line, scatter, heatmap and large series
  built-ins read values with the time series' `parseValue`, never `Number()`,
  which turns `null` into 0. A null aggregate stays `null`, so Recharts leaves a
  gap; a scatter point whose x or y is not finite is dropped; a null or
  non-numeric heatmap cell is NaN, which Plotly leaves blank; a large series row
  whose time or value is not finite is dropped.
- **The large series plots UTC epoch milliseconds**: points are
  `[epochMs, value]` pairs read with the time series' `parseTime`, so a naive
  datetime is UTC, and the option sets `useUTC: true`. Given strings, ECharts
  reads a naive datetime as browser-local time, which shifts it around DST
  changes. The plan's `large: true` and `largeThreshold` are gone: ECharts line
  series have no large mode (`LineSeriesOption` has no `large`), so
  `sampling: "lttb"` and `showSymbol: false` are what keep 50,000 points fast.
- **No two roles share a column, and no pick hides the pickers**: a saved column
  counts only while the live schema offers it, so a stale choice falls back to
  the default instead of failing the query. Roles resolve in an order that
  always leaves the next one a column, and each picker offers only the columns
  still free, compared ignoring case as the kernel compares names. In the
  scatter, y skips x and the color column skips both. The heatmap resolves the
  value first, then the row and column keys from the rest, and the column skips
  the row, since a column pivoted against itself is only a diagonal. The bar and
  line chart resolves the value first and skips `<value>_<fn>`, the aggregate's
  name, as a category; with no other column left it groups by a numeric one,
  then by the value itself, which the kernel accepts, because the manifest's
  `any` role matches all-numeric datasets.
- **The heatmap never defaults to a numeric key**: the pivot runs eagerly and
  makes one column per distinct value of its column key, which `row_cap` and
  `limit` do not bound, so a float key made a grid thousands of columns wide on
  open. Only non-numeric columns are default keys. Numeric ones stay in the Row
  and Column pickers as a deliberate choice; until a key is picked the picker
  shows blank, a note asks for it, and only the `{dataset, limit: 1}`
  placeholder query runs.
- **The scatter colors by at most 30 values**: each color value is its own
  `scattergl` trace, and Plotly stalls on thousands. Past 30 distinct values the
  points draw as one series with a note saying so; there is no numeric
  colorscale.
- **Truncation banners give no total**: `row_count` counts the rows returned and
  `truncated` is set only when the server's row cap cut them, so each of these
  built-ins shows "Showing the first N rows." when the result fills its limit or
  the cap cut it. The pivot's banner said "of {rowCount} rows", which repeated
  its own count, and fired only on the cap; it now reads the same way.
- **The bar and line chart names its series as the kernel does**: the aggregate
  column is `<value>_<fn>`, `Agg.name` without an alias.

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
- **CI times out**: the test job stops after 20 minutes, so a hung test fails
  instead of running to GitHub's 6-hour limit.
- **Local Python matches CI**: `.python-version` pins 3.11. The local venv had
  resolved 3.14, so failures specific to 3.11 surfaced only in CI.
- **Tests are annotated**: ruff's ANN rules apply to tests as well as `src`,
  where the plan had a per-file ignore.
- **Plotly's peer resolves to the dist build**: `web/package.json` overrides
  `plotly.js` with `npm:plotly.js-dist-min@4.1.2`, so react-plotly.js's peer no
  longer installs the full 98 MB source package and its 211 lock entries, which
  nothing imports. The runtime uses `react-plotly.js/factory` with the dist
  build either way.
