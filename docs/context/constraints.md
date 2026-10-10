# Constraints

Fixed facts and agreed rules that bound the work on Quarry. A choice the project
made and could revisit belongs in [decisions](decisions.md) instead.

## Authority

- The [design spec](../superpowers/specs/2026-10-08-quarry-design.md) is
  binding. Where a stage plan in
  [`docs/superpowers/plans/`](../superpowers/plans/) disagrees with it, the spec
  wins.
- Once a stage starts, its plan is history. Where a plan differs from
  [decisions](decisions.md) or the code, those win.
- A deliberate departure from the spec amends the spec in the same pull request
  and gets an entry in [decisions](decisions.md).
- Build order follows spec §15: core, server and agent, first UI, projects,
  breadth. Each stage is usable on its own before the next starts.

## Product

- One researcher, one server, one session at a time, on a shared development
  machine reached by SSH. Steps in a session are linear (spec §1).
- The server binds `127.0.0.1` only, and every API request carries a per-run
  bearer token (spec §12).
- The browser never holds a full dataset. Views ask the kernel for slices
  through a query spec, capped at `row_cap` rows (spec §4, §6).
- Every result must be reproducible as plain Python a researcher can run in a
  notebook (spec §1, §2).
- The kernel runs code, including model-written code, as the researcher's own
  user, with notebook-level trust (spec §12).
- Highcharts and SciChart stay opt-in behind a license key, AG Grid Enterprise
  is never used, and Lightweight Charts keeps its attribution logo (spec §3).

## Environment

- Python 3.11, managed with uv. Library versions and their floors are under
  [packaging and CI](decisions.md#packaging-and-ci).
- Data comes from three places: a firm SQL Server over ODBC, a Hive-partitioned
  parquet cache under `data.parquet_root`, and firm loader functions registered
  in `loaders.toml` (spec §7).
- Several researchers share each machine, so files a kernel writes can be read
  by others unless made private, and kernels compete for memory and cores.
- Target machines run Linux, and development happens on macOS. macOS rejects
  `RLIMIT_DATA`, so the kernel memory cap applies only on Linux. macOS has no
  `os.waitid`, so the client cannot test whether the kernel is alive without
  reaping it.

## Quality gates

- CI runs `pytest`, `ruff check`, `ruff format --check` and strict `mypy` on
  `src` and `tests`, and all four must pass (spec §14). The commands are in the
  [README](../../README.md#development).
- For every spec in the equivalence fixtures, `to_polars`, `to_sql` and the
  executed `to_source` output must return equal results (spec §14).
- Kernel tests run the kernel as a real subprocess over its socket (spec §14).

## How work lands

- Each stage lands as one pull request against `main` from its own branch. CI
  must be green and the Codex review clear before merging.
- Commit messages start with a bare type such as `feat:`, `fix:` or `docs:`,
  with no scope and no attribution trailer. The agent's commit hook enforces
  this.
