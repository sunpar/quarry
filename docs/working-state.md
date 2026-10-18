# Working state

Checkpoint as of 2026-10-17, after PRs #26, #28 and #29 merged. This page
records current work and verification. The [docs index](README.md) describes the
permanent context and [open-items.md](open-items.md) holds unresolved work.

## Recent merges

[PR #26](https://github.com/sunpar/quarry/pull/26) merged as `daead98`. A saved
recipe now keeps every step that bound or changed an input it reads: `defines`
lists every non-dataset name a step binds, later loads of those names are reads,
and a statement that calls a method and drops the result binds its object. A
load after the step's own module-body store of a name is not a read, so steps
that reuse `cols` or `import json` stay out of each other's recipes. The rules
and their costs are in [decisions](context/decisions.md#lineage), and spec §6 is
amended. Lineage follows names, not objects; the open items record that as a
known problem, beside the remaining blind spots.

GitHub Codex raised fifteen findings on #26 over eleven rounds; thirteen are
fixed and two documented, and Claude's last GitHub review was clean at
`45920cc`. The local Opus review on `45920cc` raised fourteen: `a24281f` fixes
its main one, recipes that replayed most of a session, plus three smaller ones,
and documents the rest. Astra found nothing actionable, and Muse timed out at 20
minutes. `make check` on `a24281f` passed with 1,287 Python tests (3 skipped)
and 272 frontend tests, and hosted Linux
[run 39065891972](https://github.com/sunpar/quarry/actions/runs/39065891972)
passed on the same head.

[PR #28](https://github.com/sunpar/quarry/pull/28) merged as `2514219`. Grouped
and pivoted rows sort by `sort`, then by each group key or pivot index column it
leaves out, on every target and in generated code, so paging through them is
stable. Hosted
[run 39070046585](https://github.com/sunpar/quarry/actions/runs/39070046585)
passed on its merge with main.

[PR #29](https://github.com/sunpar/quarry/pull/29) rejects nested filter items
and repeated pivot index columns, and a pivot value named like an index column
is now a query error; aggregate type errors still surface raw. Its pre-push gate
on the merge with main passed 1,295 Python tests (3 skipped) and 272 frontend
tests.

Running `uv run` in a fresh worktree installs Quarry into `.venv`, and
`make check` then stops at its dependency check; rerun `make deps` to recover.

## Earlier merges

[PR #27](https://github.com/sunpar/quarry/pull/27) merged as `3572008`. Both
table built-ins keep their last answer under a "Loading" status line while a
changed sort or filter loads, and the AG Grid table stays mounted. `make check`
on `cf3e01f` passed with 1,238 Python tests (3 skipped), 272 frontend and 25
gate/transport tests; Codex and Claude found nothing to fix at `d62a299`.

PRs #18–#25 merged before it. Their combined head `4bbbeb4` passed full gates on
Mac and hosted Ubuntu with 1,238 Python, 270 frontend and 25 gate/transport
tests
([run 38664668771](https://github.com/sunpar/quarry/actions/runs/38664668771)).
Each source PR completed its saved review workflow at its original head, but the
combined head received no further review round. PRs #19–#23 exhausted their
GitHub bot budgets without a clean verdict after all known findings were
addressed.

## Remaining work

The validated inventory preserves 266 stable IDs: 16 merged records and 250 open
records. PR #26 implemented the module-binding dependency record. The workflow
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

1. Select the next item from [open-items.md](open-items.md): the remaining
   correctness issues come first.
2. Decide workflow parameter contracts, metric validation and branching replay
   semantics before implementing those features.
3. Retain native-x86 and live-integration limits until their own checks run.

To resume, fetch main and compare `git log` and `gh pr list` with this page.
Update this checkpoint when repository state changes.
