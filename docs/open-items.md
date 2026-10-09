# Open items

Gaps in the shipped code, work deferred to later stages, and decisions nobody
has made yet. Decisions already made are in
[decisions.md](context/decisions.md).

## Known problems

- **`in` on zoned columns of frame-backed relations**: an `in` filter with two
  or more items on a tz-aware column of a relation over an in-memory frame needs
  `pytz`. DuckDB imports it for the scan, and Quarry does not depend on it.
  Fails loudly with `InvalidInputException`; `eq` and relations over parquet are
  unaffected.
- **Open DuckDB result streams get cut short**: a result left open across steps
  on the shared connection is truncated by the next query, including the
  kernel's own previews and view queries. Silent: a probe read 100,000 of
  3,000,000 rows with status `ok`. After an interrupt, the stream fails loudly
  instead.
- **A running polars `collect()` ignores interrupts**: the `KeyboardInterrupt`
  lands only once the collect finishes, so a long collect cannot be stopped.
  Silent: `interrupt` reports the signal delivered, and the step keeps running.
- **Four RPCs cannot be interrupted**: `describe`, `list_datasets`, `query` and
  `snapshot` run outside the guarded regions, so a slow relation preview, query
  or snapshot holds the kernel until it ends. Silent: `interrupt` answers
  `delivered: false`.
- **Previews run eagerly and are not cached**: every step describes its writes,
  so a LazyFrame or relation runs its plan as soon as it is assigned.
  `list_datasets` recomputes every preview on each call. Silent cost, with no
  error.
- **Time and UUID filters**: an ISO string against a Time column fails on the
  polars target with `InvalidOperationError`, since only Date and Datetime
  literals are coerced. Relation UUID columns are described as String, yet
  `contains` and `starts_with` on them raise DuckDB's `BinderException`. Both
  fail loudly; `eq` on a UUID works.
- **Targets disagree on loosely typed literals**: a string against an integer
  column, or a datetime-shaped string against a Date column, filters on a
  relation but raises on a polars backing. A malformed ISO date raises a bare
  `ValueError` that does not name the column. Loud on polars backings; silent
  coercion on relations.
- **Unchecked list items and pivot errors**: nested lists or objects inside
  `in`, `not_in` and `between` values pass validation and fail in the engine.
  Errors inside a pivot spec surface as raw polars errors. Both fail loudly.
- **Unsorted group-by and pivot rows have no fixed order**: without a `sort`,
  row order can change between runs and between targets. Silent; paging with
  offsets would skip or repeat groups.
- **Relation intervals sort and filter as text**: INTERVAL columns of relations
  are projected as VARCHAR, so `9 days` sorts after `100 days`. Silent.
- **Odd temporal values**: DuckDB `'infinity'` in a TIMESTAMP_S or TIMESTAMP_NS
  column arrives as a wrong in-range date, 1969-12-31 or 2262-04-11. TIMETZ
  arrives as Time with its offset dropped. Both silent.
- **Large and opaque integers in JSON rows**: 64-bit and 128-bit integers above
  2^53, including sums over 128-bit columns, are JSON numbers, which JavaScript
  rounds. VARINT and BIT values arrive as base64 of DuckDB's internal bytes.
  Both silent.
- **Lineage blind spots**: table names inside SQL strings, such as
  `sql_local("... FROM recent")`, are not reads. Helpers bound without `def` or
  `class` (lambdas, `partial`, imports) and attribute mutation such as
  `df.columns = [...]` are invisible too. Silent: a saved recipe can miss a
  source step.
