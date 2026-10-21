# Working state

Checkpoint as of 2026-10-21, after PRs #41 to #45 merged. This page records
current work and verification. The [docs index](README.md) describes the
permanent context and [open-items.md](open-items.md) holds unresolved work.

## Recent merges

Five backlog items merged by squash, each from its own branch:

- [PR #41](https://github.com/sunpar/quarry/pull/41) as `9ee780d`: a view's
  error boundary resets on every mount, so a repaired view that remounts under
  the same id drops its old error. A replaced view no longer posts an error
  under the next mount.
- [PR #42](https://github.com/sunpar/quarry/pull/42) as `12187af`: both Codex
  version checks are exact. The app-server's `userAgent` must start with
  `quarry/0.162.1`, and `CODEX_INTERNAL_ORIGINATOR_OVERRIDE` is stripped from
  its environment.
- [PR #43](https://github.com/sunpar/quarry/pull/43) as `33c9be6`: a 200 whose
  body does not decode, or that converts into missing or mistyped fields, is a
  `ProviderError`. The SDKs' own client-side errors still surface unchanged.
- [PR #44](https://github.com/sunpar/quarry/pull/44) as `0f9ef81`: tests check
  row order by the spec's keys, wait for the kernel to exit on shutdown, match
  full validator messages and test polars nulls-first directly.
- [PR #45](https://github.com/sunpar/quarry/pull/45) as `55ce496`: the
  Perspective filter mapping drops terms the kernel and the engine read
  differently: dates outside years 1 to 9999 or impossible days, and integer
  items that are not safe plain digits or exceed an Int8 to Int32 column's
  width.

A sixth branch, `claude/pivot-scrub-reset`, was dropped before its PR. Making a
missing pivot `config` reset the viewer changes what `config={undefined}` means
for agent-written views and writes a snapshot. The open items now ask what a
missing config should mean.

Each branch ran Opus 5.5 (xhigh), Astra 6 (medium) and Muse Wonder (high) once
before its PR. Opus raised findings on all five. Astra found nothing on four,
and Muse nothing on one. Valid findings were fixed or recorded in the open
items. On GitHub, Claude's first review found nothing blocking on all five, and
Codex's opening review was clean on all five.

Hosted Linux runs passed on each merged head:
[#41](https://github.com/sunpar/quarry/actions/runs/39591603201),
[#42](https://github.com/sunpar/quarry/actions/runs/39591763409),
[#43](https://github.com/sunpar/quarry/actions/runs/39593667373),
[#44](https://github.com/sunpar/quarry/actions/runs/39595515951) and
[#45](https://github.com/sunpar/quarry/actions/runs/39595748729). The full gate
on main at `55ce496` passed 1,357 Python tests (3 skipped) and 300 frontend
tests.

Running `uv run` in a fresh worktree installs Quarry into `.venv`, and
`make check` then stops at its dependency check; rerun `make deps` to recover.
Rerun it too after merging a lockfile change. The local reviewers' own probes
can trigger the same stop.

## Earlier merges

PRs #36 to #40 merged on 2026-10-21.
[PR #36](https://github.com/sunpar/quarry/pull/36) (`04c5ede`) closes a Codex
runtime past macOS's `EPERM` for an exiting process group;
[PR #37](https://github.com/sunpar/quarry/pull/37) (`49f012c`) keeps the version
only in `src/quarry/__init__.py`;
[PR #38](https://github.com/sunpar/quarry/pull/38) (`28f93fd`) treats a recipe
too deep for `ast.parse` as one that does not parse;
[PR #39](https://github.com/sunpar/quarry/pull/39) (`2ee4e70`) pins the OpenAI
request arguments and strict tool schemas;
[PR #40](https://github.com/sunpar/quarry/pull/40) (`0e32889`) falls back from a
stale session link. #36's last head had the same tree as main at `04c5ede` and
passed 1,326 Python tests (3 skipped) and 285 frontend tests.

PRs #30 to #35 merged on 2026-10-20.
[PR #30](https://github.com/sunpar/quarry/pull/30) (`75b100d`) makes Arrow bytes
that fail to decode the query's error state;
[PR #31](https://github.com/sunpar/quarry/pull/31) (`6894832`) checks the
permissions of the config file it read;
[PR #32](https://github.com/sunpar/quarry/pull/32) (`2db51e6`) retries a failed
Perspective engine start;
[PR #33](https://github.com/sunpar/quarry/pull/33) (`4caed85`) records a prompt
step's second `run_python` failure as its error;
[PR #34](https://github.com/sunpar/quarry/pull/34) (`efe9b27`) maps every SDK
`APIError` to a `ProviderError`;
[PR #35](https://github.com/sunpar/quarry/pull/35) (`fe92f3a`) keeps the last
4096 UTF-8 bytes of step output. Their gate on #35's merge with main passed
1,309 Python tests (3 skipped) and 277 frontend tests.

PRs #26 to #29 merged on 2026-10-17.
[PR #26](https://github.com/sunpar/quarry/pull/26) (`daead98`) keeps every step
that bound or changed an input a recipe reads;
[PR #28](https://github.com/sunpar/quarry/pull/28) (`2514219`) orders grouped
and pivoted rows by their keys;
[PR #29](https://github.com/sunpar/quarry/pull/29) (`dd611ab`) rejects nested
filter items and pivot value clashes. Their gate on #29's merge with main passed
1,295 Python tests (3 skipped) and 272 frontend tests.

[PR #27](https://github.com/sunpar/quarry/pull/27) merged as `3572008`. Both
table built-ins keep their last answer under a "Loading" status line while a
changed sort or filter loads, and the AG Grid table stays mounted.

PRs #18–#25 merged before it. Their combined head `4bbbeb4` passed full gates on
Mac and hosted Ubuntu with 1,238 Python, 270 frontend and 25 gate/transport
tests
([run 38664668771](https://github.com/sunpar/quarry/actions/runs/38664668771)).

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
