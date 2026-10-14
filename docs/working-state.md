# Working state

Checkpoint as of 2026-10-14 22:38 UTC. This page holds temporary context: what
is in flight, the latest check results and the next actions. Rewrite it at the
end of each session and when a pull request opens or merges. Anything that will
still be true next month belongs in [context/](context/) or
[open-items.md](open-items.md), as the [docs index](README.md) explains.

## Current objective

Finish the review workflows for the five bounded improvements selected from the
related-project survey, and leave the implementation and coordination PRs open
when ready to merge. The researcher delegated routine design choices. Separate
assessments cover parameterized workflows, session branching and the complete
remaining-work inventory.

| Work                  | Open PR / code checkpoint                                     | Contract                                                                              | Verification                                                         | Review                                                                                                                                                |
| --------------------- | ------------------------------------------------------------- | ------------------------------------------------------------------------------------- | -------------------------------------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------- |
| Reproducible exports  | [PR #18](https://github.com/sunpar/quarry/pull/18), `7c59864` | Render saved queries against replayed schemas and record allowlisted runtime versions | Mac and Linux full passed: 1,086 Python, 235 frontend, 25 gate tests | Codex 2 clean on this head; all prior review threads resolved; readiness reconciled                                                                   |
| Whole-series charts   | [PR #22](https://github.com/sunpar/quarry/pull/22), `706f4f1` | Reduce line points across the full time range                                         | Mac and Linux full passed: 1,188 Python, 237 frontend, 25 gate tests | All eight review threads resolved; budget exhausted without clean review; fallback elapsed at 22:35:03 UTC and eligibility reconciled at 22:36:18 UTC |
| Table filters         | [PR #19](https://github.com/sunpar/quarry/pull/19), `744d5ba` | Push both tables' filters into query specs                                            | Mac and Linux full passed: 1,071 Python, 249 frontend, 25 gate tests | Budget exhausted, no clean result; fallback elapsed at 21:31:27 UTC and eligibility reconciled at 21:34:21 UTC                                        |
| Mount and query reuse | [PR #21](https://github.com/sunpar/quarry/pull/21), `68fbc2d` | Mount views once and reuse in-flight queries                                          | Mac and Linux full passed: 1,069 Python, 253 frontend, 25 gate tests | Connection and early-restore fixes verified; budget exhausted without clean review; fallback elapsed at 22:10:18 UTC and eligibility reconciled       |
| Frozen HTML reports   | [PR #20](https://github.com/sunpar/quarry/pull/20), `dcf6581` | Export saved metadata and pinned rows as offline HTML without live execution          | Mac and Linux full passed: 1,100 Python, 236 frontend, 25 gate tests | All six review threads resolved; budget exhausted, no clean result; fallback elapsed at 21:48:57 UTC and eligibility reconciled                       |

Code checkpoints identify the implementations under review. Check and review
evidence belongs to its exact SHA. A silence fallback ends the capped review
workflow without a clean verdict; new substantive feedback or another push can
change eligibility.

| Work                  | Task thread                                                                        | Assessment status                                       |
| --------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------- |
| Reproducible exports  | Improve Quarry export reproducibility (`01a13c15-0c0d-7f13-84ca-d31c5bbbc160`)     | Implementation brief                                    |
| Whole-series charts   | Show complete long series in Quarry (`01a13c15-15d9-78e3-a548-708275107f4f`)       | Implementation brief                                    |
| Table filters         | Add reproducible Quarry table filters (`01a13c15-1c05-7273-afba-e9ae6f1e8df0`)     | Implementation brief                                    |
| Mount and query reuse | Improve Quarry canvas query execution (`01a13c15-2207-7c50-a47a-5941b9f5dcc2`)     | Implementation brief                                    |
| Frozen HTML reports   | Export frozen Quarry research reports (`01a13c15-295e-7a70-a0bf-6ba0ba8e65b5`)     | Implementation brief                                    |
| Reusable workflows    | Assess reusable Quarry research workflows (`01a13c16-26b4-7ba0-b634-bf6107bcdbc0`) | Complete; no implementation                             |
| Session branching     | Assess Quarry session branching (`01a13c16-2d48-71c0-99cc-5cebb5b319a1`)           | Complete; no implementation                             |
| Remaining work        | Reconcile Quarry remaining work (`01a13c16-330f-7d80-b840-bd2ceb9a2f6b`)           | Complete inventory; final status reconciliation pending |

All five implementation PRs are open, unmerged and ready for integration after
fresh eligibility reconciliation. Table filters do not close
`TABLE-SORT-RETAIN-ROWS`: same-spec refreshes retain rows, but changed sort or
filter specs still show "Loading".

The app threads reached sandbox approval prompts for their external commands.
Execution continues through delegated workers using the controller's authorized
workspace tools; the app threads retain their briefs. Each implementation has
its own worktree and branch from `38b07ac`. Full gates share one resource lock.
The controller owns this page and the consolidated backlog; workers retain their
reports and review budgets in their worktree Git directories.

A combined local check on Mac at `5f0ef9e` passed 1,238 Python, 270 frontend and
25 gate tests, with three expected skips, in 78.35 seconds. It combined
`7c59864`, `706f4f1`, `744d5ba`, `68fbc2d` and `dcf6581`; all five source heads
were unchanged after the check. The export-code conflict retained runtime-schema
rendering and protected helper bindings while applying the configured line
budget. Documentation and appended export tests also needed reconciliation. This
is local combined evidence; Linux tested each feature separately. Later merges
still need to preserve that export composition and reconcile this checkpoint and
the feature-owned backlog edits.

The documentation checkpoint is published in
[PR #23](https://github.com/sunpar/quarry/pull/23). Its worktree Git directory
holds the review ledger and exact-head gate evidence. The opening head,
`0916e77`, passed the Mac PR wrapper: 1,069 Python, 235 frontend and 25 gate
tests, with three expected skips, in 100.02 seconds including push and creation.

Local assessment evidence is under `/Users/sunpar/Documents/Codex/2026-10-14/`:
the workflow assessment is
`quarry-workflow-assessment/outputs/workflow_assessment.json`, the branching
assessment is `quarry-branching-assessment/outputs/branching-assessment.json`,
and the remaining-work inventory is
`quarry-backlog-inventory/outputs/quarry_remaining_work.json`, with an offline
HTML companion at `quarry-backlog-inventory/outputs/quarry_remaining_work.html`.
The combined-check evidence is
`quarry-integration-check/outputs/integration_verification.json`. These are
local reports, not files distributed with the repository.

The workflow probe confirmed that earlier scalar and dictionary bindings can be
omitted from a saved recipe. Existing validation compares schema and row count,
not values. The branching assessment ran 23 passing replay/recall tests and a
synthetic prefix replay, while reproducing pinned-file drift and lost
interrupted partial state. The workflow assessment prioritizes dependency
capture before parameterization. The branching assessment keeps prefix copying
deferred pending its replay and input contract. The backlog retains both
follow-ups.

### Docker integration

The [Docker plan](superpowers/plans/2026-10-14-quarry-linux-docker.md) is
implemented. All four task threads passed spec and quality review. The final
whole-branch review of `492fa17..52974bb` found no Critical or Important defect
and approved integration. npm/build diagnostics remain nonblocking, with their
limits recorded below. The branch and evidence are kept for review in
`/Users/sunpar/.codex/worktrees/quarry-linux-docker/quarry`, on
`codex/quarry-linux-docker` based on `492fa17`. Interactive acceptance used a
temporary localhost port 18765 because an unrelated Mac service owns port 8765.
The shipped default mapping remains 8765.

The plan and this checkpoint are published separately in
[PR #17](https://github.com/sunpar/quarry/pull/17). The Docker tooling remains
ready for its own integration pull request.

| Task                            | Thread                                                                         | Status   |
| ------------------------------- | ------------------------------------------------------------------------------ | -------- |
| 1. Test image                   | Build Quarry Linux test image (01a13b8f-08de-7171-a4c1-94b46787fc62)           | Complete |
| 2. Commands                     | Add Quarry Linux verification commands (01a13b90-62b8-7031-9edc-5a184a62e676)  | Complete |
| 3. Interactive runtime          | Add Quarry Linux interactive runtime (01a13b90-6d23-7132-917c-3d08239d3df8)    | Complete |
| 4. Documentation and acceptance | Document and verify Quarry Linux Docker (01a13b90-775b-74d2-979d-0ec2c73642f4) | Complete |

The per-task briefs, reports, review packages, and progress ledger live under
`.superpowers/sdd/2026-10-14-quarry-linux-docker/` in that checkout. The
controller owns this page and the ledger. Provider inference remains opt-in.

Claude Code and Codex subscription access previously merged in
[PR #16](https://github.com/sunpar/quarry/pull/16) as `bc8dc2c` on 2026-10-14.

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

### Improvement branches

Checks and reviews belong to each branch's exact head. The table above records
completed evidence and pending work. Live providers, firm loaders and licensed
integrations were not exercised in these assessments. The coordination change
updates documentation only. Whole-series standalone source generation still
rejects float membership without a schema; notebook exports rely on PR #18 for
runtime-schema rendering.

### Docker branch

The implementation at `5392889` plus Task 4's documentation passed the unchanged
full gates on Mac and native Linux ARM64. Each passed 1,069 Python tests
(including browser tests), 235 frontend tests, and 25 gate/transport tests.
Lint, formatting, types, web build, offline wheel/sdist packaging, and wheel
assets passed. The direct app probe confirmed imports from
`/opt/quarry-runtime`, Claude SDK 0.2.110, and Quarry absent from `.venv`.

| Run                                       | Full command                                  | Total seconds | Python seconds |
| ----------------------------------------- | --------------------------------------------- | ------------- | -------------- |
| Mac final                                 | `make check`                                  | 74.45         | 54.24          |
| Native Linux ARM64 final                  | `make linux-check`                            | 98.08         | 65.73          |
| Native Linux resource measurement         | Check service running `make check`            | 86.81         | 61.70          |
| Emulated Linux AMD64, Task 2 at `9ff7579` | `make linux-check LINUX_PLATFORM=linux/amd64` | 374.69        | 157.15         |

All runs had three expected skips. Mac skipped the Linux memory-cap test and the
two live API providers; Linux skipped filesystem case folding and the live API
providers. The Linux memory-cap test ran and checks the configured 4096 MiB
`RLIMIT_DATA`, not allocation exhaustion or total container memory. Emulated
AMD64 passed the same test counts; its build overlapped fixture probes, and its
timings and kernel behavior do not establish native x86 results. The app target
was exercised only on native ARM64.

Docker Desktop 4.62.0, Engine 29.2.1, and Compose 5.0.2 used a Linux ARM64 VM
with 14 CPUs and 8,216,498,176 bytes (about 7.65 GiB) of memory. The complete
resource run recorded `/sys/fs/cgroup/memory.peak` of 4,806,164,480 bytes (about
4.48 GiB), including the check container's processes and charged filesystem
cache. This is a workload measurement, not a minimum VM memory requirement. The
first sampler attached after its check finished; the bounded resource run
retained both the peak counter and live samples.

Native ARM64 interactive acceptance passed health/token checks, synthetic manual
Python, query, pinned save, recall, notebook export with Linux paths, Mac
browser display, private modes, recreation, token rotation, and shutdown. Live
acceptance used port 18765; the default 8765 mapping was inspected because an
unrelated Mac process retained that port. No owned containers or project network
remain; the private `quarry-linux-arm64_home` volume retains synthetic
development data. The unrelated host process and PostgreSQL container remained
running.

Source/lockfile rebuilds, stale dependency rejection, container failure
propagation, shell use, and ordinary Make execution with an unavailable Docker
client passed. Each implementation commit passed the staged smoke gate: 24 Node,
154 Python, and 41 frontend tests. The timed Task 3 commit, including smoke,
took 3.45 seconds.

Existing frontend deprecations, esbuild install-script policy, and bundle-size
notices remain. The pinned Claude package also emits an npm install-script
policy warning; version/help probes and built UI acceptance pass. No unrelated
dependency or policy change was made. Provider authentication/inference,
external or licensed integrations, and hosted CI were not run in this work.

## Next actions

1. Finish the documentation PR review workflow and keep all implementation and
   coordination PRs open.
2. Reconcile implemented work, open PRs, research ideas and the existing backlog
   in one remaining-work inventory.
3. Keep parameter contracts, metric definitions and session branching as
   explicit follow-up decisions where the assessments find missing semantics.
4. Integrate the completed Docker branch separately; retain its native-x86 and
   live-integration limits until those checks run.

## Docker preflight

Disposable Alpine probes confirmed Linux, case-sensitive container storage, and
IPv4/IPv6 loopback with networking disabled. The pinned provider CLI packages
exist in npm. Their version and login-help probes passed in the app image.

Codex Advisor reviewed the approach before the plan was finalized. Its points
about installing the app separately, runtime cache ownership, relay network
access, and the memory test's scope are reflected in the implementation.
Detailed task reports and logs are retained alongside the progress ledger.

## Resuming

1. Read this page, then the [docs index](README.md) for where everything else
   lives.
2. Compare `git log --oneline -5 origin/main` and `gh pr list` with the tables
   above. When they disagree, trust git and fix this page.