- **Lineage approximations**: a failed step's in-place mutation is not a write,
  while a successful step's store that never ran is one. Class bodies report
  every name they load as a read. Silent; see
  [decisions](context/decisions.md#lineage).
- **Generated relation source and INTERVAL output**: to-code on a relation query
  that returns an INTERVAL column fails at `.pl()` with polars `ComputeError`.
  Fails loudly.
- **Schema-less generated source**: without `schema=`, `to_source` renders
  numbers as given and sums plainly. `ret in [0]` on a float column then fails
  loudly when run, and an Int64 sum can wrap silently.
- **`to_source` errors are not `QueryError`**: a bad identifier or a malformed
  date raises `ValueError` or `TypeError`. Fails loudly, under a type callers do
  not expect.
- **Interrupts stop only the kernel's DuckDB connection**: DuckDB workers for a
  relation on a researcher's own `duckdb.connect()` can keep running after an
  interrupt. Silent: they hold CPU and delay that connection's next query.
- **A step's child can outlive the kernel**: a process a step started that calls
  `setsid` leaves the kernel's process group, so `close()` does not kill it.
  Silent.
- **No memory cap on macOS**: macOS rejects `RLIMIT_AS`, so the kernel runs
  uncapped. Silent to the client; the only sign is one line on the kernel's
  stderr.
- **Config errors can print secrets**: pydantic echoes the input of an unknown
  key, so a misspelled `mssql_dsn` key prints its password when startup fails.
  `mssql_dsn` and the license keys also appear in the config model's repr. Fails
  loudly, with the secret in the output.
- **`close()` right after `shutdown()` can cut off a snapshot**: `close()` sends
  SIGKILL at once, so a snapshot still writing leaves a stray `.tmp` file beside
  its target. The target keeps its old contents. Silent.
- **Output tails count characters**: the spec promises the last 4 KB of output,
  and the tail keeps 4096 characters. Silent; multi-byte output runs past 4 KB.
- **The server imports loaders and scans the cache at startup**: it runs
  `load_loaders` and `scan_layout` itself to describe them to the agent. A
  `PermissionError` from `scan_layout`, or from `path.exists()` in
  `load_loaders`, stops `quarry serve`, and a loader that hangs at import hangs
  it. Both loud. `scan_layout` also drops unpartitioned dataset directories, so
  the agent never hears of them. Silent.
- **Interrupt cannot stop a model call**: `/interrupt` reaches only the kernel,
  so while a step waits on the provider it answers `ok: false` and the loop goes
  on. Silent.
- **A crashed prompt step loses its runs**: an exception other than
  `ProviderError` or `KernelDead` fails the step with no `runs`, so restart
  skips blocks that ran. Silent until a restart.
- **A kernel never started reads as `starting`**: after a server restart,
  `/status` reports `starting` for a session whose kernel was never spawned, so
  a client cannot tell that its namespace is empty. Silent.
- **Restart shows no progress**: replay runs inside the `/restart` request,
  while spec §6 wants progress in the UI. Silent until it returns.
- **Every `/status` poll parses every step**: it loads the whole session under
  the service lock, since no route reads one step. A silent cost that grows with
  the session.
- **Prompt-step tracebacks land in the message**: a prompt step's error puts the
  traceback in `error.message` and leaves `traceback` empty, while manual steps
  fill `traceback`. Silent.
- **No transpile check runs yet**: spec §8 promises a Sucrase check, but
  `transpile-check.mjs` ships with the Stage 3 frontend, so `render_view` and
  `write_view` accept any source until then. `CommandTranspiler` then runs it
  with no timeout, so a hung check would hang the step. Silent.
- **Session files are neither durable nor private**: atomic writes skip `fsync`,
  so a machine crash can lose a finished step. The root and session directories
  take the umask, so other users can usually read prompts and code. Silent.

## Deferred work

### Stage 2

- Add a restart escalation for interrupts that cannot land, such as a running
  polars `collect()`, so the researcher can always get control back.
- Cache dataset metadata per write identity, so `list_datasets` stops
  recomputing previews and the uninterruptible RPCs stay fast.
- Stamp `DatasetMeta.origin_step` in the server and pass the kernel a
  `--session` argument, since the kernel has no step ids.
- Keep an unreadable path from stopping the server: catch `PermissionError` in
  `scan_layout` and in `load_loaders`, which is meant never to raise. Make
  `scan_layout` list unpartitioned dataset directories too.
- Make loader problems clear at startup: name a loader that hangs at import, and
  explain a missing `mssql` extra instead of a bare `ModuleNotFoundError`.
- Set `hide_input_in_errors` and keep `mssql_dsn` and license keys out of reprs
  before any config logging or UI, so secrets cannot leak.
- Make `api_key` raise only `ConfigError`: `PermissionError`,
  `IsADirectoryError` and `UnicodeDecodeError` escape and fail the step with a
  raw error, and its exists-stat-read sequence can race.
- Expand `~` in every config path and resolve relative paths against the root,
  since the server and kernel working directories can differ. Today these fail
  loudly.
- Add config tests for the OpenAI env mapping, env-over-file precedence, mode
  0o604, missing or empty key files, `~` expansion and secret-free errors.
- Kill the kernel when a Ctrl-C lands in `spawn` after `Popen`, and release the
  socket and temp directory when `close()` times out.
- Keep every client failure inside `KernelDead` or `RpcFailure`: a long `TMPDIR`
  makes the socket bind raise `OSError`, and a malformed result raises
  `ValidationError`.
- Refuse or interrupt a step when `shutdown` lands between dequeue and `exec`;
  today only `close()` or socket EOF ends it.
- Test the memory-cap wiring in `main`, since both current tests monkeypatch
  `setrlimit`.
- Add config models before new keys appear in `config.toml`, because unknown
  keys now fail startup.
- Settle the open questions on the root override, memory limits, CPU thread
  caps, previews and result streams.
- Save the runs of a prompt step that crashes, so restart replays them.
- Create the root and session directories private, and `fsync` step files.

### Stage 3

- Sort group-by and pivot results by the group keys by default. This must land
  before views page with offsets, or pages will skip or repeat groups.
- Add a tie-breaker to paged sorts, because DuckDB's parallel `ORDER BY` returns
  rows with tied keys in a different order each run.
- Ship the built frontend in the wheel: `.gitignore` excludes
  `src/quarry/static/`, so hatch drops it unless the wheel lists it in
  `artifacts`.
- Explain in the UI why an interrupt may not stop a step at once, and offer the
  Stage 2 restart.
- Let `/interrupt` stop a step waiting on the model, with a cancel flag the loop
  checks between provider calls.
- Run restart in the background and report replay progress through `/status`, as
  spec §6 asks.
- Report a kernel that was never started apart from one starting, so the UI can
  offer a restart after the server restarts.
- Add a route that reads one step, so polling stops parsing the whole session.
- Put prompt-step tracebacks in `error.traceback`, as manual steps do.
- Give `CommandTranspiler` a timeout once the Stage 3 build ships
  `transpile-check.mjs`.
- Fix filter coercion for Time literals, UUID and other natively imported
  relation columns, strings against integer columns, and datetime-shaped strings
  against Date columns.
- Turn spec-caused failures into errors that name the column: malformed ISO
  dates, unchecked nested list items and raw errors from eager pivots.
- Settle the JSON row contract with the renderer, and return null for DuckDB
  `'infinity'` in TIMESTAMP_S and TIMESTAMP_NS columns.
- Pre-aggregate relation pivots by index and pivot columns in SQL, because the
  pivot now pulls every filtered row into polars.

### Stage 4

- Extend lineage to SQL strings by passing string literals given to `sql_local`,
  `duckdb.sql` and `_conn.sql` through `duckdb.get_table_names`. Recipes from
  `sql_local` steps miss their source step until then; Stage 2 replay may need
  it sooner.
- Cover the other lineage blind spots, helpers bound without `def` or `class`
  and attribute mutation, before recipes rely on lineage.
- Decide whether a failed step's in-place mutation counts as a write, since
  recipes depend on it.
- Set a path policy for the kernel's working directory and relative snapshot
  paths.
- Let a cleanly exiting kernel finish before `close()` kills it after
  `shutdown()`, so an in-flight snapshot completes.

### Stage 5

- To-code must pass `schema=` to `to_source`; without it, `ret in [0]` and
  date-shaped strings on string columns fail when run.
- Convert INTERVAL output in generated relation code while keeping it plain
  Python.
- Raise `QueryError` from `to_source` for spec-caused failures, not `ValueError`
  or `TypeError`.
- Require NFKC-stable or ASCII identifiers in `to_source`: `ｔrades` passes
  `isidentifier()` but runs as `trades`.
- Choose the Arrow IPC compatibility level, including view types, that
  Perspective reads.

### Any time

- Move CI to current `actions/checkout` and `astral-sh/setup-uv` versions, and
  add `permissions: contents: read`.
- Keep the version in one place: `pyproject.toml` and `src/quarry/__init__.py`
  both hold it, and the test checks only its type.
- Run mypy on `tests` as well as `src`.
- Count output tails in bytes, as the spec's "last 4 KB" says.
- Type the op sets in `quarry/query/spec.py` as `frozenset[FilterOp]` rather
  than `frozenset[str]`.
- Remove the second literal coercion in `_imported_names` in `source_target.py`,
  which repeats the filter rendering's work.
- Keep TIMETZ offsets in JSON rows, and fix the Duration comment in
  `_json_native`, which says milliseconds though the guard covers every unit.
- Smoke-test `sql()` against the firm's SQL Server with `VARCHAR(MAX)` columns,
  which may need arrow-odbc's `max_text_size`.
- Close test gaps: the shutdown tests pass even if the kernel never exits. The
  equivalence `normalize` sorts rows, so order is compared only under a limit.
- Tighten tests further: some `match=` patterns in `test_spec.py` also match
  pydantic's echoed input, and the polars target has no direct nulls-first test.
- Close Stage 2 test gaps: nothing checks the arguments the OpenAI adapter
  sends, that every tool schema stays strict, or that a SciChart key enables
  SciChart.

## Open questions

- **`--root` or a config `root` key**: which wins, and should a `root` key in
  `config.toml` exist at all, given it lives inside the root it overrides?
  Options: drop the key, keep it with `--root` winning, or keep it with the
  config winning.
- **Memory limits**: `RLIMIT_AS` counts virtual memory, including mmapped
  parquet, thread stacks and malloc arenas. A cap near the working set then
  breaks polars and DuckDB in confusing ways. Options: keep `RLIMIT_AS`, use
  cgroups through `systemd-run --user -p MemoryMax`, or use `RLIMIT_DATA`.
  DuckDB's 70% share of the cap is unmeasured too.
- **JSON contract for the Stage 3 renderer**: decimals arrive as exact strings,
  so every sum over integers of up to 64 bits is a string, while a 128-bit sum
  is a number. A Map is an object when its key type allows one and no value
  needs converting, such as Binary to base64; otherwise it is a list of
  `{key, value}` entries, and integers above 2^53 are numbers JavaScript rounds.
  Options: keep these and parse by schema dtype, send large integers as strings,
  or use Arrow where exact values matter.
- **Naive timestamps and offset strings**: keep DuckDB 1.5.6's per-unit rule,
  where only nanosecond columns convert an offset to UTC, or pick one rule for
  every unit? The current rule follows DuckDB's cast, which an upgrade could
  change.
- **Interrupt escalation and restart UX**: Stage 2 needs a restart escalation,
  and the UI must explain it. When to offer or force the restart, and what the
  researcher sees meanwhile, is open. Today `/restart` answers 409 while a step
  runs, so the only escape from a hung step is killing the kernel's process.
- **Live provider calls**: neither adapter has called its real API. Whether the
  Anthropic API accepts `fallbacks="default"` with the
  `server-side-fallback-2026-07-01` beta, and whether `gpt-5` is the right
  OpenAI model name, is unverified. `tests/agent/test_live_providers.py` checks
  both once keys are set.
- **Previews**: cache them per write identity in Stage 2, or compute them on
  demand when a client asks? Today every write forces lazy plans to run.
- **CPU threads per kernel**: polars and DuckDB each default to every core, so
  several kernels on one machine oversubscribe it. Options: cap threads per
  kernel through config (`POLARS_MAX_THREADS` and DuckDB's `threads` setting),
  or keep the defaults.
- **Exact class-body lineage**: keep over-reporting class-body reads, or add
  execution-order analysis covering conditionals, loops, `del` and `try`?
  Over-reporting adds recipe dependencies but never drops one.
- **Result streams on the shared connection**: should the kernel protect result
  streams left open across steps from later queries, or only document the limit?
  Neither option has been evaluated.
