# Working state

Checkpoint as of 2026-10-08. This page holds temporary context: what is in
flight, the latest check results and the next actions. Rewrite it at the end of
each session and when a pull request opens or merges. Anything that will still
be true next month belongs in [context/](context/) or
[open-items.md](open-items.md), as the [docs index](README.md) explains.

## Current objective

Build Stage 2, the server and agent loop, on top of the merged Stage 1 core,
following the
[Stage 2 plan](superpowers/plans/2026-10-08-quarry-stage2-server-agent.md). The
[Stage 3](superpowers/plans/2026-10-08-quarry-stage3-first-ui.md),
[Stage 4](superpowers/plans/2026-10-08-quarry-stage4-projects.md) and
[Stage 5](superpowers/plans/2026-10-09-quarry-stage5-breadth.md) plans are
written; each stage waits for the one before it.

## Status by stage

| Stage               | Status                                 | Plan                                                                  |
| ------------------- | -------------------------------------- | --------------------------------------------------------------------- |
| 1. Core             | Merged in sunpar/quarry#1 as `d00b5fa` | [Stage 1](superpowers/plans/2026-10-08-quarry-stage1-core.md)         |
| 2. Server and agent | In progress, sunpar/quarry#2 open      | [Stage 2](superpowers/plans/2026-10-08-quarry-stage2-server-agent.md) |
| 3. First UI         | Planned, handoff ready, not started    | [Stage 3](superpowers/plans/2026-10-08-quarry-stage3-first-ui.md)     |
| 4. Projects         | Planned, handoff ready, not started    | [Stage 4](superpowers/plans/2026-10-08-quarry-stage4-projects.md)     |
| 5. Breadth          | Planned, not started                   | [Stage 5](superpowers/plans/2026-10-09-quarry-stage5-breadth.md)      |

### Stage 1: core

Done. What it left for later stages is filed by stage in
[open-items.md](open-items.md).

### Stage 2: server and agent

In progress on `claude/quarry-stage2-server-agent-66853b`, sunpar/quarry#2. The
session building Stage 2 owns this subsection.

## Latest verification

`main` at `023a5c1` on 2026-10-08: 721 tests passed, and `ruff check`,
`ruff format --check` and `mypy src` were clean.

## Next actions

1. Stage 2: once these docs reach `main`, merge them into
   `claude/quarry-stage2-server-agent-66853b`. Then add a server and agent area
   to [decisions](context/decisions.md), rows for `quarry.agent` and
   `quarry.server` to the [code map](context/code-map.md), and Stage 2 entries
   to [open-items.md](open-items.md), resolving the Stage 1 items filed under
   Stage 2.
2. Stage 2: work through its [deferred items](open-items.md#stage-2) and the
   [open questions](open-items.md#open-questions) it depends on.
3. Merge sunpar/quarry#2 once CI is green and the Codex review is clear.
4. Stage 3: start from the
   [Stage 3 handoff](superpowers/handoffs/2026-10-08-quarry-stage3-handoff.md),
   which points at the plan and its [deferred items](open-items.md#stage-3).
5. Stage 4: once sunpar/quarry#2 and sunpar/quarry#4 are merged, start from the
   [Stage 4 handoff](superpowers/handoffs/2026-10-08-quarry-stage4-handoff.md).
6. Stage 5: once Stage 4 is merged, execute the
   [Stage 5 plan](superpowers/plans/2026-10-09-quarry-stage5-breadth.md), which
   closes the Stage 5 and Stage 4 items in [open-items.md](open-items.md).

## Resuming

1. Read this page, then the [docs index](README.md) for where everything else
   lives.
2. Compare `git log --oneline -5 origin/main` and `gh pr list` with the tables
   above. When they disagree, trust git and fix this page.
