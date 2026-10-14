# Working state

Checkpoint as of 2026-10-14. This page holds temporary context: what is in
flight, the latest check results and the next actions. Rewrite it at the end of
each session and when a pull request opens or merges. Anything that will still
be true next month belongs in [context/](context/) or
[open-items.md](open-items.md), as the [docs index](README.md) explains.

## Current objective

Migrate routine verification to local staged and committed snapshots on
`codex/local-first-ci`, based on the merged CI-speed work in
[sunpar/quarry#14](https://github.com/sunpar/quarry/pull/14). The full local
replacement passed before automatic hosted triggers were removed. GitHub has no
branch protections or rulesets to migrate. The rollout is open in
[sunpar/quarry#15](https://github.com/sunpar/quarry/pull/15). Astra completed
its local review without findings on `ecc1c65`; Opus and Muse were unavailable
due to provider quotas. Their one-attempt budgets are recorded in the worktree
ledger. Continue the authorized open-pr-and-babysit workflow.

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
merged on 2026-10-10. How the stage was run (models, reviews, the long commit
subjects kept, the merge record pushed straight to `main`) is under
[build process](context/decisions.md#build-process).

### Stages 4 and 5 review

Built on `claude/quarry-stage4-5-review-fixes`. Codex (`gpt-6-astra`) reviewed
the branch diff from `6bc133e`, the `main` before Stage 4, four times, and each
round's findings were fixed, tested and recorded in
[decisions](context/decisions.md); a `/simplify` pass followed. On the pull
request, five rounds of `@claude` and `@codex` reviews followed, and both came
back clean on `8b54708` with CI green. Two Codex points stayed as recorded
decisions: any load of a helper's name counts as a call, and recall calls
`exec`, `dict` and `globals` from the session. What the reviews suggested and
the branch left is under [Any time](open-items.md#any-time). The pull request
merged on 2026-10-11.

### Save, pin and To code follow-up

Built on `claude/quarry-save-pin-tocode`, it took three items the Stages 4 and 5
review had filed under [Any time](open-items.md#any-time). A pinned save now
snapshots to `.data.parquet.tmp`, which `write_dataset` moves into place just
before `meta.json`; "Pin to canvas" is a `pin` field on the view save, which
`ProjectStore.pin_view` applies under the store's lock; and the server picks
what "To code" renders, through `to_code_input`, which the export shares. Codex
and `@claude` came back clean, and the pull request merged in sunpar/quarry#12
as `e8cce38` on 2026-10-12. Codex's point that the rows' rename and the
`meta.json` write are still two steps is recorded as a cost in
[decisions](context/decisions.md); the whole-canvas layout write is filed under
Any time. A separate review of the PR comments at `8c723eb` found no new defects
introduced by that PR and confirmed that live saves remove abandoned staging
files. Its documentation follow-up is
[sunpar/quarry#13](https://github.com/sunpar/quarry/pull/13).

## Latest verification

Local-first rollout, macOS and Python 3.11 on 2026-10-14: all 962 Python tests
passed, with the same three skips (two live providers and the Linux memory cap).
All 10 browser tests ran against a fresh build and all 235 frontend tests
passed. Python lint/format/types, frontend checks and the offline wheel/sdist
build passed; the wheel includes UI, runtime manifest, checker and assets.

Branch coverage passed the same suite in 61.92 seconds; the full coverage
command took 90.34 seconds including setup/build checks. It covered 3,904 of
4,012 statements and 882 of 946 branches. These figures cover pytest processes,
not all kernel subprocess execution. The initial staged smoke gate took 4.27
seconds; the expanded regression suite took 8.78 seconds after review fixes. All
24 gate/transport regressions passed, including snapshot imports in xdist and a
real kernel. A real pre-commit rejected staged invalid Python despite an
unstaged fix and preserved the index and HEAD. Workflow actionlint passed.

Full checks install the snapshot wheel in a separate environment so the existing
isolated Python export test still runs. Shared dependencies contain no editable
Quarry install. Linux hosted validation and licensed Highcharts/SciChart browser
coverage have not been exercised in this session.

## Next actions

1. Seven Codex findings are fixed: complete the code map, paginate exact-head PR
   lookup, use explicit fork repository identity, reject equal base/head before
   pushing, avoid fetched-ref tracking, persist the hook bootstrap in Git
   metadata and force setup into the repository environment. Required
   self-assignment remains after verified PR creation, with the URL printed
   before metadata changes. Full local validation passed again.
2. Push and validate the fixes, reply to the eight review threads, then continue
   the remaining capped bot rotation and merge only when its conditions hold.

## Resuming

1. Read this page, then the [docs index](README.md) for where everything else
   lives.
2. Compare `git log --oneline -5 origin/main` and `gh pr list` with the tables
   above. When they disagree, trust git and fix this page.
