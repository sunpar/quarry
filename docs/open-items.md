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
- **Previews run eagerly**: every step describes its writes, so a LazyFrame or
  relation runs its plan as soon as it is assigned. Silent cost, with no error.
- **Stale previews from outside a step**: the kernel clears cached dataset
  metadata only when a step runs, so a parquet file rewritten under a LazyFrame,
  or a DuckDB file another process writes, shows an old preview until the next
  step. Silent.
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
- **No memory cap on macOS**: macOS rejects `RLIMIT_DATA`, so the kernel runs
  uncapped. Silent to the client; the only sign is one line on the kernel's
  stderr.
- **Small memory caps need a thread cap**: on Linux `RLIMIT_DATA` counts thread
  stacks, so with every core in use a small cap kills the kernel as polars
  starts, as 256 MB on 14 cores did. Loud: the kernel dies. `kernel_threads`
  avoids it.
- **`close()` right after `shutdown()` can cut off a snapshot**: `close()` sends
  SIGKILL at once, so a snapshot still writing leaves a stray `.tmp` file beside
  its target. The target keeps its old contents. Silent.
- **Output tails count characters**: the spec promises the last 4 KB of output,
  and the tail keeps 4096 characters. Silent; multi-byte output runs past 4 KB.
- **A loader that hangs at import hangs startup**: the server imports loaders to
  describe them to the agent, and each kernel imports them at start. Loud only
  through a stderr notice naming the loader after 10 s.
- **Some cache layouts are hidden or misread**: `scan_layout` skips an
  unreadable directory without a log line, and misses a dataset whose parquet
  files sit only in nested directories not named `key=value`. A dangling
  `*.parquet` symlink still lists its dataset. Silent.
- **Cancel waits for the model**: `/interrupt` and `/restart` stop a prompt step
  only once the provider answers the call in flight, bounded only by the
  provider client's timeout. Meanwhile `/restart` holds its request, a second
  restart gets 409, and under uvicorn a graceful Ctrl-C waits too. Silent.
- **A crashed prompt step saves no code or transcript**: an exception other than
  `ProviderError` or `KernelDead` saves the step's runs and their lineage, but
  leaves `code` empty and saves no view or transcript. Silent.
- **Restart can mislabel a step**: a step that a kernel crash or the
  researcher's cancel ended right before a restart is saved with "stopped by a
  restart". Silent; the status is right.
- **A stuck kernel holds the manager lock**: `KernelManager.kill` and `restart`
  close the old client under the manager's lock, and `close()` waits up to 5 s
  for a killed kernel, so every session's kernel lookup waits too. Silent.
- **`origin_step` can name a step replay dropped**: replay skips interrupted
  runs and stops at the first failure, but `/datasets` still credits the latest
  saved writer. After a step that rebound `df` is interrupted and the session
  restarts, `df` holds the older data and names the interrupted step. Silent.
- **Saving a step stalls every route**: `_finish` writes and fsyncs the step
  file and its directory under the service lock that every route takes. With a 1
  s fsync in a probe, another session's `/status` took 2 s, so a slow filesystem
  such as an NFS home directory stalls all sessions. A failed save also kills
  the kernel under that lock, which can wait up to 5 s for the process to exit.
  Silent.
- **A kernel never started reads as `starting`**: after a server restart,
  `/status` reports `starting` for a session whose kernel was never spawned, so
  a client cannot tell that its namespace is empty. Silent.
- **Restart shows no progress**: replay runs inside the `/restart` request,
  while spec §6 wants progress in the UI. Silent until it returns.
- **Every `/status` poll parses every step**: it loads the whole session under
  the service lock, since no route reads one step, and `/datasets` parses every
  step too. A silent cost that grows with the session.
- **Prompt-step tracebacks land in the message**: a prompt step's error puts the
  traceback in `error.message` and leaves `traceback` empty, while manual steps
  fill `traceback`. Silent.
- **No transpile check runs yet**: spec §8 promises a Sucrase check, but
  `transpile-check.mjs` ships with the Stage 3 frontend, so `render_view` and
  `write_view` accept any source until then. Silent.

## Deferred work

### Stage 5

- Sort group-by and pivot results by the group keys by default. This must land
  before views page with offsets, or pages will skip or repeat groups.
- Add a tie-breaker to paged sorts, because DuckDB's parallel `ORDER BY` returns
  rows with tied keys in a different order each run.
- Explain in the UI why an interrupt may not stop a step at once, and offer the
  Stage 2 restart.
- Run restart in the background and report replay progress through `/status`, as
  spec §6 asks.
