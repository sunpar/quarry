# Handoff: implement Quarry Stage 3 (first UI)

Written 2026-10-08 for the thread that will build Stage 3. The plan is approved
and must be executed as written; this page gathers everything that thread needs
in one place and points at the files that hold the detail.

## Start here

1. Read [docs/working-state.md](../../working-state.md) and compare it with
   `git log --oneline -5 origin/main` and `gh pr list`; trust git when they
   disagree.
2. Read [docs/context/constraints.md](../../context/constraints.md) and
   [docs/context/decisions.md](../../context/decisions.md). The spec is binding;
   where the plan and the code disagree once work starts, decisions and code
   win.
3. Read the Stage 3 plan in full:
   [2026-10-08-quarry-stage3-first-ui.md](../plans/2026-10-08-quarry-stage3-first-ui.md).
   Every task carries its failing tests, implementation, commands and commit
   message. Follow the red step; do not merge tasks.
4. Load `superpowers:subagent-driven-development` (or
   `superpowers:executing-plans`), `superpowers:test-driven-development`,
   `superpowers:verification-before-completion`, and `anthropic-frontend-design`
   before touching any UI beyond what the plan specifies.

## Repository context

- Repo `~/workspace/quarry`, GitHub `sunpar/quarry` (public). `main` holds the
  spec, the three stage plans, Stage 1 (merged in sunpar/quarry#1, `d00b5fa`)
  and the docs convention (sunpar/quarry#3, `d821da4`).
- Stage 2 (server and agent) is on `claude/quarry-stage2-server-agent-66853b`,
  sunpar/quarry#2, open, CI green, head `08efb23` at the time of writing. Stage
  3 builds on it. Branch from it, or from `main` once it merges.
- The Stage 3 plan was written against that branch's actual code, not the Stage
  2 plan. These are the files it consumes:
  - `src/quarry/server/app.py`:
    `create_app(*, config, token, provider_factory, static_dir=None)`, serves
    `src/quarry/static/` at `/` when `index.html` exists; bearer auth on
    everything except `GET /healthz`.
  - `src/quarry/server/service.py`: `SessionService`, `StepRequest {prompt}`,
    `SessionStatus {session_id, running_step, kernel, last_error}`,
    `interrupt() -> bool`, `_system_context()` builds the system prompt.
  - `src/quarry/server/store.py`: `SessionStore` with `append_step`,
    `_write_atomic`.
  - `src/quarry/server/models.py`: `Step`,
    `View {component_id, content_hash, source, initial_state, datasets, snapshots}`,
    `Snapshot {ts, state, queries}`, `Session`, `KernelStatus`.
  - `src/quarry/server/kernels.py`:
    `ReplayReport {replayed, failed_step, error}` returned by `POST /restart`.
  - `src/quarry/agent/tools.py`: `render_view` and `write_view` take
    `initial_state` as a JSON string; `PendingView`.
  - `src/quarry/agent/context.py`: `CONTRACT`, `ALWAYS_ON`,
    `enabled_libraries(config)`.
  - `src/quarry/agent/transpile.py`: `default_transpiler(static_dir)` runs
    `node static/transpile-check.mjs` when it exists.
  - `src/quarry/components/library.py`: `ComponentLibrary`, `builtin_root()`
    (empty directory today).
  - `src/quarry/query/spec.py`, `src/quarry/kernel/datasets.py`,
    `src/quarry/kernel/executor.py`: the pydantic models the TypeScript types
    mirror (`QuerySpec`, `DatasetMeta`, `QueryResult`, serialised with `schema`,
    not `schema_`).
- Routes and status codes: `POST /sessions` 201; `POST /sessions/{id}/steps` 202
  or 409 when busy; `POST /sessions/{id}/query` takes a raw dict and returns 400
  on validation, 503 when the kernel is dead; `POST /sessions/{id}/restart` 409
  busy or 503. `GET /sessions/{id}` includes the in-memory running step.
- No `web/` directory and no `src/quarry/static/` exist yet. `.gitignore`
  already excludes `web/node_modules/`, `web/dist/`, `src/quarry/static/`.

## Execution order

Twelve tasks, runtime before host so a mid-plan stop still leaves usable pieces.
Each ends in one commit with the message given in the plan.

| #   | Task                                                 | Produces                                                                                                                                            |
| --- | ---------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- |
| 1   | Web scaffold, tokens, build into the package         | `web/` Vite project with `index.html` and `runtime.html` entries, design tokens, shadcn components, build to `src/quarry/static`, wheel `artifacts` |
| 2   | Shared types, token, API client, query keys          | TS mirrors of the pydantic models, `readToken`, `ApiClient` (one method per route), `keys`                                                          |
| 3   | Node transpile checker and runtime manifest gate     | `static/transpile-check.mjs`, `static/runtime-manifest.json`, `runtime_libraries()`, `enabled_libraries(config, available)`                         |
| 4   | Runtime loader and module table                      | `loadComponent(source, table)` over Sucrase with an allowlisted `require`; `MODULES`                                                                |
| 5   | Runtime bridge, view state, query cache, hooks       | `RuntimeBridge`, `ViewStateStore` (300 ms debounce), `RequestCache`, `useQuery`, `useViewState`, `useDatasetSchema`                                 |
| 6   | Runtime entry: mount, restore, error boundary        | `createRuntime(post, root)`, `ready` on load, `error` on load or render failure                                                                     |
| 7   | Host bridge and view frame                           | `HostBridge` (source check, correlation ids, ready handshake), `ViewFrame` iframe with error overlay                                                |
| 8   | Built-ins: data table and time series                | `src/quarry/components/builtin/{data-table,time-series}/` with manifests; `datasets: string[]` prop line in `CONTRACT`                              |
| 9   | Server: snapshots, repair prompts, atomic updates    | `SessionStore.update_step`, `POST /sessions/{id}/steps/{step_id}/snapshots`, `StepRequest.repair`                                                   |
| 10  | Host app: shell, sessions, step column, prompt, poll | `ApiProvider`, React Query hooks, rail, step cards, code drawer, prompt box with Stop, polling at 750 ms while running                              |
| 11  | Host app: live views, fix this, kernel restart       | `ViewFrameContainer` (one bridge per view, snapshots posted), "Fix this view" repair, `KernelBanner` with "Restart kernel"                          |
| 12  | Playwright end-to-end, CI, README                    | `tests/e2e` with uvicorn in a thread and `FakeProvider`, CI building web before Python checks, README dev loop                                      |

## Architecture and constraints agreed

- One Vite project, two HTML entries: host app (React 19, React Query v5,
  shadcn/ui on Tailwind 4) and iframe runtime (Sucrase transpile at mount,
  allowlisted `require`, lazy chunks per chart library).
- The iframe is `sandbox="allow-scripts"` only, never `allow-same-origin`, with
  meta CSP
  `default-src 'none'; script-src 'self' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; img-src data:; font-src 'self'; connect-src 'none'`.
  `'unsafe-eval'` is required for `new Function` over Sucrase output; the jail
  is the sandbox plus `connect-src 'none'`.
- The frame's origin is opaque: host to runtime `postMessage` uses target origin
  `"*"`, and the host trusts a message only when
  `event.source === iframe.contentWindow`. `event.origin` is the string `"null"`
  and must never be checked.
- The host alone holds the bearer token. It is read from `location.hash` once,
  kept in memory, and the fragment stays in the URL so a reload still works. No
  cookie, no `localStorage`.
- Bridge surface, nothing more: host to runtime `mount`, `restore`,
  `queryResult`, `schemaResult`; runtime to host `ready`, `query`, `schema`,
  `stateChanged`, `error`. Every message but `ready` carries `viewId`.
  `queryResult` carries the server's `QueryResult` verbatim.
- A view's default export receives one prop, `datasets: string[]`, in the order
  passed to `render_view` or `write_view`. Built-ins read `datasets[0]`.
- `useQuery` success adds `rowCount` and `truncated` to the spec's
  `{rows, schema}` so built-ins can show the truncation banner. `useViewState`
  keys starting with `shared:` are recorded now; linked behaviour is Stage 4.
- Snapshot recording lands now (`stateChanged` debounced at 300 ms, host posts
  to the snapshots endpoint, server keeps the last 500 per view). The scrubber
  UI is Stage 4.
- The system prompt advertises only chart libraries the built runtime can
  resolve: the web build emits `runtime-manifest.json` and `enabled_libraries`
  intersects with it. Stage 3's runtime resolves `ag-grid` and
  `lightweight-charts`.
- The wheel carries the UI only because `[tool.hatch.build.targets.wheel]` lists
  `artifacts = ["src/quarry/static/**"]`; hatchling honours `.gitignore`. The
  web build must run before `uv build`; CI does so.
- Code rules: TypeScript strict, no `any`, `interface` for props, no `React.FC`,
  discriminated unions for request state, `useEffect` only for the bridge
  listeners and the Lightweight Charts container, files under 250 lines,
  prettier on everything, `tsc -b` clean. Python keeps the Stage 1 and 2 rules
  (typed, ruff, mypy strict).
- Commits: bare Conventional Commit types only (`feat`, `fix`, `refactor`,
  `docs`, `style`, `test`, `build`), no scopes, no attribution trailers; the
  pre-commit hook rejects both.
- Design tokens are fixed in the plan: IBM Plex Sans and Mono, limestone
  background `#EEF0F2`, ink `#1C2127`, serpentine accent `#1E6E63`, iron oxide
  error `#9A3B2E`, mica interrupted `#B8860B`; ledger-style step column with an
  index in the margin and a 3 px status rule, no cards, no shadows, sentence
  case, no uppercase labels. Buttons: "Run", "Stop", "Restart kernel", "Fix this
  view", "New session".

## Dependencies and versions

Probed on 2026-10-08 with a fresh `npm create vite` and
`npx shadcn@latest init`; the plan's code targets these APIs. Do not substitute
remembered ones.

| Package                            | Version | Notes                                                                                         |
| ---------------------------------- | ------- | --------------------------------------------------------------------------------------------- |
| vite                               | 8.3     | rolldown based; `esbuild` is a dev dependency only to bundle the node checker                 |
| react, react-dom                   | 19.3    |                                                                                               |
| typescript                         | 6.0     | `erasableSyntaxOnly`, `noUncheckedIndexedAccess` on                                           |
| tailwindcss, @tailwindcss/vite     | 4.3     | `@source inline(...)` safelist for layout utilities in generated views                        |
| shadcn                             | 4.21    | `base-nova` style, components import `@base-ui/react/*` and `cn` from the `cn` package        |
| @tanstack/react-query              | 5.104   |                                                                                               |
| sucrase                            | 3.35    | transforms `typescript`, `jsx`, `imports`; `jsxRuntime: "automatic"`                          |
| ag-grid-community, ag-grid-react   | 36.2    | `ModuleRegistry.registerModules([AllCommunityModule])`, `theme={themeQuartz…}`, no CSS import |
| lightweight-charts                 | 5.2     | `chart.addSeries(LineSeries, …)`; keep `attributionLogo: true`                                |
| @fontsource/ibm-plex-sans, -mono   | current | bundled, no network                                                                           |
| vitest, @testing-library/react     | 5, 16   | jsdom 29                                                                                      |
| pytest-playwright (Python dev dep) | 0.10    | `uv run playwright install chromium`                                                          |

Environment: `python` does not exist on the dev Mac, use `uv run` or
`python3.11`; Node 24 and npm, no pnpm; macOS has no `timeout`. The pre-commit
hook misparses a heredoc Python script placed in the same shell command as
`git commit`; run scripts separately.

## Acceptance criteria

Stage 3 is done when all of these hold, on the branch and in CI:

- `quarry serve` opened from its printed link lets a researcher create a
  session, run a prompt, see the step with its note, dataset chips and collapsed
  code drawer, and interact with the table or chart.
- A refused import or render error shows in the view slot with "Fix this view",
  which starts a repair step whose prompt carries the view source and the error.
- Reloading the page mid-step resumes polling with the token intact; the prompt
  box stays disabled until the step finishes.
- A dead kernel shows "Restart kernel"; restart replays steps and the banner
  clears.
- `useViewState` changes land in the step's `view.snapshots` on disk.
- The table shows a banner when a result is truncated.
- `npm run check`, `npm test`, `npm run build`, `uv run pytest` (including
  `tests/e2e`), ruff and mypy pass; the wheel contains
  `quarry/static/index.html`.

## Required tests

Each is written before its implementation, as laid out per task in the plan.

- Vitest: `readToken`; `ApiClient` headers, error mapping, query body;
  `loadComponent` (transpile, refused import message, missing default export,
  syntax error); `RuntimeBridge` (correlation, foreign ids, `stateChanged`
  carrying issued specs); `ViewStateStore` (debounce, `replace`); hooks (loading
  to success, dedupe, re-query on state change, schema); runtime mount (`ready`,
  mount with datasets, restore, render error, refused import); `HostBridge`
  (mount after ready, source check, forwarding, error results); `PromptBox`;
  `StepCard`; `useSession` polling; `ViewFrameContainer` (snapshot post, error
  overlay, repair callback); the two built-ins with the hooks and chart
  libraries stubbed.
- pytest: `default_transpiler` using the real bundle (skipped without a build);
  `runtime_libraries` and the `enabled_libraries` gate; builtin library lists
  `data-table` and `time-series`; `CONTRACT` mentions `datasets: string[]`;
  `SessionStore.update_step`; snapshot endpoint (append, 404 without a view);
  repair prompt contents.
- Playwright (`tests/e2e`, skipped without a build): table round trip through a
  scripted `FakeProvider`; refused import shows "Fix this view" and the repair
  step completes.

## Known risks

- CSP `'self'` under the opaque sandbox origin. Chromium resolves it from the
  document URL, which the Playwright test proves. If chunks fail to load, the
  fallback is an explicit loopback host-source with a port wildcard
  (`script-src 'self' http://127.0.0.1:* http://localhost:*`, same for
  `style-src` and `font-src`). A response header is not a fallback; it resolves
  `'self'` the same way.
- Tailwind cannot scan generated views. The runtime CSS safelists common layout
  utilities with `@source inline(...)`; an agent-written class outside that set
  simply has no effect. `@tailwindcss/browser` (runtime JIT) is the upgrade if
  this bites, not scope for Stage 3.
- AG Grid and Lightweight Charts are stubbed in vitest; real rendering,
  including sort pushing into the query spec, is covered only by the Playwright
  test. Adding a header click and asserting a second `/query` with `sort` is
  optional.
- `ViewFrameContainer`'s effect keys on `content_hash`, not the `view` object,
  because snapshots mutate `step.view` on every poll. Keep that or every state
  change remounts the view.
- `schemaFor` resolves from `step.datasets` first and only then from the API
  with `staleTime: 0`; a cached dataset list from an earlier step would make the
  time series report a missing date column.
- The `ready` handshake has a narrow race (host listener attached in an effect,
  runtime posts `ready` when its module script runs). The effect wins in
  practice; the plan describes the `load` listener fix if the e2e flakes.
- uvicorn runs in a daemon thread in the e2e fixture; this needs uvicorn 0.29+
  (signal handlers are skipped off the main thread).
- Stage 1 open items filed under Stage 3 in
  [docs/open-items.md](../../open-items.md#stage-3) are not in this plan:
  default ordering of group-by and pivot rows, paged-sort tie-breakers, filter
  coercion gaps, the JSON row contract (decimals as strings, large integers),
  eager pivots. The data table sorts and limits but does not page with offsets,
  so the ordering items do not block Stage 3; the JSON contract shows up as
  string-typed sums in the table and is acceptable for the first UI.

## Unresolved questions

- JSON row contract with the renderer (see open items): parse by schema dtype in
  the browser, send large integers as strings, or move exact values to Arrow.
  Stage 3 renders what arrives; the decision belongs to Stage 5 with Perspective
  and Arrow transport.
- Interrupt and restart UX: the plan shows a banner only when the kernel is
  dead. How to explain an interrupt that does not stop a running `collect()`
  (open item) is not designed; Stage 3 shows "Stopped" when the step ends.
- Dark mode: tokens for `.dark` stay as shadcn generated; no toggle in Stage 3.

## Rejected alternatives

- Infinite Observable-style canvas: rejected for a snap-to-grid dashboard (Stage
  4), because data views need a legible native size.
- JSON-spec view renderer: rejected in favour of agent-written TSX rendered at
  runtime.
- `allow-same-origin` on the iframe, or a CSP without `'unsafe-eval'`: rejected;
  Sucrase output needs `new Function`, and the sandbox is the jail.
- Stripping the token fragment with `history.replaceState`: rejected because a
  reload would lose the token; fragments never reach the server anyway.
- Re-deriving `queryResult` into flat fields on the bridge: rejected; the host
  already holds the server's `QueryResult`, so it is forwarded verbatim.
- A separate status query to drive the step column: rejected;
  `GET /sessions/{id}` already includes the running step, so the session query
  polls itself while the last step is running and status is polled only for
  kernel state.
- `@tailwindcss/browser` in the runtime: deferred, not rejected; the safelist
  covers Stage 3.
- Vega-Lite, Highcharts and SciChart bundled by default: settled earlier (spec
  §3); Highcharts and SciChart are opt-in with a bring-your-own license.

## After Stage 3

Update [docs/working-state.md](../../working-state.md) (status row, latest
verification, next actions), add `quarry.server` snapshot and repair entries
plus a `web/` section to [docs/context/code-map.md](../../context/code-map.md),
record any departure from the plan in
[docs/context/decisions.md](../../context/decisions.md), and resolve the Stage 3
items in [docs/open-items.md](../../open-items.md). Stage 4 (projects and
canvas) needs its plan written from the spec and from the real Stage 3 code.
