# Quarry

Agentic data exploration for quant researchers. See the
[design spec](docs/superpowers/specs/2026-10-08-quarry-design.md).

Project docs, starting with the current working state, are indexed in
[docs/README.md](docs/README.md).

## Development

```bash
make deps       # online dependency and Chromium setup, required after lock changes
make hooks      # enable staged smoke and open-PR push checks
make smoke      # check the exact staged snapshot
make check      # offline lint, types, all tests, browser E2E and packaged assets
make coverage   # the same checks with Python branch coverage
make pr ARGS='--title "Change behavior" --body-file /path/to/body.txt'
```

`make hooks` stores a stable bootstrap in this worktree's Git directory. Rerun
it after gate updates. Branches missing the verifier fail and require an update
from `origin/main`; switching branches no longer removes installed hooks.

The PR wrapper supports `--title` (required), `--body`, `--body-file`, `--base`,
`--draft` and `--no-maintainer-edit`; `make pr ARGS=--help` lists short aliases.
It resolves the base before pushing and rejects a head/base match within the
same repository. It verifies and pushes the committed snapshot, then creates the
PR through the GitHub API, with the fork repository identified explicitly.
Required self-assignment runs after creation, so a metadata permission failure
leaves the created PR URL visible. Push hooks verify the actual outgoing commits
for branches with open PRs, including upstream fork PRs, and for `main`. Missing
tools, mismatched dependency locks and failed PR lookups stop the operation. Use
`make check-commit REF=<sha>` to check a specific commit.

Git has no PR-creation hook. Website/API PR creation, direct `gh pr create`,
`--no-verify`, and uninstalled hooks can bypass these local gates.

GitHub verification is manual: choose full, smoke or coverage and Linux or macOS
in the `ci` workflow. Linux retains the kernel memory-cap check that macOS
cannot run. Claude review is manual or requested through the existing `@claude`
workflow. No branch protections or rulesets required hosted checks at migration
time.

Test commands remove live provider credentials, restrict Python/Node sockets to
loopback and Unix sockets, and route browser HTTP requests to local servers.
This is transport-level enforcement, not an operating-system network sandbox;
native-library networking and other browser transports are outside that
boundary. Tests use fake providers and synthetic local data. Licensed
Highcharts/SciChart browser coverage and live providers remain outside the local
gate.

## Test Linux from macOS with Docker

Start Docker Desktop with its Compose plugin, then run the Linux gate from the
repository root:

```bash
make linux-check
```

The command builds a Linux image from the current working tree and runs the
existing `make check` with networking disabled. It includes real kernel
subprocesses, Chromium browser tests, and the Linux memory-cap test. The image
keeps its own locked dependencies and caches; it never mounts your Mac checkout,
virtual environment, Quarry data, or provider credentials. Dependency downloads
happen during the image build.

`make linux-build` builds the check image without running tests.
`make linux-shell` rebuilds it and opens Bash for focused checks. Source and
lockfile changes require a rebuild, which these Make commands perform before
running. The images use the built browser UI. They do not run Vite or mount your
working tree for live editing.

The default platform follows the Docker server. On Apple Silicon, use this
explicit override to check x86 compatibility:

```bash
make linux-check LINUX_PLATFORM=linux/amd64
```

Each platform gets its own image tags and Compose project. AMD64 runs through
emulation on an ARM Docker host; its results do not establish native x86 timing
or kernel resource behavior. The memory-cap test reads the configured Linux
data-segment limit, not allocation exhaustion or total container memory. The
[working state](docs/working-state.md) records measured virtual machine
resources, memory usage, timings, and current platform coverage. Those
measurements apply to the verification workload, not a minimum memory
requirement.

Docker checks test the copied working tree. Continue using the staged and
committed Git gates for their exact snapshots. Hosted checks remain manual. Live
providers, external SQL Server, firm loaders, and licensed chart libraries need
separate opt-in checks.

### Use the Linux app in your Mac browser

Start the installed app and its relay in the foreground:

```bash
make linux-serve
```

