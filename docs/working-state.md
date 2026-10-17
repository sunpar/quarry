# Working state

Checkpoint as of 2026-10-17, with PR #26 open. This page records current work
and verification. The [docs index](README.md) describes the permanent context
and [open-items.md](open-items.md) holds unresolved work.

## Current work

[PR #26](https://github.com/sunpar/quarry/pull/26), "Keep steps that bind recipe
inputs", is open on main `3572008` from branch
`claude/token-usage-cleanup-c8c59f`, with CI Auto-fix on. Hosted CI runs only on
demand. It fixes the first known problem in the backlog and the priority-1 gap
in the workflow assessment. A saved recipe used to drop the step that bound a
parameter, import or lambda a later step read, and fresh replay failed with
`NameError`. A later `symbols.append(...)` or `params.update(...)` step was
dropped the same way.

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

Over eleven review rounds GitHub Codex raised fifteen findings, and later
commits fix thirteen:

- dunder dataset names lost their writes;
- the module check asked a proxy's raising `__class__`;
- stores to `__builtins__` or `__annotations__` were dropped. The executor now
  adds `__builtins__` before the first step, as `exec` would, and
  `__annotations__` is an ordinary name, so no special case remains;
- a `def` that never ran hid another store to its name, then replaced the
  helper's recorded body;
- a name bound to a helper, as `fetch = get_data`, or an instance of a helper
  class did not read what the helper reads;
- export ordering stopped seeing a recipe's `def` names;
- method calls and attribute stores in a class body, which runs with its
  definition, were not counted.

The later rounds found members of one family, objects reached through another
name, so the open items now record that family as one known problem, along with
a step reading later annotations. Claude's re-review found nothing blocking;
`e8c4b11` documents the two limits it raised.

`make check` on `8a65aba` passed with 1,257 Python tests (3 skipped), 270
frontend and 25 gate/transport tests in 78.28 s on macOS arm64. Hosted Linux
[run 39044174936](https://github.com/sunpar/quarry/actions/runs/39044174936)
passed on `135c818`. The pre-push check on `e8c4b11` passed 1,260 Python tests
with 3 skipped.

Running `uv run` in a fresh worktree installs Quarry into `.venv`, and
`make check` then stops at its dependency check; rerun `make deps` to recover.

## Main as of `3572008`

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

1. Merge PR #26 once `@claude` is clean on its head and hosted CI is green.
2. Select the next item from [open-items.md](open-items.md): the remaining
   correctness issues come first.
3. Decide workflow parameter contracts, metric validation and branching replay
   semantics before implementing those features.
4. Retain native-x86 and live-integration limits until their own checks run.

To resume, fetch main and compare `git log` and `gh pr list` with this page.
Update this checkpoint when repository state changes.
