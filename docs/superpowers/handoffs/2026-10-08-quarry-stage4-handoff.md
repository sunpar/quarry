# Handoff: implement Quarry Stage 4 (projects and canvas)

Written 2026-10-08 for the thread that will build Stage 4. The plan is approved
and must be executed as written. This page gathers what that thread needs and
points at the files that hold the detail.

## Wait before starting

Stage 4 builds on Stage 3, which builds on Stage 2. Neither is on `main` yet. Do
not write Stage 4 code until all of these hold:

- sunpar/quarry#2 (Stage 2, `claude/quarry-stage2-server-agent-66853b`) is
  merged into `main`.
- sunpar/quarry#4 (Stage 3, `claude/quarry-stage3-first-ui`) is merged into
  `main`. Its base is the Stage 2 branch today; it retargets to `main` after #2
  merges.
- Any other pull request that #4 or its base branch depends on is merged, and
  `git log origin/main` shows the Stage 3 commits.

Check with `gh pr view 2 --repo sunpar/quarry --json state,mergedAt` and the
same for #4, then `git fetch origin && git log --oneline -15 origin/main`. While
waiting, read; do not branch or edit. If a check shows a PR closed without
merging, stop and report rather than building on an unmerged branch.

## Start here, once unblocked

1. Read [docs/working-state.md](../../working-state.md) and compare it with
   `git log --oneline -5 origin/main` and `gh pr list`; trust git when they
   disagree.
2. Read [docs/context/constraints.md](../../context/constraints.md),
   [docs/context/decisions.md](../../context/decisions.md) and the Stage 3
   additions to [docs/context/code-map.md](../../context/code-map.md). The spec
   is binding; once work starts, decisions and code win over a plan.
3. Read the Stage 4 plan in full:
   [2026-10-08-quarry-stage4-projects.md](../plans/2026-10-08-quarry-stage4-projects.md).
   Every task carries its failing tests, implementation, commands and commit
   message. Follow the red step; do not merge tasks.
4. Before Task 7, and again before Task 8, re-read the real Stage 3 code on
   `main`: `web/src/host/bridge/HostBridge.ts`,
   `web/src/host/containers/ViewFrameContainer.tsx`, `web/src/host/api/*`,
   `web/src/host/components/{StepCard,SessionRail,DatasetChips}.tsx`,
   `web/src/host/App.tsx`, and `src/quarry/server/{service,app,store}.py`. The
   plan was written against the Stage 3 plan, not Stage 3 code; where they
   differ, adjust the plan's TypeScript and Python to the code and record the
   departure in `docs/context/decisions.md`.
5. Load `superpowers:subagent-driven-development` (or
   `superpowers:executing-plans`), `superpowers:test-driven-development`,
   `superpowers:verification-before-completion`, and `anthropic-frontend-design`
   before any UI beyond what the plan specifies.

## Repository context

