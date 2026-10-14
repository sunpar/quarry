# Test Quarry on Linux from macOS implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans
> or superpowers:subagent-driven-development to implement this plan task by
> task. Steps use checkbox syntax for tracking.

**Goal:** Run Quarry's full Linux verification and use its Linux-hosted browser
UI from a Mac, without changing the Mac's dependencies or Quarry data.

**Architecture:** Build Linux images from a filtered copy of the current working
tree. A test image runs the existing offline gate; an interactive image installs
Quarry and its native provider CLIs. Docker Compose connects the Mac browser
through a relay and keeps interactive state in a Linux volume.

**Tech stack:** Docker Desktop, Docker Compose, Debian Bookworm, Python 3.11,
Node 24, uv 0.10.9, Chromium, socat, and Quarry's existing verification
commands.

**Spec:** The [Quarry design](../specs/2026-10-08-quarry-design.md) and
[constraints](../../context/constraints.md) remain binding. The proposed Docker
design and implementation steps are below. This is a plan; implementation has
not started.

## Intent and success criteria

You want to test Linux behavior while developing on macOS. You confirmed that
the plan should cover automated tests and interactive browser use.

Success means one command runs the existing full gate inside Linux, including
real kernel subprocesses and browser tests. A second command starts an installed
Quarry app that you can open in the Mac browser. Sessions, projects, and
optional provider logins survive container recreation in a separate development
volume.

## Why use Docker

