# Handoff: implement Quarry Stage 5 (breadth)

Written 2026-10-09 for the thread that will build Stage 5. The plan is approved
and must be executed as written. This page gathers what that thread needs and
points at the files that hold the detail.

## Run this thread on Opus 5.5 at extra-high effort

Before any other step, set this session's model to Claude Opus 5.5
(`claude-opus-5-5`) and its effort to extra high (`xhigh`), and keep them for
the whole stage. Subagents dispatched for tasks and reviews inherit the session
model unless told otherwise; leave them on it.

## Wait before starting

Stage 5 builds on Stage 4, which is planned but not started: its earlier gated
thread was removed before Stage 3 merged, so a new thread must build it from the
[Stage 4 handoff](2026-10-08-quarry-stage4-handoff.md). Stages 1, 2 and 3 are on
`main` (sunpar/quarry#1 `d00b5fa`, #2 `7779c05`, #4 `faf913f`). Do not write
Stage 5 code until all of these hold:

- The pull request that implements the Stage 4 plan (expected branch
  `claude/quarry-stage4-projects`) is merged into `main`, and
  `git log --oneline -20 origin/main` shows its commits (`quarry.projects`,
  `ProjectService`, `ViewHost`, the canvas).
- Any pull request that one depends on is merged too.

Check with `gh pr list --repo sunpar/quarry --state all` and
`git fetch origin && git log --oneline -20 origin/main`. While waiting, read; do
not branch or edit. If a Stage 4 pull request is closed without merging, stop
and report rather than building on an unmerged branch.

## Start here, once unblocked

1. Read [docs/working-state.md](../../working-state.md) and compare it with
   `git log --oneline -5 origin/main` and `gh pr list`; trust git when they
   disagree.
2. Read [docs/context/constraints.md](../../context/constraints.md),
   [docs/context/decisions.md](../../context/decisions.md) (the first UI and
   projects sections), [docs/context/code-map.md](../../context/code-map.md) and
   [docs/open-items.md](../../open-items.md) (the Stage 4, Stage 5 and "Any
   time" lists are what this stage closes). The spec is binding; once work
   starts, decisions and code win over a plan.
3. Read the Stage 5 plan in full:
   [2026-10-09-quarry-stage5-breadth.md](../plans/2026-10-09-quarry-stage5-breadth.md).
   Every task carries its failing tests, implementation, commands and commit
   message. Follow the red step; do not merge tasks.
4. Before each task, re-read the real code it consumes on `main`. The plan was
   written against the Stage 3 and Stage 4 plans and verified against the Stage
   3 code on `main` at `faf913f` (differences listed below), but never against
   Stage 4 code. Where code differs, adjust the plan's TypeScript and Python to
   the code and record the departure in `docs/context/decisions.md`.
5. Load `superpowers:subagent-driven-development` (or
   `superpowers:executing-plans`), `superpowers:test-driven-development`,
   `superpowers:verification-before-completion`, and `anthropic-frontend-design`
   before any UI beyond what the plan specifies.

## Repository context

- Repo `~/workspace/quarry`, GitHub `sunpar/quarry` (public). `main` holds the
  spec, five stage plans, three handoffs, Stages 1 to 3, the docs convention
  (sunpar/quarry#3) and a Claude Code workflow (sunpar/quarry#5). Name the
  branch `claude/quarry-stage5-breadth`; if the stage ships as two pull requests
  (the plan allows Tasks 1 to 7, then 8 to 13), name the second
  `claude/quarry-stage5-host`.
- Stage 3 code on `main` differs from the plan's assumptions in four places. The
  plan's Task 2 already handles the first three; the fourth changes Task 7:
  - `web/src/runtime/hooks.ts` `useQuery` returns
    `{status: "error", message: 'views cannot use format "arrow"'}` when `rows`
    is null. Task 2 replaces that guard with the `arrow: ArrayBuffer | null`
    field.
  - `web/src/runtime/state.ts` has no `flush`; nothing reports state after
    mount. Task 2 Step 3b adds the one-shot report; it is needed, not optional.
  - `web/runtime.html` carries the Stage 3 CSP with `connect-src 'none'`; Task 2
    Step 1 replaces it.
  - `src/quarry/server/app.py` serves the static bundle as
    `app.mount("/", CORSMiddleware(StaticFiles(...), allow_origins=["*"]))`
    (user-approved, recorded in decisions). There is no `STATIC_PREFIXES`
    middleware. Task 7's `mount_licensed` must wrap each `/libs/<id>`
    `StaticFiles` in the same `CORSMiddleware(..., allow_origins=["*"])` and
    mount it before the `/` mount; the plan's test that checks
    `access-control-allow-origin: *` on `/libs/highcharts/highstock.js` stands.
- Stage 3 code the plan consumes, as found on `main`:
  `web/src/runtime/{modules.ts,loader.ts,mount.tsx,bridge.ts,cache.ts,state.ts,hooks.ts,libraries.ts}`
  (`MODULES` also lists `@/components/ui/textarea` and `scroll-area`; keep
  them), `web/src/host/bridge/HostBridge.ts`,
  `web/src/host/containers/{ViewFrameContainer,SessionPage,StepList}.tsx`,
  `web/src/host/components/{StepCard,CodeDrawer,PromptBox,KernelBanner,...}.tsx`,
  `web/src/host/api/{client,hooks,keys,context}.ts`, `src/quarry/server/app.py`
  (snapshots route at `POST /sessions/{id}/steps/{step_id}/snapshots`),
  `src/quarry/agent/context.py` (`runtime_libraries`,
  `enabled_libraries(config, available)`),
  `src/quarry/components/builtin/{data-table,time-series}`,
  `tests/e2e/{conftest,test_ui}.py`.
- Stage 4 code the plan consumes, as planned (re-read the real files):
  `quarry.projects.{models,store,files,recipe,tidy,validate}`,
  `quarry.server.projects.ProjectService` (`hold`, `save_view` writing
  `queries.json`, `recall`), `quarry.server.project_routes` (`_found`,
  `_saving`), `SavedViewFiles {meta, source, state, queries}`, host `ViewHost`,
  `StepActions`, `SaveDialog`, `ProjectPage`, `SavedItems`, `useProjects` and
  friends. If Stage 4 shipped without `queries.json` (its handoff predates the
  amendment in `1edbd91`), add it as the Stage 4 plan's Task 1 describes before
  Task 6 here.
- Stage 1 and 2 code the plan changes: `src/quarry/query/source_target.py`
  (`to_source`),
  `src/quarry/kernel/{datasets,executor,lineage,service,client}.py`,
  `src/quarry/server/service.py` (`SessionStatus`), `src/quarry/cli.py`,
  `src/quarry/components/library.py`, `src/quarry/config.py` (`LibrariesConfig`,
  unchanged).
- Library facts probed on this machine on 2026-10-09 (copy the plan's code; do
  not substitute remembered APIs): Perspective 3.8.0
  (`init_server`/`init_client` take a `fetch(wasmUrl)` promise,
  `perspective.worker()` creates a Blob-URL module worker, viewer
  `load/restore/save/delete`, `perspective-config-update` event,
  `ViewerConfigUpdate` with `filter: [col, op, term][]`, `sort: [col, dir][]`,
  `aggregates`, `expressions: {[name]: string}`); TanStack Table 9.2.8
  (`useTable`, `tableFeatures`, `rowSortingFeature`, `createColumnHelper` all
  exported from `@tanstack/react-table`; `<table.FlexRender cell={cell} />`);
  Highcharts 13.1.1 `highstock.js` UMD sets `window.Highcharts`; SciChart 6.0.6
  single-file `index.min.mjs`, wasm under `_wasm/scichart.wasm`, statics
  `SciChartSurface.configure({wasmUrl})` and `setRuntimeLicenseKey`; polars 2.0
  `write_ipc(compat_level=pl.CompatLevel.oldest())` still emits `large_string`,
  and pyarrow 25 cannot read polars Int128; DuckDB 1.5.6
  `conn.get_table_names(sql)` binds the statement (unknown plain names bind to
  placeholders, a bad `read_parquet` glob raises `IOException`); `nbformat`
  5.11.1.

## Execution order

Thirteen tasks; kernel and server first, the runtime proof second so the
riskiest piece (Perspective under the sandbox CSP) is known early.

| #   | Task                                               | Produces                                                                                                                     |
| --- | -------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| 1   | Arrow transport                                    | `quarry.kernel.arrow.{for_viewer,arrow_ipc}`: casts to Perspective-readable types, IPC stream, `string` not `large_string`   |
| 2   | Runtime CSP, Perspective wrapper, Playwright proof | Amended CSP and spec sections 9/12, `useQuery(...).arrow`, mount-time state report, `@quarry/perspective`, e2e proof         |
| 3   | `to_source` hardening, kernel `to_code`, route     | `QueryError` only, ASCII identifiers, `relation_projection` for INTERVAL, `POST /sessions/{id}/to-code`                      |
| 4   | Lineage gaps, busy flag                            | SQL string literals through DuckDB's binder, attribute and subscript mutation as stores, `SessionStatus.busy`                |
| 5   | Save generated components                          | `POST /components` (409 on any existing id), `GET /components`, `requirements_for`, `write_component`                        |
| 6   | Export and CLI                                     | nbformat 4.5 notebook, `.py` script, `GET /projects/{slug}/export.ipynb`, `.../recipe.py`, `quarry projects list\|export`    |
| 7   | Licensed libraries                                 | `licensed_libraries`, `/libs/<id>/` mounts with CORS, `GET /libraries`, key-without-path warning, guide gating               |
| 8   | Runtime module table and guide                     | Plotly, ECharts, Recharts, TanStack, d3, Highstock (classic script), SciChart (module) in `MODULES`; `mount.licensed`; guide |
| 9   | Perspective mapping and pivot built-in             | `perspectiveToSpec` (lossy, `dropped` list), `pivot` built-in with the one-row probe query                                   |
| 10  | TanStack table and OHLC built-ins                  | `data-table-tanstack`, `ohlc`                                                                                                |
| 11  | Recharts, Plotly, ECharts built-ins                | `bar-line`, `scatter`, `heatmap`, `large-series`                                                                             |
| 12  | Host actions                                       | To code drawer → manual step, Save to library dialog, export and recipe downloads, prompt box disabled while busy            |
| 13  | End-to-end, docs, CI                               | Playwright to-code and save-to-library flows; docs; `permissions: contents: read`, pinned actions, `mypy src tests`          |

## Architecture and constraints agreed

- Runtime CSP becomes
  `default-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; worker-src blob:; style-src 'self' 'unsafe-inline'; img-src data: blob:; font-src 'self'; connect-src 'self'`.
  "No network" now means nothing beyond the server's own static files; API
  routes need the bearer token the frame never holds. Spec sections 9 and 12 are
  amended in Task 2. If the Blob-URL worker is refused, serve Perspective's
  worker from the bundle and drop `worker-src blob:`; never widen `script-src`.
- `format: "arrow"` is an Arrow IPC stream at `CompatLevel.oldest()` after
  casts: Decimal and 128-bit integers to Float64, Categorical/Enum/Duration/Time
  to String, Binary to base64 text, nested to JSON strings, `large_string`
  narrowed to `string`. Arrow is a display transport; JSON rows stay the exact
  ones.
- `to_source` raises only `QueryError`; identifiers are ASCII
  `[A-Za-z_][A-Za-z0-9_]*` and not keywords; a DuckDB relation renders through
  `rel.project(<importable projection>)` so INTERVAL and UNION columns import.
  "To code" renders in the kernel with the live schema; export renders saved
  queries without one and says so in a comment.
- Lineage: string literals passed to `sql_local(...)` or any `.sql(...)` call go
  to DuckDB's binder for table names, kept when they were datasets before the
  step; a literal that fails to bind adds nothing. Module-level attribute and
  subscript assignment stores the root name; inside a function it is only a
  read.
- Perspective to query spec is lossy and deterministic: the plan's table in Task
  9 is the mapping; what is dropped is listed in view state under `dropped`. The
  pivot built-in issues a one-row probe of the mapped spec so the kernel
  validates it and it reaches lineage and "to code".
- Generated components save under `<root>/components/<id>/` with
  `origin: "generated"` and requirements derived from the dataset's dtype
  classes; ids match `^[a-z0-9][a-z0-9-]{0,63}$`; any existing id in any root is
  a 409.
- Licensed libraries are never in `package.json`; they load from the
  researcher's install under `/libs/<id>/` only when both the key and the path
  are configured and the entry file exists. A key without a path warns once and
  stays disabled. The key reaches the browser through `GET /libraries` and the
  mount message; it is never logged.
- Export is nbformat 4.5 JSON built by hand (cell ids, `kernelspec`,
  `language_info`), validated by `nbformat` in tests only; datasets first, then
  views (markdown, query source, fenced TSX).
- Code rules unchanged: TypeScript strict, no `any`, `interface` for props, no
  `React.FC`, files under 250 lines (built-ins cannot share files at runtime, so
  helpers are copied, not imported), prettier on everything; Python typed, ruff,
  mypy strict on `src` and `tests`. Commits: bare Conventional Commit types, no
  scopes, no attribution trailers; never put a heredoc in the same shell command
  as `git commit`.

## Acceptance criteria

- Perspective mounts inside the sandboxed frame over an Arrow result with
  String, Date, Datetime, Decimal and Categorical columns, with no CSP or CORS
  console errors.
- "To code" on any built-in produces Python that runs as a manual step,
  including a DuckDB relation with an INTERVAL column.
- A custom view saved to the library appears in `GET /components` and in
  `search_components` on the next step; a built-in id is refused.
- `quarry projects export <slug>` and the export route produce a notebook that
  validates and runs; the recipe route serves a runnable script.
- With a license key and a real install path, `/libs/<id>/` serves the package
  with the CORS header and the guide lists the library; with a key alone it
  stays disabled with one warning.
- All nine built-ins in spec section 9 exist with manifests and tests, and push
  grouping, filtering and sorting into their query specs.
- `uv run pytest` (including `tests/e2e`), ruff, `mypy src tests`,
  `npm run check`, `npm test` and `npm run build` pass locally and in CI.

## Required tests

- pytest: Arrow casts and stream format; `to_source` QueryError cases, ASCII
  identifiers, malformed literal with schema, relation projection executed;
  executor `to_code` with live schema and errors; client round trip; to-code
  route codes; lineage SQL literals and mutation; executor SQL reads and
  mutation writes; status `busy`; library `requirements_for`, `write_component`,
  id pattern; component routes (201, 409 twice, 400 id, 400 transpile, 404);
  export notebook validates and runs, script header, pinned note; export routes;
  CLI list and export; licensed library statuses, mount with CORS, 401,
  unlicensed 404; guide filtering; built-in id set.
- vitest: base64; `useQuery.arrow`; mount-time state report; registry; Highstock
  loader; module table coverage; `perspectiveToSpec` (flat, grouped, pivot,
  dropped order, default count); pivot, TanStack table, OHLC, bar-line, scatter,
  heatmap, large-series built-ins; client
  `toCode`/`saveComponent`/`fetchBlob`/`libraries`; download helper with fake
  timers; `ToCodeDrawer`; `SaveComponentDialog`.
- Playwright: Perspective in the sandbox (Task 2); bar-line → To code → manual
  step runs; custom view → Save to library (Task 13).

## Known risks

- The Perspective worker under `sandbox="allow-scripts"` is the one unproven
  piece; Task 2 proves it before anything depends on it, with the bundled-worker
  fallback described in the plan.
- Perspective's datagrid renders inside an open shadow root; if the Playwright
  header locator cannot see it, assert through `getTable().size()` as the plan
  says.
- `@tanstack/react-table` 9 is a rewrite; if `meta` on column defs or
  `enableSorting` is typed differently, follow the plan's fallbacks (module
  augmentation; drop the option).
- `get_table_names` binds against the kernel connection; a literal naming a
  table function over a missing path raises and is skipped, which hides nothing
  the recipe needed.
- The mount-time state report adds one snapshot per mount; the snapshots route
  accepts repeats. If snapshot lists grow noticeably, de-duplicate identical
  consecutive states server-side (a one-line check in the Stage 3 route).
- Export without a schema can render `ret in [0]` against a float column; the
  notebook's comment says to use "To code" for an exact rendering.

## Unresolved questions

- Whether SciChart's `UseCommunityLicense()` should be offered when no key is
  set. The spec says disabled without a key; keep it so unless the maintainer
  asks.
- Whether a saved component should also be re-mountable from the step card ("Use
  my-scatter"); the agent's `render_view` already can, so the host button is a
  convenience left out.

## Rejected alternatives

- Keeping `connect-src 'none'` with Perspective's inline builds: rejected; the
  engine worker still comes from a Blob URL and the wasm still needs a fetch.
- `highcharts-react-official` and `scichart-react` as bundled wrappers:
  rejected; both would pull the licensed library into the wheel as a peer.
  `@quarry/highcharts` is a 40-line wrapper, and SciChart is used directly.
- Highcharts as ESM `es-modules/masters/highstock.src.js`: rejected; hundreds of
  cross-origin module fetches from the sandbox. The UMD script is one request.
- Exporting with a reconstructed polars schema from dtype strings: rejected; a
  parser nobody needs yet.
- A fourth hook (`useRecordedQuery`) for the Perspective mapping: rejected; the
  one-row probe query records and validates the mapped spec with the existing
  hook.
- NFKC normalisation of identifiers in `to_source`: subsumed by the ASCII rule.

## After Stage 5

Update [docs/working-state.md](../../working-state.md), the
[code map](../../context/code-map.md), [decisions](../../context/decisions.md)
(CSP amendment, Arrow transport, Perspective mapping, ASCII identifiers,
licensed libraries, nbformat), the [glossary](../../context/glossary.md), and
[open-items.md](../../open-items.md) (remove the Stage 5 list; move the plan's
deferrals to "Any time" with reasons). Stage 5 is the last planned stage; what
remains after it is the spec's section 16 deferrals and the open questions.