- Add a route that reads one step, so polling stops parsing the whole session.
- Put prompt-step tracebacks in `error.traceback`, as manual steps do.
- Fix filter coercion for Time literals, UUID and other natively imported
  relation columns, strings against integer columns, and datetime-shaped strings
  against Date columns.
- Turn spec-caused failures into errors that name the column: malformed ISO
  dates, unchecked nested list items and raw errors from eager pivots.
- Settle the JSON row contract with the renderer, and return null for DuckDB
  `'infinity'` in TIMESTAMP_S and TIMESTAMP_NS columns.
- Pre-aggregate relation pivots by index and pivot columns in SQL, because the
  pivot now pulls every filtered row into polars.
- Push the data table's filters into the query spec, and keep the previous rows
  while a sort refetches, so the grid stops flashing to "Loading".
- Restore the last snapshot's state on mount: a reload resets a view to
  `initial_state` even when `view.snapshots` has later state.
- Detect a view frame that navigates itself (its `load` event fires a second
  time) and tear the frame down; see [decisions](context/decisions.md#first-ui).
- Invalidate `RequestCache` entries: a query error cached while the kernel was
  dead stays until reload, and a later step that rebinds a dataset leaves
  earlier views stale.
- Make `npm run dev` views work inside the null-origin frame: Vite's dev CORS
  allowlist and its inline React preamble are both blocked there, so views
  render only from a production build today.
- A stale `session=` id in the hash opens a column on a 404; fall back to the
  first session.
- Disable the view's "Fix this view" after a successful repair, and clear a
  replay-failure banner once a later restart succeeds.
- `ErrorBoundary` resets only when the view id changes, and a store abandoned by
  a stale mount is not disposed, so its debounced change can still post.
- The Lightweight Charts attribution link is inert under the sandbox (no
  popups).
- Add component tests for `SessionPage` (reload keeps the session, 401 message),
  the time series success and "needs a date column" paths, and the canvas's
  debounced layout write and its flush on unmount.
- Extend lineage to SQL strings by passing string literals given to `sql_local`,
  `duckdb.sql` and `_conn.sql` through `duckdb.get_table_names`. Recipes from
  `sql_local` steps miss their source step until then. Such a recipe fails in
  the scratch kernel, so it is saved unvalidated with that reason and the gap is
  visible. Stage 2 replay may need it sooner.
- Cover the other lineage blind spots, helpers bound without `def` or `class`
  and attribute mutation. A recipe they break usually fails validation the same
  way.
- Let a cleanly exiting kernel finish before `close()` kills it after
  `shutdown()`, so an in-flight snapshot completes.
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
- Map `anthropic.APIError` and `openai.APIError` to a non-retryable
  `ProviderError` at the provider boundary. Until then, an unmapped SDK error
  escapes a save after its pinned parquet is written.
- Give recipe validation a timeout: `validate_recipe` waits on the scratch
  kernel, so a recipe that hangs hangs the save request, which is synchronous so
  that it can show a saving state. The session stays usable, since the hold is
  released first.
- A failed view recall keeps its view on the step, so the frame shows a query
  error under the recall's traceback.
- Canvas cards: a card is blank when its saved view fails to load, a card whose
  view is missing has no Remove, and recall and layout errors never clear.
- The rail's project list does not scroll, and `SaveDialog` picks its project
  only when it opens, so a project list that arrives later leaves none chosen.

### Any time

- Move CI to current `actions/checkout` and `astral-sh/setup-uv` versions, and
  add `permissions: contents: read`.
- Keep the version in one place: `pyproject.toml` and `src/quarry/__init__.py`
  both hold it, and the test checks only its type.
- Run mypy on `tests` as well as `src`.
- Open `config.toml` once in `load_config`: it checks `exists()`, opens the
  file, then stats it again for the DSN warning, so a file swapped in between is
  checked apart from what was read.
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
- **Restart UX**: restart always works, and it kills a running step. When the UI
  offers or forces a restart, and what the researcher sees meanwhile, is open.
- **Live provider calls**: neither adapter has called its real API. Whether the
  Anthropic API accepts `fallbacks="default"` with the
  `server-side-fallback-2026-07-01` beta, and whether `gpt-5` is the right
  OpenAI model name, is unverified. `tests/agent/test_live_providers.py` checks
  both once keys are set.
- **Exact class-body lineage**: keep over-reporting class-body reads, or add
  execution-order analysis covering conditionals, loops, `del` and `try`?
  Over-reporting adds recipe dependencies but never drops one.
- **Result streams on the shared connection**: should the kernel protect result
  streams left open across steps from later queries, or only document the limit?
  Neither option has been evaluated.