Docker Desktop runs Linux containers inside a Linux virtual machine on macOS. It
can exercise Linux resource limits, processes, sockets, and filesystem behavior
without a separate development machine. See
[Docker's Mac architecture](https://docs.docker.com/desktop/setup/install/mac-permission-requirements/).

This Mac already has a working Linux ARM Docker engine and Compose. Disposable
Alpine probes confirmed Linux, a case-sensitive container filesystem, and both
IPv4 and IPv6 loopback with `--network none`. A Quarry image has not been built
or tested yet.

Choose Docker over a full Linux VM for this task because Quarry already has
local test fixtures and one shared verification command. A VM adds operating
system administration; the existing manual Linux CI remains useful for native
server checks but cannot provide this local interactive workflow.

## Global constraints

- Keep `make deps`, `make check`, and `make coverage` as the owners of setup and
  verification; do not duplicate their test lists
- Match `.python-version` (3.11), the CI Node major (24), `uv.lock`, and
  `web/package-lock.json`; pin container tool versions and image digests
- Keep Quarry's server on `127.0.0.1` and retain its per-run bearer token
- Run tests and the interactive app as the unprivileged `quarry` user
- Keep test setup online and test execution offline, with fake providers and
  synthetic local data
- Copy source into Linux storage; do not bind-mount the Mac checkout, virtual
  environments, dependency directories, Quarry state, or provider credentials
- Preserve the existing Git hooks, PR checks, and manual hosted verification
- Do not add production deployment, external database provisioning, or Vite
  iframe fixes to this work

## Container design

### Images and dependencies

Use one Dockerfile with `check` and `app` targets. Start with a glibc-based
Python 3.11 Bookworm image, copy Node 24 and uv 0.10.9 from their official
images, and install Git, Make, and socat. Avoid Alpine for Quarry's Python and
Chromium dependencies.

Copy dependency manifests, the Makefile, and the setup script before source so
source edits can reuse dependency layers. Run `make deps` as root during the
build because Playwright's Linux setup installs operating system packages. Store
`UV_CACHE_DIR` and `PLAYWRIGHT_BROWSERS_PATH` under `/opt`, then give `quarry`
ownership of those caches and `/workspace`.

Keep the uv cache in the image: `make check` needs it to create `.check-venv`
offline. A BuildKit cache mount alone would disappear at runtime. Do not mount
host caches or reuse dependency volumes across platforms. Preserve `.venv`
without Quarry installed because its dependency fingerprint checks that fact.

Build the static UI from source. The `app` target additionally builds the wheel,
creates `/opt/quarry-runtime` from the lock with the `claude-code` extra, and
installs that wheel with `--no-deps`. Start the app through
`/opt/quarry-runtime/bin/quarry`; the test environment remains separate.

Only the `app` target installs the supported native CLIs:

- `@openai/codex@0.162.1`
- `@anthropic-ai/claude-code@2.1.299`

These versions match the existing adapters and were found in the npm registry.
Run neither login nor inference during builds or routine verification.

### CPU architecture and resources

Default `LINUX_PLATFORM` to the Docker server's operating system and
architecture, using `docker version --format '{{.Server.Os}}/{{.Server.Arch}}'`.
This Mac uses `linux/arm64`. Allow `LINUX_PLATFORM=linux/amd64` for x86
compatibility checks; use platform-specific image tags and Compose project
names.

Docker Desktop supports architecture emulation, but compute-heavy builds can be
slower. Emulated x86 tests do not establish native x86 timing or kernel
resource-limit behavior. See
[Docker's multi-platform guidance](https://docs.docker.com/build/building/multi-platform/).

Start with about 8 GB of Docker VM memory and at least four CPU cores; measure
the full suite before documenting a minimum. Set `shm_size: 1gb` and
`init: true` for Chromium and child-process cleanup. Shared-memory size is a
ceiling, not a RAM reservation. Do not set a container data-segment limit that
could override the kernel's own configuration.

### Automated verification

The `check` service runs `make check` with `network_mode: none`, no published
ports, and no persistent mounts. Confirm both `127.0.0.1` and `::1` work before
accepting that configuration; existing transport tests exercise both.

The full gate already covers lint, types, frontend tests, the built UI, Chromium
end-to-end tests, offline packaging, and Python tests. In particular,
`test_kernel_applies_the_configured_memory_cap` must execute on Linux. It checks
the configured 4096 MiB `RLIMIT_DATA`; it does not test allocation exhaustion or
a container's total memory limit. The filesystem case-folding test can retain
its existing skip on a case-sensitive filesystem, as it does in Linux CI.

Reuse `make coverage` when requested. Document how to run a named container and
copy `coverage.xml` out before removing it, rather than adding a report mount
that changes the default test environment. These commands test the copied
working tree; they do not replace exact-index or outgoing-commit Git gates.

### Interactive app and browser connection

Start Quarry with its installed CLI, `--port 8765`, and
`--root /home/quarry/.quarry`. Keep a named volume at `/home/quarry`,
initialized with a private directory owned by `quarry`. It holds development
sessions, projects, config, and optional native provider logins. No dependency
directory or runtime environment lives under that mounted home.

Port publishing cannot reach the current loopback listener directly. Add a
`relay` service using the same image and `network_mode: service:quarry`. Run
socat from container port 8766 to `127.0.0.1:8765`, and publish only
`127.0.0.1:8765:8766` on the `quarry` service. The existing token-bearing URL
then works in the Mac browser; the banner's SSH instruction is unnecessary for
this Docker workflow.

The relay listens on the container interface, while Quarry itself retains its
loopback binding. Give this Compose project a dedicated bridge network with no
unrelated services. Peer containers attached to that network could reach the
relay; host publishing remains localhost-only. See
[Docker's port publishing rules](https://docs.docker.com/engine/network/port-publishing/).

Allow network access for interactive use. Sign in inside the container as
`quarry`, using `codex login --device-auth` or `claude auth login`, then select
the provider in its own `config.toml`. Keep API keys opt-in through the existing
key-file configuration. Do not pass provider credentials to the `check` service.

Manual Python steps through `/sessions/{session_id}/steps/manual` and browsing
saved results require no live provider. The UI uses prompts to create new views,
so that interactive flow needs a configured provider. Without one, prompts
report an error and dataset saves keep raw recipes. Existing fake-provider
browser tests cover rendering, save, recall, and canvas flows deterministically;
do not introduce a fake-provider mode into the production CLI. Actual
subscription authentication, quota, external SQL Server, firm loaders, and
licensed charts need separate opt-in checks.

## Review focus

Exercise these conditions during the tasks that own them:

- A changed lockfile or source edit must rebuild the relevant Linux image,
  rather than reuse a stale checkout or dependency stamp
- A non-root offline run must find Chromium and the uv cache, build assets,
  create `.check-venv`, and retain IPv6 loopback
- A failed check must return a nonzero status through Docker and Make
- The browser must reach the relay with authentication; neither the app nor the
  host's published port should become a general network listener
- Fresh state must be writable and private; recreation must retain state, and
  stopping the app must stop its relay and kernel processes

## Task 1: Build the Linux verification image

**Files:** Create `Dockerfile` and `.dockerignore`.

**Interface:** Dockerfile target `check`, working directory `/workspace`,
unprivileged user `quarry`, default command `make check`.

- [ ] Allowlist repository build inputs in `.dockerignore`, including the docs
      that the gate formats. Exclude `.git`, all environments and caches,
      generated static assets, reports, local config, data, and credentials.
- [ ] Implement the dependency and source layers described above. Pin image
      digests and preserve offline uv and Chromium files in the resulting image.
- [ ] Build the `check` target for native Linux. Inspect Python, Node, uv,
      operating system, user, cache ownership, and absence of host artifacts.
- [ ] Run the configured-memory-cap test and `tests/kernel/test_client.py` with
      `PYTHONPATH=src` and `.venv/bin/python -m pytest -n 0`. Both must pass;
      the Linux memory-cap test must not skip.
- [ ] Run `make check` inside a fresh container with no network. Confirm that
      all browser tests execute and only documented platform/live-provider skips
      remain.

## Task 2: Expose Linux checks through repository commands

**Files:** Create `compose.yaml`; modify `Makefile`.

**Interfaces:** `check` Compose service; `LINUX_PLATFORM`; `make linux-build`,
`make linux-check`, and `make linux-shell`. Linux recipes export the selected
platform and scope image tags and the Compose project name to it.

- [ ] Add the `check` service, network isolation, init process, and
      shared-memory setting. Keep all source and dependency mounts absent.
- [ ] Add Make targets that build the selected image before running it.
      `linux-check` invokes `make check`; `linux-shell` opens the same image for
      focused tests. Keep Docker discovery confined to Linux targets so ordinary
      Mac commands do not require a running daemon.
- [ ] Run `make linux-check` from the Mac and record elapsed time and test
      outcomes. Confirm IPv4 and IPv6 transport tests pass.
- [ ] Change a source file and rebuild in a disposable worktree; confirm the
      container sees the change. Repeat with a lockfile change and verify setup
      reruns rather than accepting a stale stamp.
- [ ] Corrupt a dependency stamp in a disposable container and confirm the
      existing gate fails. Run a failing container command through Make and
      confirm its exit status is preserved.
- [ ] Repeat the full check with `LINUX_PLATFORM=linux/amd64`. If emulation
      prevents a check, record that limitation and use current-head manual
      native Linux CI before claiming x86 coverage; do not add skips.

## Task 3: Start an installed app for interactive use

**Files:** Extend `Dockerfile`, `compose.yaml`, and `Makefile`.

**Interfaces:** Dockerfile target `app`; Compose services `quarry` and `relay`;
`make linux-serve` and `make linux-down`; localhost URL on port 8765.

- [ ] Build and install the wheel into `/opt/quarry-runtime`, using locked
      runtime dependencies and the `claude-code` extra. Install the two pinned
      native CLIs. Keep `.venv` compatible with its existing fingerprint.
- [ ] Add the private home volume, dedicated network, loopback port mapping, and
      relay. `linux-serve` builds the app and starts both services in the
      foreground; `linux-down` stops them without deleting the volume.
- [ ] Confirm `/healthz` responds from the Mac, `/sessions` rejects a missing
      token, and the printed token URL opens the built UI. Inspect the actual
      listeners and port mapping.
- [ ] Submit synthetic data through the existing manual-step API, query it, save
      a pinned dataset, recall it, and export a notebook. Confirm the Mac
      browser displays those steps and the export uses Linux paths. The full
      gate's fake-provider browser tests verify view rendering and canvas use.
- [ ] Recreate the app and check that saved state remains, its modes are
      private, and the Mac's existing Quarry data is untouched. Stop the Compose
      project and check for leftover app, relay, and kernel processes.
- [ ] Verify the pinned CLI versions and the login instructions without starting
      live inference. When explicitly requested, test provider login and one
      synthetic prompt that renders a table in this development volume. Bound
      the probe to five minutes and five model requests, including tool
      follow-ups, and omit model-assisted saves from that probe. Report quota,
      authentication, and request-budget limits separately from offline results.

## Task 4: Document usage and record acceptance evidence

**Files:** Modify `README.md`, `docs/context/code-map.md`,
`docs/context/decisions.md`, and `docs/working-state.md`.

- [ ] Add a Linux-on-Mac section with prerequisites,
      build/check/shell/serve/down commands, rebuild behavior, provider setup,
      and report export.
- [ ] Describe the home volume and an explicit destructive reset command;
      ordinary shutdown must retain it. Explain that source edits require a
      rebuild and that this workflow uses the production UI build.
- [ ] Record native versus emulated coverage, the memory-cap test's scope,
      aggregate resource usage, and exclusions for live or licensed
      integrations.
- [ ] Review prose with `writing-guidelines`, format the touched Markdown, and
      run the unchanged Mac gate and the new Linux gate on the implementation
      head. Keep test counts and timings in working state.
- [ ] Record Docker-specific choices in decisions and file responsibilities in
      the code map. Leave hosted workflows and operation-boundary gates intact.

## Delivery boundary

The initial implementation is development tooling and documentation: two Docker
image targets, Compose services, and Make commands. It changes no Quarry
application behavior. Builds may download dependencies; routine verification
uses no cloud resources. Docker's Linux VM does not reproduce every native
server kernel, CPU, filesystem, database, or provider environment.
