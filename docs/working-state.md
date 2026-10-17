# Working state

Checkpoint as of 2026-10-17, with PRs #26 and #27 open. This page records
current work and verification. The [docs index](README.md) describes the
permanent context and [open-items.md](open-items.md) holds unresolved work.

## Current work

Two independent PRs are open on main `c37524b`, each with CI Auto-fix on. Hosted
CI runs only on demand.

### PR #26: recipe input lineage

[PR #26](https://github.com/sunpar/quarry/pull/26), "Keep steps that bind recipe
inputs", is open from branch `claude/token-usage-cleanup-c8c59f`. It fixes the
first known problem in the backlog and the priority-1 gap in the workflow
assessment. A saved recipe used to drop the step that bound a parameter, import
or lambda a later step read, and fresh replay failed with `NameError`. A later
`symbols.append(...)` or `params.update(...)` step was dropped the same way.

- `defines` now lists every non-dataset name a step binds, and later loads of
  those names are reads. Module-level method calls whose result is dropped bind
  their object, unless it holds a dataset or a module. The rules and their costs
  are in [decisions](context/decisions.md#lineage), and spec §6 is amended.
- A store that left a known name holding the same object also reads it, so a
  store that never ran keeps the earlier producer.
- What lineage still misses is in the open items' lineage blind spots, including
  a change made through an alias.

Local Claude and Codex reviews of the first commit found two regressions, fixed
with tests in the second commit, plus a freed weak reference that matched `None`
and the missing method-call rule. The prompt-step fold still counts a failed
call's bindings, by choice; the fold decision records why.

GitHub's Claude review found nothing blocking. GitHub Codex raised three
findings on `8a65aba`. Commit `00a0a26` fixes two: dunder dataset names lost
their writes, and the module check asked a proxy's raising `__class__`. The
third, a change through an alias, is recorded as a blind spot. All three threads
are answered and resolved, and a Codex re-review is requested.

`make check` on `8a65aba` passed with 1,257 Python tests (3 skipped), 270
frontend and 25 gate/transport tests in 78.28 s on macOS arm64. Hosted Linux
[run 39044174936](https://github.com/sunpar/quarry/actions/runs/39044174936)
passed on `135c818`. The pre-push check on `00a0a26` passed 1,259 Python tests
with 3 skipped and 270 frontend tests.

### PR #27: table rows during refetch

[PR #27](https://github.com/sunpar/quarry/pull/27), "Keep table rows visible
while a changed query loads", is open from branch `claude/table-row-retention`.
Both table built-ins now keep their last answer under a "Loading" status line
while a changed sort or filter loads, and the AG Grid table stays mounted. The
decision is in [decisions](context/decisions.md), next to the other table
decisions. Its browser assertion fails against the old components.

`make check` on `cf3e01f` passed with 1,238 Python tests (3 skipped), 272
frontend and 25 gate/transport tests in 77.92 s. The PR wrapper re-verified it.
`@codex review` and `@claude review` are requested.

Running `uv run` in a fresh worktree installs Quarry into `.venv`, and
`make check` then stops at its dependency check; rerun `make deps` to recover.

## Main as of `c37524b`

PRs #18–#25 are merged. Their combined head `4bbbeb4` passed full gates on Mac
and hosted Ubuntu with 1,238 Python, 270 frontend and 25 gate/transport tests
([run 38664668771](https://github.com/sunpar/quarry/actions/runs/38664668771)).
Each source PR completed its saved review workflow at its original head, but the
combined head received no further review round. PRs #19–#23 exhausted their
GitHub bot budgets without a clean verdict after all known findings were
addressed.

## Remaining work

The validated inventory preserves 266 stable IDs: 16 merged records and 250 open
records. PR #26 implements the module-binding dependency record. The workflow
assessment's next step after it, reusable parameter contracts, needs a product
decision on which repeated workflow takes replacement inputs. Metric definitions
and content validation also need product decisions. The branching assessment
found prefix replay with current inputs feasible; immutable historical inputs
and side-effect behavior remain undecided.

Local evidence lives under `/Users/sunpar/Documents/Codex/2026-10-14/`:

- `quarry-integration-check/outputs/integration_verification.json`
- `quarry-backlog-inventory/outputs/quarry_remaining_work.json` and its offline
  HTML companion
- `quarry-workflow-assessment/outputs/workflow_assessment.json`
- `quarry-branching-assessment/outputs/branching-assessment.json`

These are local reports, not repository files. Per-PR review budgets, exact
reviewed commits and gate results remain in the worktree Git directories as
`open-pr-and-babysit.json`. The controller's integration record is
`.git/quarry-merge-prs-18-23.json`.

## Docker evidence and limits

Docker's reviewed source head `6f5feea` passed hosted Linux CI and separate Mac
and Linux gates with 1,069 Python, 235 frontend and 25 gate/transport tests.
After the research features were combined, a tree identical to `3d9ab20` passed
Mac and native ARM64 Docker checks with 1,238 Python, 270 frontend and 25 gate
tests. The Python portions took 83.32 and 95.56 seconds respectively. Docker's
Astra and GitHub Codex reviews found no actionable issues; Opus and Muse hit
subscription limits, and GitHub Claude failed before review.

Earlier emulated AMD64 verification passed at `9ff7579`; emulation does not
establish native x86 behavior. Interactive acceptance ran on native ARM64 and
covered token checks, synthetic Python/query, save/recall, notebook export,
private modes, recreation, token rotation and shutdown. Port 18765 was used
because an unrelated service owns the default 8765 port. No owned container or
project network remains; the private development volume retains synthetic data.

A bounded ARM64 resource run measured 4,806,164,480 bytes of cgroup memory peak,
including charged filesystem cache. This is a workload observation, not a
minimum VM requirement. Linux checks exercise a 4,096 MiB `RLIMIT_DATA` setting,
not allocation exhaustion or total container memory. Quarry cannot enforce its
kernel memory cap on macOS. Live provider inference, firm data and licensed
integrations remain unverified. Existing dependency deprecation and bundle-size
warnings remain.

## Next actions

1. Address bot review findings on PRs #26 and #27 until `@codex` and `@claude`
   are clean, then merge each once CI is green.
2. Select the next item from [open-items.md](open-items.md): the remaining
   correctness issues come first.
3. Decide workflow parameter contracts, metric validation and branching replay
   semantics before implementing those features.
4. Retain native-x86 and live-integration limits until their own checks run.

To resume, fetch main and compare `git log` and `gh pr list` with this page.
Update this checkpoint when repository state changes.
