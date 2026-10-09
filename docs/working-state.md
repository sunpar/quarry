# Working state

Checkpoint as of 2026-10-08. This page holds temporary context: what is in
flight, the latest check results and the next actions. Rewrite it at the end of
each session and when a pull request opens or merges. Anything that will still
be true next month belongs in [context/](context/) or
[open-items.md](open-items.md), as the [docs index](README.md) explains.

## Current objective

Land Stage 2, the server and agent loop, in sunpar/quarry#2. The
[Stage 3 plan](superpowers/plans/2026-10-08-quarry-stage3-first-ui.md) and the
[Stage 4 plan](superpowers/plans/2026-10-08-quarry-stage4-projects.md) are
written; Stage 3 waits for Stage 2, Stage 4 for Stage 3.

## Status by stage

| Stage               | Status                                 | Plan                                                                  |
| ------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| 1. Core             | Merged in sunpar/quarry#1 as `d00b5fa` | [Stage 1](superpowers/plans/2026-10-08-quarry-stage1-core.md)         |
| 2. Server and agent | Built, sunpar/quarry#2 open            | [Stage 2](superpowers/plans/2026-10-08-quarry-stage2-server-agent.md) |
| 3. First UI         | Planned, handoff ready, not started    | [Stage 3](superpowers/plans/2026-10-08-quarry-stage3-first-ui.md)     |
| 4. Projects         | Planned, handoff ready, not started    | [Stage 4](superpowers/plans/2026-10-08-quarry-stage4-projects.md)     |
| 5. Breadth          | Not planned yet                        | Spec §15                                                              |

### Stage 1: core

Done. What it left for later stages is filed by stage in
[open-items.md](open-items.md).

### Stage 2: server and agent

Built on `claude/quarry-stage2-server-agent-66853b` and open as sunpar/quarry#2.
All 12 plan tasks passed their task reviews, and the fixes from the whole-branch
review are in. Its calls are under
[server and agent](context/decisions.md#server-and-agent), and what it left is
in [open-items.md](open-items.md).

- Neither provider adapter has called its real API yet; see the
  [open questions](open-items.md#open-questions).
- The fixes for the first Codex review are in, and CI Auto-fix is on.
- The Stage 2 deferred items landed in sunpar/quarry#2 as seven reviewed tasks:
  config hardening, unreadable data paths, the `RLIMIT_DATA` and thread caps,
  kernel client failures, metadata caching, restart that stops a running step,
  and private session files with `origin_step`.

## Latest verification

`main` at `023a5c1` on 2026-10-08: 721 tests passed, and `ruff check`,
`ruff format --check` and `mypy src` were clean.

`claude/quarry-stage2-server-agent-66853b` at `8c86831` on 2026-10-09: 911 tests
passed and 3 skipped (the two live provider tests, which need API keys, and the
memory-cap test, which macOS refuses), and `ruff check`, `ruff format --check`,
`mypy src`, `uv lock --check` and the docs prettier check were clean.

## Next actions

1. Stage 2: merge sunpar/quarry#2 once CI is green and the Codex review is
   clear.
2. Run the live provider tests with a key:
   `QUARRY_ANTHROPIC_API_KEY=... uv run pytest tests/agent/test_live_providers.py -v`.
3. Stage 3: start from the
   [Stage 3 handoff](superpowers/handoffs/2026-10-08-quarry-stage3-handoff.md),
   which points at the plan and its [deferred items](open-items.md#stage-3). The
   plan's API types match Stage 2 as of `08efb23`. Since then a step gained
   `runs`, `DatasetMeta` gained `origin_step`, `/interrupt` also cancels a
   prompt step, and `/restart` stops a running step instead of answering 409, so
   re-check the plan against the merged branch.
4. Stage 4: once sunpar/quarry#2 and sunpar/quarry#4 are merged, start from the
   [Stage 4 handoff](superpowers/handoffs/2026-10-08-quarry-stage4-handoff.md).

## Resuming

1. Read this page, then the [docs index](README.md) for where everything else
   lives.
2. Compare `git log --oneline -5 origin/main` and `gh pr list` with the tables
   above. When they disagree, trust git and fix this page.
