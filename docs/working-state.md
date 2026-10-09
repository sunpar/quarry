# Working state

Checkpoint as of 2026-10-09. This page holds temporary context: what is in
flight, the latest check results and the next actions. Rewrite it at the end of
each session and when a pull request opens or merges. Anything that will still
be true next month belongs in [context/](context/) or
[open-items.md](open-items.md), as the [docs index](README.md) explains.

## Current objective

Start Stage 5, breadth. Stage 4, projects and the canvas, merged to `main` in
sunpar/quarry#8. The
[Stage 5 plan](superpowers/plans/2026-10-09-quarry-stage5-breadth.md) and
[Stage 5 handoff](superpowers/handoffs/2026-10-09-quarry-stage5-handoff.md) are
written.

## Status by stage

| Stage               | Status                                 | Plan                                                                  |
| ------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| 1. Core             | Merged in sunpar/quarry#1 as `d00b5fa` | [Stage 1](superpowers/plans/2026-10-08-quarry-stage1-core.md)         |
| 2. Server and agent | Merged in sunpar/quarry#2 as `7779c05` | [Stage 2](superpowers/plans/2026-10-08-quarry-stage2-server-agent.md) |
| 3. First UI         | Merged in sunpar/quarry#4 as `faf913f` | [Stage 3](superpowers/plans/2026-10-08-quarry-stage3-first-ui.md)     |
| 4. Projects         | Merged in sunpar/quarry#8              | [Stage 4](superpowers/plans/2026-10-08-quarry-stage4-projects.md)     |
| 5. Breadth          | Planned, handoff ready, next           | [Stage 5](superpowers/plans/2026-10-09-quarry-stage5-breadth.md)      |

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
[Stage 5](open-items.md#stage-5). The maintainer approved the one security
change, the `Access-Control-Allow-Origin` header on the static mount. Merged to
`main` in sunpar/quarry#4 as `faf913f` on 2026-10-09 after a clean Codex review
of its fifth fix round.

### Stage 4: projects and canvas

Built on `claude/quarry-stage4-projects`, branched from `main` at `faf913f` and
brought up to date with `main`'s Stage 5 docs. All 12 plan tasks passed their
task reviews, and the Playwright test for save, recall and the canvas passes
against the built UI. Its calls are under
[projects](context/decisions.md#projects), with a few under
[server and agent](context/decisions.md#server-and-agent) and
[first UI](context/decisions.md#first-ui); the modules are in the
[code map](context/code-map.md#quarryprojects), and what it left is filed under
[Stage 5](open-items.md#stage-5). The final review's four Important findings and
eight of its ten Minor ones are fixed; the other two, with the task reviews'
deferred findings a researcher could hit, are filed there too. A `/simplify`
pass then reused existing helpers and dropped the rail's per-project fetches.
Two `@claude` reviews on the pull request led to a lock around `project.json`
updates and to `child`, which keeps request names inside their directories.
Codex was out of review credits, so at the maintainer's call a whole-PR
`@claude` review stood in for it; it came back clean, and the pull request
merged on 2026-10-09.

## Latest verification

`claude/quarry-stage4-projects` at its last review fix, on 2026-10-09: CI ran
995 tests passed and 2 skipped (the live provider tests), including the browser
tests under `tests/e2e`, and in `web/` `npm run check`, `npm test` (92 tests)
and `npm run build`. Locally, after the `/simplify` pass, 994 passed and 3
skipped (the memory-cap test too), and `ruff check`, `ruff format --check`,
`mypy src` and `uv lock --check` were clean.

## Next actions

1. Stage 5: on `main`, start from the
   [Stage 5 handoff](superpowers/handoffs/2026-10-09-quarry-stage5-handoff.md),
   which points at the plan that closes the
   [Stage 5 items](open-items.md#stage-5).

## Resuming

1. Read this page, then the [docs index](README.md) for where everything else
   lives.
2. Compare `git log --oneline -5 origin/main` and `gh pr list` with the tables
   above. When they disagree, trust git and fix this page.