Open the printed `http://127.0.0.1:8765/` link, including its token fragment.
The banner's SSH tunnel instruction is unnecessary for Docker. Quarry keeps its
loopback listener; the relay publishes only on your Mac's localhost. Containers
attached to this project's dedicated bridge can also reach the relay and still
need the token. If port 8765 is occupied, use the
[temporary port override](#use-another-localhost-port).

The named home volume keeps Linux sessions, projects, configuration, and native
provider logins across container recreation. Its Quarry root is
`/home/quarry/.quarry`. This state is separate from your Mac's `~/.quarry`.
Manual Python steps through `/sessions/{session_id}/steps/manual` need no
provider. Prompts that create views require one; the routine browser tests use
fake providers instead.

For direct Compose commands below, select the same platform as `linux-serve`.
These variables select the Docker server's platform; for an override, set
`LINUX_PLATFORM` to that value before deriving `LINUX_PLATFORM_TAG`:

```bash
export LINUX_PLATFORM="$(docker version \
  --format '{{.Server.Os}}/{{.Server.Arch}}')"
export LINUX_PLATFORM_TAG="${LINUX_PLATFORM//\//-}"
```

The app image already includes the supported Codex and Claude Code CLIs and the
Claude SDK. Sign in inside the container as its `quarry` user, following the
CLI's instructions:

```bash
docker compose --project-name "quarry-${LINUX_PLATFORM_TAG}" \
  exec quarry codex login --device-auth
```

For Claude Code, use:

```bash
docker compose --project-name "quarry-${LINUX_PLATFORM_TAG}" \
  exec quarry claude auth login
```

Edit `/home/quarry/.quarry/config.toml` inside the container using the
[native-login settings](#using-codex-or-claude-code-login), then restart the
app. For API providers, place the key file in that private Linux home and
configure `api_key_file`. Compose does not forward your Mac's provider
environment variables. Login, account access, quota, and inference remain
outside the offline gate.

### Stop or reset the Linux app

Stop the project from another terminal while retaining its home volume:

```bash
make linux-down
```

To erase this platform's Linux sessions, projects, configuration, and provider
logins, explicitly remove its volumes using the Compose environment above:

```bash
docker compose --project-name "quarry-${LINUX_PLATFORM_TAG}" down --volumes
```

### Copy a Linux coverage report to your Mac

Build the selected check image, run the existing coverage gate in a named
container, and keep that container until you copy its report. Use the Compose
environment above and check the gate's exit status before using the report:

```bash
make linux-build
docker compose --project-name "quarry-${LINUX_PLATFORM_TAG}" \
  run --name "quarry-coverage-${LINUX_PLATFORM_TAG}" --no-deps -T \
  check make coverage
docker cp "quarry-coverage-${LINUX_PLATFORM_TAG}:/workspace/coverage.xml" \
  coverage.xml
docker rm "quarry-coverage-${LINUX_PLATFORM_TAG}"
```

The copy writes the repository's ignored `coverage.xml` on your Mac. No report
mount changes the check container's filesystem.

### Use another localhost port

If another service owns 8765, leave that service running and create a temporary
Compose override outside the build inputs, such as `/tmp/quarry-port.yaml`:

```yaml
services:
  quarry:
    ports: !override
      - "127.0.0.1:18765:8766"
```

The `!override` tag replaces the default publish rather than adding a second
one. With the Compose environment above, build and start the same app through
that override:

```bash
docker compose --project-name "quarry-${LINUX_PLATFORM_TAG}" \
  -f compose.yaml -f /tmp/quarry-port.yaml up --build quarry relay
```

Open the token-bearing link with host port 18765 in place of 8765; the banner
still describes Quarry's internal port. `make linux-down` stops the same project
and retains its home volume. The shipped default remains port 8765.

## Using the core from a REPL (Stage 1)

The snippet assumes `config.toml` under the root (`~/.quarry` here) sets
`data.parquet_root`.

```python
from pathlib import Path
from quarry.kernel.client import KernelClient
from quarry.query import QuerySpec, Filter, to_source

k = KernelClient.spawn(Path("~/.quarry").expanduser())
k.execute("prices = pq('prices/**/*.parquet')")
k.execute("recent = prices.filter('year = 2024').pl()")
k.query(QuerySpec(dataset="recent", filters=[Filter(col="ticker", op="eq", value="B")])).rows
print(to_source(QuerySpec(dataset="recent", limit=10), "polars"))
k.shutdown()
k.close()
```

The kernel reads `config.toml` from the root it is spawned with. Its namespace
starts with:

- `pl` and `duckdb`
- `loaders.<name>` for every valid entry in the root's `loaders.toml`
- `sql(query)` for SQL Server: set `data.mssql_dsn` or `QUARRY_MSSQL_DSN` and
  install the `mssql` extra
- `pq(glob)` for a DuckDB relation over the Hive-partitioned parquet cache under
  `data.parquet_root`
- `sql_local(query)` for DuckDB SQL that reads the kernel's datasets by name

`pq`, `sql_local` and `duckdb.sql` share DuckDB's default connection, so
`duckdb.sql` sees `pq` relations too.

`execute` returns the step's status, the tails of its output, its lineage
(`reads`, `writes`, `defines`) and metadata for the datasets it wrote. The
client also has `describe`, `list_datasets`, `query`, `interrupt` and
`snapshot`. `shutdown()` stops the kernel, and `close()` then releases its
socket directory.

## Driving the server from curl (Stage 2)

```bash
export QUARRY_ANTHROPIC_API_KEY=...   # or QUARRY_OPENAI_API_KEY, with provider.name = "openai" and provider.model = "gpt-5" in config.toml
quarry serve --root ~/.quarry          # prints the port and token
T="Bearer <token>"; U=http://127.0.0.1:<port>
SID=$(curl -s -X POST $U/sessions -H "Authorization: $T" -H 'Content-Type: application/json' -d '{"title":"demo"}' | jq -r .id)
curl -s -X POST $U/sessions/$SID/steps -H "Authorization: $T" -H 'Content-Type: application/json' -d '{"prompt":"load the parquet cache prices for 2024 and show the first rows"}'
curl -s $U/sessions/$SID/status -H "Authorization: $T"          # poll until running_step is null
curl -s $U/sessions/$SID -H "Authorization: $T" | jq '.steps[-1] | {status, note, writes}'
curl -s -X POST $U/sessions/$SID/query -H "Authorization: $T" -H 'Content-Type: application/json' -d '{"dataset":"prices","limit":5}'
```

Server-side refusal fallbacks are enabled by default on Anthropic requests.

### Using Codex or Claude Code login

Install the provider CLI on the Linux server that runs Quarry, then sign in as
the same OS user. Quarry leaves login and credential storage to that CLI. It
never copies tokens into API requests or switches to API billing on failure.

For Codex, install `codex` and run `codex login` on the server. Over SSH, use
`codex login --device-auth` when a browser callback cannot reach the server. Set
the following in the Quarry root's `config.toml`:

```toml
[provider]
name = "codex"
model = "gpt-6.1-sol"
# cli_path = "/path/to/codex"  # optional; otherwise use PATH
```

Choose a model available to your account; the example does not establish access.
Use the tested Codex `0.162.1` CLI. The adapter requires this version and uses a
private per-operation model catalog to enable direct Quarry tool calls. It
leaves your normal Codex configuration unchanged.

For Claude Code, install `claude`, run `claude auth login` on the server, and
check `claude auth status`. Install Quarry's optional SDK dependency too:

```bash
uv sync --extra claude-code
```

Then select Claude Code in `config.toml`:

```toml
[provider]
name = "claude-code"
model = "opus"
# cli_path = "/path/to/claude"  # optional; otherwise use PATH
```

Choose a Claude model available to your account. Use the tested Claude Code
`2.1.299` CLI; the adapter requires this version, and the optional extra pins
its Python Agent SDK. Account access and subscription limits still apply.

Both modes require an explicit, nonblank `model` and reject `api_key_file`.
`cli_path` expands `~`; relative paths resolve under the Quarry root. Each
prompt or recipe tidy starts a fresh native conversation. Recipe validation
still runs locally, and a failed tidy falls back to the raw recipe. Codex
model-wait cancellation normally closes its process within 2 seconds; Claude
uses its SDK cleanup, which can take about 12 seconds. Native login checks can
take up to 20 seconds before a cancelled operation returns.

## Using the browser UI (Stage 3)

Build the UI once, then serve:

```bash
cd web && npm ci && npm run build && cd ..
uv run quarry serve
```

Open the printed link (it carries the token after `#`). From a laptop, forward
the port first with the `ssh -L` line the banner prints.

The server checks each generated view's syntax with `node` before saving it.
Without `node` on `PATH` it logs a warning at startup and skips that check; a
broken view then fails in the browser, where "Fix this view" sends it back to
the agent.

### Developing the UI

```bash
uv run quarry serve --port 8765          # terminal 1
cd web && QUARRY_PORT=8765 npm run dev    # terminal 2, open http://localhost:5173/#token=<token>
```

Vite proxies `/sessions`, `/projects`, `/components`, `/libraries`, `/libs` and
`/healthz` to the Python server. `npm run check`, `npm test`, and
`npm run build` must pass before a commit; the Playwright tests under
`tests/e2e` run only when `src/quarry/static/index.html` exists. They need a
browser, installed once with `uv run playwright install chromium`; without it
they error whenever a build exists.

## Projects (Stage 4)

A project keeps what a session produced. Create one with "New project" in the
rail, then:

- **Save** a dataset with "Save" beside its chip, or a view with "Save view"
  under its frame. A dataset is saved as a recipe, the code that made it, tidied
  by the model and checked in a fresh kernel. A view is saved with its TSX, its
  latest state and the datasets it reads, which are saved first. "Pinned copy"
  also keeps today's rows as parquet. A recipe that does not reproduce the data
  is still saved, marked unvalidated with the reason.
- **Recall** by clicking a project in the rail to list what it holds, then a
  dataset or view. The recall runs as a step in the open session, replacing a
  dataset of the same name after you confirm, and a restart replays it like any
  other step.
- **Canvas**: "Pin to canvas" saves a view and adds it as a card. "Open" on a
  project shows its Saved and Canvas tabs. Cards drag by their title bar, resize
  from the corner, and query through the open session; a card whose datasets the
  session lacks offers "Load". Cards that share a `shared:` state key stay in
  step.

Each project is a directory under the Quarry root, `~/.quarry/projects/<slug>/`,
with `project.json` (name and canvas layout), `datasets/<name>/` and
`views/<name>/`; the
[design spec](docs/superpowers/specs/2026-10-08-quarry-design.md#project) lists
every file. Everything is plain text except pinned parquet. Files are
owner-only, so `chmod` a project before sharing it in place.

### Export

"Export notebook" on a project page downloads `<slug>.ipynb`: each saved
dataset's recipe, then each saved view's queries as Python and its TSX.
"Download recipe" beside a saved dataset downloads its `recipe.py`. The command
line writes the same notebook and needs no running server:

```bash
quarry projects list --root ~/.quarry                       # slug, name, last update
quarry projects export momentum --root ~/.quarry            # writes ./momentum.ipynb
quarry projects export momentum --out ~/notebooks/mom.ipynb
```

The notebook's first code cell, and the recipe's first lines after its header,
rebuild a session's preloads (`pl`, `duckdb`, `pq`, `sql`, `sql_local`,
`loaders`) for the Quarry root the export names, so run an export where `quarry`
is importable, such as a Jupyter kernel in Quarry's environment. On another
machine it needs that root's `config.toml` and `loaders.toml`, or an edit to the
path.

An exported view's queries render without the dataset's schema, which only a
live session has, and the cell says so; "To code" under the view in a session
renders them exactly.

## Libraries

Highcharts Stock and SciChart.js are licensed, so Quarry never bundles them.
Install the package yourself, then name its folder and your key in
`config.toml`:

```toml
[libraries]
highcharts_license = "your_highcharts_license_key"
highcharts_path = "/path/to/node_modules/highcharts"
scichart_license = "your_scichart_license_key"
scichart_path = "/path/to/node_modules/scichart"
```

A library is enabled only when its key and path are both set and the path holds
its entry file, `highstock.js` or `index.min.mjs`; a key without a usable path
logs one warning at startup. The server then serves that folder under
`/libs/<id>/` to any origin, so each `*_path` must be the library's package
folder itself, never a broad folder such as `~` or `~/Downloads`. A relative
path resolves under the root. `GET /libraries` reports each library's status,
and the agent's library guide lists only the enabled ones. Restart the server
after installing or moving a package.
