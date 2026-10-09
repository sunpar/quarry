# Working state

Checkpoint as of 2026-10-08. This page holds temporary context: what is in
flight, the latest check results and the next actions. Rewrite it at the end of
each session and when a pull request opens or merges. Anything that will still
be true next month belongs in [context/](context/) or
[open-items.md](open-items.md), as the [docs index](README.md) explains.

## Current objective

Build Stage 4, projects and the canvas, from the
[Stage 4 handoff](superpowers/handoffs/2026-10-08-quarry-stage4-handoff.md) now
that Stages 1 to 3 are on `main`. The
[Stage 5 plan](superpowers/plans/2026-10-09-quarry-stage5-breadth.md) and
[Stage 5 handoff](superpowers/handoffs/2026-10-09-quarry-stage5-handoff.md) are
written; Stage 5 waits for Stage 4.

## Status by stage

| Stage               | Status                                 | Plan                                                                  |
| ------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| 1. Core             | Merged in sunpar/quarry#1 as `d00b5fa` | [Stage 1](superpowers/plans/2026-10-08-quarry-stage1-core.md)         |
| 2. Server and agent | Merged in sunpar/quarry#2 as `7779c05` | [Stage 2](superpowers/plans/2026-10-08-quarry-stage2-server-agent.md) |
| 3. First UI         | Merged in sunpar/quarry#4 as `faf913f` | [Stage 3](superpowers/plans/2026-10-08-quarry-stage3-first-ui.md)     |
| 4. Projects         | Planned, handoff ready, not started    | [Stage 4](superpowers/plans/2026-10-08-quarry-stage4-projects.md)     |
| 5. Breadth          | Planned, handoff ready, not started    | [Stage 5](superpowers/plans/2026-10-09-quarry-stage5-breadth.md)      |

### Stage 1: core

Done. What it left for later stages is filed by stage in
[open-items.md](open-items.md).

### Stage 2: server and agent

Merged to `main` in sunpar/quarry#2 as `7779c05` on 2026-10-09. Its calls are
under [server and agent](context/decisions.md#server-and-agent), and what it
left is in [open-items.md](open-items.md#stage-2). Neither provider adapter has
called its real API yet; see the [open questions](open-items.md#open-questions).
The fixes for five Codex reviews landed with it, as did the Stage 2 deferred
items, in seven reviewed tasks: config hardening, unreadable data paths, the
`RLIMIT_DATA` and thread caps, kernel client failures, metadata caching, restart
that stops a running step, and private session files with `origin_step`.

### Stage 3: first UI

Built on `claude/quarry-stage3-first-ui`, branched from the Stage 2 branch and
brought up to date with `main` after Stage 2 merged. All 12 plan tasks passed
their task reviews, the whole-branch review's fixes are in, and the Playwright
tests pass against the built UI. Its calls are under
[first UI](context/decisions.md#first-ui), the modules are in the
[code map](context/code-map.md#web), and what it left is filed under
[Stage 4](open-items.md#stage-4). The maintainer approved the one security
change, the `Access-Control-Allow-Origin` header on the static mount. Merged to
`main` in sunpar/quarry#4 as `faf913f` on 2026-10-09 after a clean Codex review
of its fifth fix round.

## Latest verification

`claude/quarry-stage3-first-ui` on 2026-10-09, with the Stage 2 branch merged
in: 951 tests passed and 3 skipped (the live provider tests and the memory-cap
test), including the two browser tests under `tests/e2e`; `ruff check`,
`ruff format --check`, `mypy src` and `uv lock --check` were clean; in `web/`,
`npm run check` (tsc and prettier), `npm test` (67 tests) and `npm run build`
passed; the wheel from `uv build` contains `quarry/static/index.html`.

## Next actions

1. Run the live provider tests with a key:
   `QUARRY_ANTHROPIC_API_KEY=... uv run pytest tests/agent/test_live_providers.py -v`,
   then open the UI with a real key and try a prompt.
2. Stage 4: start from the
   [Stage 4 handoff](superpowers/handoffs/2026-10-08-quarry-stage4-handoff.md).
   Its plan was written against the Stage 3 plan, so re-check it against the
   real `HostBridge`, hooks and snapshot route; `HostBridge.restore` and
   `ViewStateStore.replace` are ready for the scrubber.
3. Stage 5: once Stage 4 is merged, start from the
   [Stage 5 handoff](superpowers/handoffs/2026-10-09-quarry-stage5-handoff.md),
   which points at the plan that closes the Stage 5 and Stage 4 items in
   [open-items.md](open-items.md).

## Resuming

1. Read this page, then the [docs index](README.md) for where everything else
   lives.
2. Compare `git log --oneline -5 origin/main` and `gh pr list` with the tables
   above. When they disagree, trust git and fix this page.
