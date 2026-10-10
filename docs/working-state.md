# Working state

Checkpoint as of 2026-10-10. This page holds temporary context: what is in
flight, the latest check results and the next actions. Rewrite it at the end of
each session and when a pull request opens or merges. Anything that will still
be true next month belongs in [context/](context/) or
[open-items.md](open-items.md), as the [docs index](README.md) explains.

## Current objective

None planned. Stage 5, breadth, was the last planned stage and merged on
2026-10-10. What remains is in [open-items.md](open-items.md) (its known
problems, the "Any time" list and the open questions) and in the spec's
[deferred list](superpowers/specs/2026-10-08-quarry-design.md#16-deferred).

## Status by stage

| Stage               | Status                                 | Plan                                                                  |
| ------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| 1. Core             | Merged in sunpar/quarry#1 as `d00b5fa` | [Stage 1](superpowers/plans/2026-10-08-quarry-stage1-core.md)         |
| 2. Server and agent | Merged in sunpar/quarry#2 as `7779c05` | [Stage 2](superpowers/plans/2026-10-08-quarry-stage2-server-agent.md) |
| 3. First UI         | Merged in sunpar/quarry#4 as `faf913f` | [Stage 3](superpowers/plans/2026-10-08-quarry-stage3-first-ui.md)     |
| 4. Projects         | Merged in sunpar/quarry#8 as `0e1720d` | [Stage 4](superpowers/plans/2026-10-08-quarry-stage4-projects.md)     |
| 5. Breadth          | Merged in sunpar/quarry#9 as `1aa5d6e` | [Stage 5](superpowers/plans/2026-10-09-quarry-stage5-breadth.md)      |

### Stage 1: core

Done. What it left is filed in [open-items.md](open-items.md).

### Stage 2: server and agent

Merged to `main` in sunpar/quarry#2 as `7779c05` on 2026-10-09. Its calls are
under [server and agent](context/decisions.md#server-and-agent), and what it
left is in [open-items.md](open-items.md). Neither provider adapter has called
its real API yet; see the [open questions](open-items.md#open-questions). The
fixes for five Codex reviews landed with it, as did the Stage 2 deferred items,
in seven reviewed tasks: config hardening, unreadable data paths, the
`RLIMIT_DATA` and thread caps, kernel client failures, metadata caching, restart
that stops a running step, and private session files with `origin_step`.

### Stage 3: first UI

Built on `claude/quarry-stage3-first-ui`, branched from the Stage 2 branch and
brought up to date with `main` after Stage 2 merged. All 12 plan tasks passed
their task reviews, the whole-branch review's fixes are in, and the Playwright
tests pass against the built UI. Its calls are under
[first UI](context/decisions.md#first-ui), the modules are in the
[code map](context/code-map.md#web), and what it left is filed in
[open-items.md](open-items.md). The maintainer approved the one security change,
the `Access-Control-Allow-Origin` header on the static mount. Merged to `main`
in sunpar/quarry#4 as `faf913f` on 2026-10-09 after a clean Codex review of its
fifth fix round.

### Stage 4: projects and canvas

Built on `claude/quarry-stage4-projects`, branched from `main` at `faf913f` and
brought up to date with `main`'s Stage 5 docs. All 12 plan tasks passed their
task reviews, and the Playwright test for save, recall and the canvas passes
against the built UI. Its calls are under
[projects](context/decisions.md#projects), with a few under
[server and agent](context/decisions.md#server-and-agent) and
[first UI](context/decisions.md#first-ui); the modules are in the
[code map](context/code-map.md#quarryprojects), and what it left is filed in
[open-items.md](open-items.md). The final review's four Important findings and
eight of its ten Minor ones are fixed; the other two, with the task reviews'
deferred findings a researcher could hit, are filed there too. A `/simplify`
pass then reused existing helpers and dropped the rail's per-project fetches.
Two `@claude` reviews on the pull request led to a lock around `project.json`
updates and to `child`, which keeps request names inside their directories.
Codex was out of review credits, so at the maintainer's call a whole-PR
`@claude` review stood in for it; it came back clean, and the pull request
merged on 2026-10-09.

### Stage 5: breadth

Built on `claude/quarry-stage5-breadth`, branched from the Stage 4 branch and
brought up to date with `main` once Stage 4 merged, as one pull request. Tasks 1
to 12 passed their task reviews, and Task 13 added the browser tests for "To
code", the library and the new chart libraries, the CI pins, `mypy` on the tests
and these docs. Its calls are under [views](context/decisions.md#views) and in
the other sections the plan touched, the modules are in the
[code map](context/code-map.md), and what it closed is gone from
[open-items.md](open-items.md). What it deferred is under
[Any time](open-items.md#any-time), and what the task reviews and the final
review left is under [known problems](open-items.md#known-problems). Codex was
out of review credits, so two whole-PR `@claude` reviews stood in for it; both
came back with nothing to block on, the second covering the built-ins, the
Perspective mapping and the host dialogs the first had skipped. The pull request
merged on 2026-10-10.

## Latest verification

`claude/quarry-stage5-breadth` at `6eb8d19`, merged as `1aa5d6e`. Locally on
2026-10-10, after the final review's fixes: `pytest` passed 1060 tests and
skipped 3 (the live provider and memory-cap tests), including the 10 browser
tests under `tests/e2e`. `ruff check`, `ruff format --check`, `mypy src tests`
and `uv lock --check` were clean, and in `web/` `npm run check`, `npm test` (233
tests) and `npm run build` passed. CI passed on sunpar/quarry#9 at `6eb8d19`.

## Next actions

1. Pick the next work from [open-items.md](open-items.md), starting with its
   known problems.

## Resuming

1. Read this page, then the [docs index](README.md) for where everything else
   lives.
2. Compare `git log --oneline -5 origin/main` and `gh pr list` with the tables
   above. When they disagree, trust git and fix this page.