- Repo `~/workspace/quarry`, GitHub `sunpar/quarry` (public). `main` holds the
  spec, four stage plans, two handoffs, Stage 1 (sunpar/quarry#1) and the docs
  convention (sunpar/quarry#3).
- Stage 2 is sunpar/quarry#2; Stage 3 is sunpar/quarry#4, built by a separate
  thread from the Stage 3 handoff. Stage 4 branches from `main` after both
  merge. Name the branch `claude/quarry-stage4-projects`.
- Stage 2 code the plan consumes (verified on branch head `08efb23`):
  - `src/quarry/server/service.py`: `SessionService` with `_begin`, `_start`,
    `_run_manual`, `_finish`, `restart`, `get`, `datasets`, `status`; the
    `_running` dict uses `None` as the "busy, no step" marker.
  - `src/quarry/server/models.py`: `Step` with `runs: list[CodeRun]`, `View`,
    `Snapshot`; `src/quarry/agent/tools.py`: `CodeRun {code, status}`.
  - `src/quarry/server/kernels.py`: `KernelManager.restart` replays `runs`.
  - `src/quarry/kernel/client.py`: `KernelClient.spawn(root, threads=)`,
    `execute`, `describe` (counts rows), `snapshot(name, path)`, `shutdown`,
    `close`, `KernelDead`, `RpcFailure`.
  - `src/quarry/agent/types.py`:
    `Provider.complete(*, system, messages, tools)`, `ProviderError`;
    `src/quarry/agent/fake.py`: `FakeProvider`.
  - `src/quarry/agent/loop.py`: `step_lineage` folds per-run reads so a read
    satisfied inside the same step is not a step read.
  - `src/quarry/kernel/datasets.py`: `describe` reports `height` for an eager
    frame even with `count_rows=False`; lazy frames and relations get `None`.
- Stage 3 code the plan consumes (as planned; re-read the real files):
  `HostBridge`, `ViewFrame`, `ViewFrameContainer`, `ApiClient`, `keys`, React
  Query hooks, `StepCard`, `StepList`, `SessionRail`, `SessionPage`, `App`;
  Python `StepNotFound`, `SessionStore.update_step`, the snapshots route; the
  `serve` Playwright fixture and helpers in `tests/e2e`.

## Execution order

Twelve tasks, Python first so the API is complete before the host changes.

| #   | Task                                        | Produces                                                                                                   |
| --- | ------------------------------------------- | ---------------------------------------------------------------------------------------------------------- |
| 1   | Project models and store                    | `quarry.projects.{models,files,store}`, spec section 5 layout, slug rules, atomic writes                   |
| 2   | Recipe walk                                 | `recipe_steps`, `raw_recipe`: dependency closure in index order, `ok` runs only                            |
| 3   | Tidy through the provider                   | `tidy_recipe` with fence stripping and a binds-the-name check; Anthropic adapter omits empty `tools`       |
| 4   | Validation in a scratch kernel              | `validate_recipe` comparing schema and row count with the live `describe`                                  |
| 5   | Project service: save dataset and view      | `ProjectService`, `SessionService._busy` and `hold`, tidied-then-raw validation, pinned snapshot           |
| 6   | Project routes                              | `/projects` CRUD, `/projects/{slug}/views/{name}`, save routes with 404/409/400/503 mapping, canvas PUT    |
| 7   | Recall as a step                            | `start_recall`, `POST /sessions/{id}/recall`, `recall` steps with `runs`, view recall with saved state     |
| 8   | Host: types, client, `ViewHost`, scrubber   | TS project types, client methods, hooks taking the slug in variables, `ViewHost` shared by steps and cards |
| 9   | Host: project browser, save dialogs, recall | `ProjectBrowser`, `SaveDialog`, `StepActions`, `ProjectRail`, `App` page union                             |
| 10  | Canvas page                                 | `react-grid-layout` 2.3 grid, `CanvasCardFrame`, `ProjectPage` tabs, layout mapping, debounced canvas PUT  |
| 11  | Linked keys                                 | `SharedStateHub` fanning `shared:` keys to other cards through `restore`                                   |
| 12  | End-to-end and docs                         | Playwright save → recall → canvas; working state, code map, decisions, glossary, open items, README        |

## Architecture and constraints agreed

- Project layout is exactly spec section 5; everything is text except
  `data.parquet`; writes are atomic through temp-and-replace.
- A dataset saves while its session is idle. `hold` marks the session busy like
  restart; a running step makes the save return 409 at once. While held,
  `running_step` is `None`, so the prompt box stays enabled and a prompt sent
  meanwhile gets 409; that is accepted for Stage 4.
- Validation uses `describe(name)` on both kernels, never `step.datasets`. Same
  column names and dtypes in order, same row count.
- The tidied script is validated first; on failure the raw concatenation is
  validated as the fallback. Neither a tidy failure nor a validation failure
  fails the save: `validated` and `validation_error` say what happened, and
  `recipe.py` is the raw script when nothing validated.
- Recipes keep only the `ok` runs of each step in the closure. A read is
  produced by the latest earlier step that wrote or defined the name; reads
  nothing produced (such as `loaders`) are skipped.
- Pinned recall code is generated at recall time from the absolute parquet path
  and never stored. Recall overwrites an existing name after the UI confirms.
  Recall steps go through the manual-run path so `runs` is filled and restart
  replays them.
- The canvas binds to the active session; a card whose datasets are absent shows
  "Load", which recalls the view as a step. No hidden project kernel. Only
  layout lives in `project.json`; card state is ephemeral per visit and "Save
  view" freezes a new `state.json`.
- Linked keys fan out only on the canvas, through `restore` with each card's
  last known state merged with the shared values. No seeding on load; the first
  change wins. `restore` never fires `stateChanged`, so no loop.
- Dependencies: `react-grid-layout` 2.3 (root export `GridLayout`,
  `useContainerWidth`, `gridConfig`, `dragConfig.handle`) and `react-resizable`
  for handle CSS. Do not install `@types/react-grid-layout` (v1 typings,
  conflicts). The drag handle is the card header; iframes get
  `pointer-events: none` while dragging or resizing; the mount-time
  `onLayoutChange` is ignored by comparing cards before writing.
- Code rules: TypeScript strict, no `any`, `interface` for props, no `React.FC`,
  `useEffect` only for the bridge listener, the restore effect and the chart
  container, files under 250 lines, prettier on everything; Python typed, ruff,
  mypy strict. Commits: bare Conventional Commit types, no scopes, no
  attribution trailers (the pre-commit hook rejects both).

## Acceptance criteria

- A dataset saved live or pinned from a finished session has `recipe.py`,
  `recipe.raw.py` and `meta.json` on disk with `validated` reflecting a real
  scratch-kernel run, and `data.parquet` when pinned.
- Saving a view saves its datasets first (one mode prompt), its TSX, and its
  latest snapshot state.
- Recall creates a `recall` step with `runs` filled; restart replays it;
  recalled views mount with their saved state.
- The rail lists projects with datasets and views; the project page has a Saved
  tab and a Canvas tab with draggable, resizable cards persisted in
  `project.json`; "Pin to canvas" appends a card.
- Changing a `shared:` key in one card restores the other cards with that value.
- Saving while a step runs returns 409 at once.
- `npm run check`, `npm test`, `npm run build`, `uv run pytest` (including
  `tests/e2e`), ruff and mypy pass locally and in CI.

## Required tests

- pytest: store CRUD, slug dedupe, dataset and view round trips, canvas; recipe
  walk (helpers, latest writer, self-rebinding, failed step with an `ok` run,
  unknown dataset); tidy (fences, failure, garbage, unbound name); validation
  (match, row mismatch, schema mismatch, error, unbound); project service
  (validated live save, bad tidy falling back unvalidated with a pinned parquet,
  409 while running, save view saving datasets first); routes (CRUD, save flow,
  bad name 400, unknown dataset 404, canvas PUT, saved view GET, 409 while
  running); recall (live, pinned, view with state, second recall with everything
  present, 404s).
- Vitest: client canvas PUT shape; `ViewHost` (mount after ready, forward
  `stateChanged`, `restore` on `restoreState` change); `SnapshotScrubber`;
  `ProjectBrowser`; `SaveDialog` (submit shape, slugified name); canvas layout
  mapping; `SharedStateHub` (extract, fan out with merge, latest base,
  unregister, no shared keys).
- Playwright: save → new session → recall → open canvas with a `FakeProvider`
  whose fourth turn is the tidy reply.

## Known risks

- Tidy on a real provider may return prose or partial code; the binds-check and
  the raw fallback cover it, and the save reports it in `validation_error`.
- Validation re-runs loaders, so a recipe over SQL Server hits the database
  again at save time. Expected, and the reason saves are synchronous with a
  visible saving state.
- Lineage blind spots (SQL strings in `sql_local`, helpers bound without `def`,
  attribute mutation) make a recipe miss a source step. Validation then fails
  with `NameError` and the dataset is saved unvalidated with that reason.
  Deferred to Stage 5, listed in the plan's open items.
- `useQueries` in `ProjectRail` fetches every project's detail to show datasets
  and views in the rail; fine for tens of projects, a listing endpoint is the
  fix if it grows.
- The canvas "present datasets" set comes from step writes, not the kernel
  namespace; a name deleted in the kernel shows a failing query inside the card
  rather than the Load placeholder.
- `react-grid-layout` 2.3 is a recent rewrite; if `GridLayout` props differ from
  the plan at install time, read `node_modules/react-grid-layout/dist/*.d.ts`
  and adjust, recording the change.

## Unresolved questions

- Export and CLI project commands (spec section 10) are Stage 5.
- Whether the busy-but-no-step state should disable the prompt box (a `busy`
  flag in `SessionStatus`) is left for Stage 5 if it confuses anyone.
- Canvas card state persistence across visits is deliberately not done; reopen
  only if researchers ask for it.

## Rejected alternatives

- A hidden per-project kernel for the canvas: rejected; cards query through the
  active session, and recall steps keep lineage honest.
- Storing pinned recall code: rejected; generated from the path at recall time
  so a moved root does not break recall.
- Failing the save on a bad tidy or a failed validation: rejected by spec
  section 13; the save succeeds unvalidated with the reason shown.
- Seeding linked keys on canvas load: rejected; the first change wins, so two
  cards saved with different values do not fight on mount.
- Infinite canvas: rejected earlier (spec section 10), snap-to-grid stays.
- `@types/react-grid-layout`: rejected; v2 ships its own types.

## After Stage 4

Update [docs/working-state.md](../../working-state.md), add `quarry.projects`
and the new server and host modules to
[docs/context/code-map.md](../../context/code-map.md), record decisions in
[docs/context/decisions.md](../../context/decisions.md), resolve the Stage 4
items in [docs/open-items.md](../../open-items.md). Stage 5 (breadth: export,
CLI project commands, to-code, remaining built-ins, Perspective with Arrow,
opt-in licensed libraries) needs its plan written from the spec and the real
Stage 4 code.
