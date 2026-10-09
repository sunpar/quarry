# Working state

Checkpoint as of 2026-10-08. This page holds temporary context: what is in
flight, the latest check results and the next actions. Rewrite it at the end of
each session and when a pull request opens or merges. Anything that will still
be true next month belongs in [context/](context/) or
[open-items.md](open-items.md), as the [docs index](README.md) explains.

## Current objective

Land Stage 2, the server and agent loop, in sunpar/quarry#2. Then start Stage 3
from its [plan](superpowers/plans/2026-10-08-quarry-stage3-first-ui.md), which
is written and waits for Stage 2.

## Status by stage

| Stage               | Status                                 | Plan                                                                  |
| ------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| 1. Core             | Merged in sunpar/quarry#1 as `d00b5fa` | [Stage 1](superpowers/plans/2026-10-08-quarry-stage1-core.md)         |
| 2. Server and agent | Built, sunpar/quarry#2 open            | [Stage 2](superpowers/plans/2026-10-08-quarry-stage2-server-agent.md) |
| 3. First UI         | Planned, handoff ready, not started    | [Stage 3](superpowers/plans/2026-10-08-quarry-stage3-first-ui.md)     |
| 4. Projects         | Not planned yet                        | Spec §15                                                              |
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
- The maintainer chose to land the [Stage 2 items](open-items.md#stage-2) in
  sunpar/quarry#2. They are being worked one task at a time, each reviewed.

## Latest verification

`main` at `023a5c1` on 2026-10-08: 721 tests passed, and `ruff check`,
`ruff format --check` and `mypy src` were clean.

`claude/quarry-stage2-server-agent-66853b` at `95a7efd` on 2026-10-08: 798 tests
passed and 2 skipped (the live provider tests, which need API keys), and
`ruff check`, `ruff format --check`, `mypy src` and `uv lock --check` were
clean.

## Next actions

1. Stage 2: finish its [deferred items](open-items.md#stage-2) in
   sunpar/quarry#2, then merge it once CI is green and the Codex review is
   clear.
2. Run the live provider tests with a key:
   `QUARRY_ANTHROPIC_API_KEY=... uv run pytest tests/agent/test_live_providers.py -v`.
3. Stage 3: start from the
   [Stage 3 handoff](superpowers/handoffs/2026-10-08-quarry-stage3-handoff.md),
   which points at the plan and its [deferred items](open-items.md#stage-3). The
   plan's API types match Stage 2 as of `08efb23`; since then a step gained
   `runs`, so re-check them against the merged branch.

## Resuming

1. Read this page, then the [docs index](README.md) for where everything else
   lives.
2. Compare `git log --oneline -5 origin/main` and `gh pr list` with the tables
   above. When they disagree, trust git and fix this page.
