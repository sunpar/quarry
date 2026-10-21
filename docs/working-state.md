# Working state

Checkpoint as of 2026-10-21, after PRs #52 to #58 merged. This page records
current work and verification. The [docs index](README.md) describes the
permanent context and [open-items.md](open-items.md) holds unresolved work.

## Recent merges

Seven backlog items merged by squash, each from its own branch:

- [PR #52](https://github.com/sunpar/quarry/pull/52) as `56979ae`: `for_viewer`
  casts Float16 to Float64 and unwraps extension columns to their converted
  storage, so Perspective loads them.
- [PR #53](https://github.com/sunpar/quarry/pull/53) as `88990ce`: a canvas card
  shows "Loading" or its saved view's error, a card whose view has left the
  project can be removed, every canvas error shows, and Dismiss clears only
  failed actions.
- [PR #54](https://github.com/sunpar/quarry/pull/54) as `5dfe9c5`: a failed
  `write_atomic` names its target, not its temporary file, in the CLI and the
  web app.
- [PR #55](https://github.com/sunpar/quarry/pull/55) as `ce341cb`: OHLC compares
  names ignoring case for its guesses, saved columns and pickers, and keeps its
  pickers when a role is left empty.
- [PR #56](https://github.com/sunpar/quarry/pull/56) as `6018a1d`: "To code" is
  off while its drawer is open, Stop shows only while a step runs, and the
  status reads the running step under its lock.
- [PR #57](https://github.com/sunpar/quarry/pull/57) as `d1b88c8`: a component
  save that fails removes what it wrote, so its id is free again, and the
  components root is fsynced.
- [PR #58](https://github.com/sunpar/quarry/pull/58) as `1526241`: "To code",
  "Save view" and "Pin to canvas" use the snapshot picked in the scrubber, named
  by its server `ts`.

Each branch ran Opus 5.5 (xhigh), Astra 6 (medium) and Muse Wonder (high) once
before its PR. Opus raised findings on all seven, Astra on two and Muse on four.
Valid findings were fixed or recorded in the open items. #58 was reworked after
Opus: it first counted snapshots back from the newest, which named the wrong
snapshot whenever the host's cached list and the server's differed. On GitHub,
Claude's first review was clean on all seven. Codex's opening review was clean
on six; on #58 it found a pick of the latest that stopped following newer
snapshots, fixed before the merge.

Hosted Linux runs passed on each merged head:
[#52](https://github.com/sunpar/quarry/actions/runs/39633997207),
[#53](https://github.com/sunpar/quarry/actions/runs/39634119822),
[#54](https://github.com/sunpar/quarry/actions/runs/39634430648),
[#55](https://github.com/sunpar/quarry/actions/runs/39635034618),
[#56](https://github.com/sunpar/quarry/actions/runs/39636240307),
[#57](https://github.com/sunpar/quarry/actions/runs/39636594487) and
[#58](https://github.com/sunpar/quarry/actions/runs/39642833360). The full gate
on main at `1526241` passed 1,381 Python tests (3 skipped) and 334 frontend
tests.

Running `uv run` in a fresh worktree installs Quarry into `.venv`, and
`make check` then stops at its dependency check; rerun `make deps` to recover.
Rerun it too after merging a lockfile change. The local reviewers' own probes
can trigger the same stop. Under plain `pytest` in a worktree,
`test_dataset_script_has_a_header_and_the_recipe` fails because its `python -I`
child cannot import Quarry; `make check` installs the package for it.

## Earlier merges

PRs #46 to #51 merged on 2026-10-21.
[PR #46](https://github.com/sunpar/quarry/pull/46) (`5e679e9`) types the filter
op sets and limits the Duration guard to milliseconds;
[PR #47](https://github.com/sunpar/quarry/pull/47) (`b3c61c0`) lets the save
dialog take a project list that arrives late;
[PR #48](https://github.com/sunpar/quarry/pull/48) (`016e067`) keeps chart
pickers above a loading or failed query;
[PR #49](https://github.com/sunpar/quarry/pull/49) (`c89fba4`) checks the
components folder at startup and cuts long ids;
[PR #50](https://github.com/sunpar/quarry/pull/50) (`2e9a532`) replaces a
snapshot whose state repeats; [PR #51](https://github.com/sunpar/quarry/pull/51)
(`b3ababf`) closes the Stage 5 server and CLI test gaps. Their gate on main at
`b3ababf` passed 1,372 Python tests (3 skipped) and 319 frontend tests.

PRs #41 to #45 merged on 2026-10-21.
[PR #41](https://github.com/sunpar/quarry/pull/41) (`9ee780d`) resets a view's
error boundary on every mount;
[PR #42](https://github.com/sunpar/quarry/pull/42) (`12187af`) makes both Codex
version checks exact; [PR #43](https://github.com/sunpar/quarry/pull/43)
(`33c9be6`) turns malformed provider responses into provider errors;
[PR #44](https://github.com/sunpar/quarry/pull/44) (`0f9ef81`) checks row order
by key and waits for the kernel to exit in tests;
[PR #45](https://github.com/sunpar/quarry/pull/45) (`55ce496`) drops Perspective
filter terms the kernel and engine read differently. Their gate on main at
`55ce496` passed 1,357 Python tests (3 skipped) and 300 frontend tests. A sixth
branch, `claude/pivot-scrub-reset`, was dropped: the open items ask what a
missing pivot `config` should mean.

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
Perspective engine start; [PR #33](https://github.com/sunpar/quarry/pull/33)
(`4caed85`) records a prompt step's second `run_python` failure as its error;
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
   correctness issues come first. Unwrapping extension columns where the kernel
   takes a frame would let pivot queries filter and aggregate them.
2. Settle the choices that block small items, listed under Open questions: what
   a missing pivot `config` means, when paged sorts get a tie-breaker, which
   code a busy session's component save returns, and how long recipe validation
   may run.
3. Decide workflow parameter contracts, metric validation and branching replay
   semantics before implementing those features.
4. Retain native-x86 and live-integration limits until their own checks run.

To resume, fetch main and compare `git log` and `gh pr list` with this page.
Update this checkpoint when repository state changes.
