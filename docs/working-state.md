# Working state

Checkpoint as of 2026-10-15 01:37 UTC, after the PR #18–#23 integration. This
page records current work and verification. The [docs index](README.md)
describes the permanent context and [open-items.md](open-items.md) holds
unresolved work.

## Integration status

All six requested PRs report merged. Final integration main is `c8a6f44`; its
files exactly match verified shared head `4bbbeb4`. Docker #24 and the
recall-test fix #25 are included. The primary checkout tracks current main.

| PR                                              | Result                                                                                                |
| ----------------------------------------------- | ----------------------------------------------------------------------------------------------------- |
| [#18](https://github.com/sunpar/quarry/pull/18) | Reproducible notebook exports with runtime-schema rendering and allowlisted runtime versions          |
| [#19](https://github.com/sunpar/quarry/pull/19) | Saved server-side table filters and sort                                                              |
| [#20](https://github.com/sunpar/quarry/pull/20) | Frozen, script-free HTML reports and private atomic export writes                                     |
| [#21](https://github.com/sunpar/quarry/pull/21) | One mount owner, reliable history-restore delivery and in-flight query reuse                          |
| [#22](https://github.com/sunpar/quarry/pull/22) | Bounded full-range line reduction with required null-gap endpoints; insufficient budgets are rejected |
| [#23](https://github.com/sunpar/quarry/pull/23) | Coordinated working state, backlog and assessment records                                             |

The export conflict retains runtime-schema rendering, protected helper bindings,
and the configured point budget. Appended export tests and feature-owned backlog
edits were reconciled. The shared candidate retains all original source heads
and the Docker changes. GitHub used squash merges, so main contains the combined
files rather than the original commit ancestry; the source branches remain
available.

[Docker PR #24](https://github.com/sunpar/quarry/pull/24) merged separately as
`3d9ab20`. [Recall-test PR #25](https://github.com/sunpar/quarry/pull/25) is a
separate task, merged as `663c9ff`. Its one-line wait synchronizes Recall with
completed new-session selection. Its author ran source-only reviews, as
requested in that task; the fresh combined checks include the merged test.

## Verification and review

The combined head `4bbbeb4` passed fresh full gates on Mac and hosted Ubuntu:
1,238 Python tests, 270 frontend tests and 25 gate/transport tests, plus lint,
formatting, types, build and offline wheel/sdist checks. Each environment had
three expected skips. Python took 71.37 seconds on Mac and 76.94 seconds on
Linux; the normal Mac outgoing gate and push took 111.24 seconds.
[Hosted run 38664668771](https://github.com/sunpar/quarry/actions/runs/38664668771)
records the exact Linux head. The final merged files match this tested tree.

The earlier combined hosted run at `8c1b0d1` failed an unchanged browser test,
`test_refused_import_offers_fix`, before the session view rendered: 1,237 Python
tests passed and three skipped. Six focused repeats passed after a fresh asset
build. No application change or test relaxation was made for that timeout. The
failed run and its logs remain in the integration ledger.

The staged commit smoke runs 24 Node gate tests, 154 Python tests and 41
frontend tests. Normal hooks verify the staged snapshot independently of
unstaged edits. The final commit timing is recorded in the integration ledger.

Each source PR completed its saved review workflow at its original delivery
head. The later combined and history heads did not receive another review round.
PR #18 received a clean Codex review at its original `7c59864` head; that review
does not cover the later combined head. PRs #19–#23 exhausted their GitHub bot
budgets without a clean verdict. All known findings were addressed and inline
threads resolved; the capped review rotation ended without a clean verdict.
Local Astra reviews completed, while Opus and Muse were unavailable because of
subscription limits. GitHub Claude failed before producing substantive reviews.
No review budgets were reset.

The merges occurred concurrently before the controller issued its final merge
command. PRs #20–#22 merged at 01:33:51–01:34:40 UTC, before the controller's
01:35:36 silence deadline. The controller issued no merge command and verified
the resulting main afterward. These merges do not establish a clean combined
review.

## Remaining work

The validated inventory preserves 266 stable IDs: 16 merged records and 250 open
records. The open work comprises 151 independent local follow-ups, 41 research
opportunities, 29 decisions or current limits, 17 external/platform checks, ten
intentional design deferrals and two optional maintenance choices. All 114
original backlog bullets and ten supplemental entries retain their source
mappings. No implemented-but-unmerged records remain.

The backlog also removes the completed notebook-route query and default-output
test gaps. CLI project-subcommand and filesystem-write-failure coverage remain
open. The backlog removes the resolved schema-free notebook rendering, duplicate
mount, truncated long-series and CLI export-permissions problems. PR #27 keeps
table rows visible while a changed sort or filter query loads. Completed-result
query caching remains open; the implementation reuses only concurrent requests.
Restoring the latest saved snapshot automatically on mount remains deferred; the
history-restore fix covers scrubber selections.

The workflow assessment prioritizes scalar and dictionary dependency capture
before reusable parameter contracts. Metric definitions and content validation
still need product decisions. The branching assessment found prefix replay with
current inputs feasible; immutable historical inputs and side-effect behavior
remain undecided. These assessments do not implement workflows or branching.

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

1. Select follow-up work from the validated inventory and preserve its stable
   source identities when priorities or implementations change.
2. Prioritize scalar dependency capture and the remaining correctness issues in
   [open-items.md](open-items.md).
3. Decide workflow parameter contracts, metric validation and branching replay
   semantics before implementing those features.
4. Retain native-x86 and live-integration limits until their own checks run.

To resume, fetch main and compare `git log` and `gh pr list` with this page.
Update this checkpoint when repository state changes.
