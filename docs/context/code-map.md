# Code map

What each module in `src/quarry` is responsible for, which section of the design
spec it implements, and which tests cover it. Each stage adds a section for its
packages.

## quarry

The top-level package holds the version, the config loader, failure helpers
shared by `quarry.kernel` and `quarry.data`, and the `quarry` command;
`kernel.__main__` loads the config and `data.namespace` builds from it.

| Module        | Responsibility                                                                                                                                                                            | Spec                  | Tests             |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | ----------------- |
| `__init__.py` | `__version__` only.                                                                                                                                                                       | §17 Repository layout | `test_package.py` |
| `cli.py`      | `quarry serve`: picks a free port and a token, prints the SSH tunnel banner, and runs the app on `127.0.0.1` under uvicorn.                                                               | §12 Security          | `test_cli.py`     |
| `config.py`   | `QuarryConfig` and its sub-models, `load_config` (reads `config.toml`, applies `QUARRY_MSSQL_DSN`), `api_key` (env var or owner-only key file), `ConfigError`. Unknown keys are rejected. | §11 Config            | `test_config.py`  |
| `errors.py`   | `exception_message` (a `str(exc)` that survives a failing `__str__`) and `NOT_FAILURES` (exits and interrupts that failure guards must let through).                                      | §13 Error handling    | none              |

## quarry.query

A pure compiler from one `QuerySpec` to three targets (polars, DuckDB SQL,
Python source) with no import from `quarry.kernel` or `quarry.data`; the kernel
executor runs `to_polars` and `to_sql`, and `to_source` renders code a
researcher runs in the kernel.

| Module                   | Responsibility                                                                                                                                                        | Spec                   | Tests                         |
| ------------------------ | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ----------------------------- |
| `query/__init__.py`      | Re-exports the public API listed in `__all__`.                                                                                                                        | §7 Query spec compiler | none                          |
| `query/spec.py`          | Pydantic `QuerySpec` and its parts, with shape validation (for example `group_by` with `pivot` is rejected), plus `QueryError`.                                       | §5 Query spec          | `query/test_spec.py`          |
| `query/columns.py`       | `check_columns` and `check_output_columns` raise `QueryError` for a column the dataset lacks.                                                                         | §7 Query spec compiler | `query/test_polars_target.py` |
| `query/polars_target.py` | `to_polars(spec, frame)` returns a `LazyFrame`; `filter_expr`, `agg_expr` and `coerce_literal` build the expressions.                                                 | §7 Query spec compiler | `query/test_polars_target.py` |
| `query/sql_target.py`    | `to_sql(spec, relation)` renders one DuckDB statement; `split_for_relation` splits a pivot spec into its SQL and polars parts; `first` and `last` raise `QueryError`. | §7 Query spec compiler | `query/test_sql_target.py`    |
| `query/source_target.py` | `to_source(spec, backing, result_name=, schema=)` renders readable Python that assigns the result; the DuckDB form drops its temporary view in a `finally`.           | §7 Query spec compiler | `query/test_source_target.py` |

## quarry.kernel

The subprocess that runs step code and answers queries, and the client that
spawns and drives it; `__main__` builds its namespace with `quarry.data` and
`executor` compiles queries with `quarry.query`.

| Module               | Responsibility                                                                                                                                                                                                        | Spec                           | Tests                     |
| -------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------ | ------------------------- |
| `kernel/__main__.py` | `python -m quarry.kernel` entry: `main`, `serve` (a reader thread answers `interrupt` and `shutdown` while the main thread runs requests), `apply_memory_cap` (`RLIMIT_AS`).                                          | §6 Kernel, §6 Resource limits  | `kernel/test_main.py`     |
| `kernel/protocol.py` | Newline-delimited JSON-RPC: `Request`, `Response`, `RpcError`, `InterruptResult`, `encode`, `decode_request`, `decode_response`, `read_lines`.                                                                        | §6 Kernel                      | `kernel/test_protocol.py` |
| `kernel/service.py`  | `KernelService.handle` dispatches `execute`, `describe`, `list_datasets`, `query`, `snapshot` and `shutdown` to the `Executor`; any failure becomes an error response.                                                | §6 Methods                     | `kernel/test_protocol.py` |
| `kernel/client.py`   | `KernelClient.spawn` starts the kernel over a Unix socket; one method per RPC method, plus `is_alive` and `close`; raises `KernelDead` and `RpcFailure`.                                                              | §6 Kernel                      | `kernel/test_client.py`   |
| `kernel/datasets.py` | `DatasetMeta` and `Column`, `is_dataset`, `backing_of`, `describe` (schema, row count, JSON preview), `to_json_rows`, `importable_relation`.                                                                          | §5 Dataset                     | `kernel/test_datasets.py` |
| `kernel/executor.py` | `Executor`: `execute` (runs code in the namespace, returns `ExecResult` with reads and writes), `describe`, `list_datasets`, `query` (returns `QueryResult`, capped at `row_cap`), `snapshot` (parquet), `on_sigint`. | §6 Methods, §6 Lineage capture | `kernel/test_executor.py` |
| `kernel/lineage.py`  | `analyze` (an `ast` pass returning `CodeNames`), `dataset_reads`, `dataset_writes`.                                                                                                                                   | §6 Lineage capture             | `kernel/test_lineage.py`  |

## quarry.data

The firm loaders, SQL Server and parquet access that `build_namespace` binds
into the kernel namespace; it depends on `quarry.config` and `quarry.errors`
only.

| Module              | Responsibility                                                                                                                                                        | Spec               | Tests                    |
| ------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------ | ------------------------ |
| `data/namespace.py` | `build_namespace(config, temp_dir)` returns the starting namespace; `configure_connection` sets the DuckDB connection up.                                             | §7 Data layer      | `data/test_namespace.py` |
| `data/loaders.py`   | `load_loaders` reads `loaders.toml` and records failures as `LoaderFailure` rather than raising; `LoaderRegistry`, `LoaderSpec`, `LoaderFailure`, `describe_loaders`. | §7 Loader registry | `data/test_loaders.py`   |
| `data/mssql.py`     | `make_sql(dsn, reader=)` returns `sql(query, params=)`, which reads SQL Server through arrow-odbc into a polars frame.                                                | §7 SQL Server      | `data/test_mssql.py`     |
| `data/parquet.py`   | `ParquetCatalog` with `pq` (hive-partitioned `read_parquet`) and `sql_local`; `scan_layout` lists partition keys.                                                     | §7 Parquet catalog | `data/test_parquet.py`   |

## quarry.agent

The provider-neutral loop behind prompt steps. Its tools drive a `KernelClient`
and a `ComponentLibrary`, and `context` reads `quarry.server.models.Step` to
summarize earlier steps.

| Module                        | Responsibility                                                                                                                                                                                                                    | Spec                  | Tests                                                 |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | ----------------------------------------------------- |
| `agent/types.py`              | `Message`, `ToolCall`, `ToolResult`, `ToolDef`, `AssistantTurn` with its stop reason, the `Provider` protocol and `ProviderError`.                                                                                                | §8 Provider interface | `agent/test_types.py`                                 |
| `agent/anthropic_provider.py` | `AnthropicProvider` calls `client.beta.messages.create` and maps stop reasons; `to_api_messages`, `to_api_tools`, `from_api_response`.                                                                                            | §8 Provider interface | `agent/test_anthropic_provider.py`                    |
| `agent/openai_provider.py`    | `OpenAIProvider` over chat completions; `to_openai_messages`, `to_openai_tools`, `from_openai_response`.                                                                                                                          | §8 Provider interface | `agent/test_openai_provider.py`                       |
| `agent/fake.py`               | `FakeProvider` returns scripted turns, for tests.                                                                                                                                                                                 | §14 Testing           | used by `agent/test_loop.py` and `server/test_app.py` |
| `agent/tools.py`              | `TOOL_DEFS`, the five strict tool schemas; `ToolExecutor.run` sends each call to the kernel, the library or the transpiler and records `exec_results` and the `PendingView`.                                                      | §8 Tools              | `agent/test_tools.py`                                 |
| `agent/context.py`            | `build_system` (contract, library guide, loaders, parquet layout, helpers), `build_summary` (earlier steps and datasets within a token budget), `enabled_libraries` intersected with `runtime_libraries` from the built manifest. | §8 Context            | `agent/test_context.py`                               |
| `agent/guide.md`              | The library guide, cut to the enabled libraries by `build_system`.                                                                                                                                                                | §8 Library guide      | `agent/test_context.py`                               |
| `agent/transpile.py`          | The `Transpiler` protocol, `CommandTranspiler` (runs `transpile-check.mjs` under node), `NoopTranspiler` and `default_transpiler`.                                                                                                | §8 Tools              | `agent/test_transpile.py`                             |
| `agent/loop.py`               | `run_agent_step` (provider calls, tool dispatch, the 12-call cap and the repair rule), `StepOutcome`, `step_lineage`.                                                                                                             | §8 Loop               | `agent/test_loop.py`                                  |

## quarry.components

The component library the agent searches and mounts from. It reads `DatasetMeta`
from `quarry.kernel` to match schemas.

| Module                  | Responsibility                                                                                                                                                                                                                    | Spec                   | Tests                        |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ---------------------------- |
| `components/library.py` | `ComponentLibrary` reads `*/manifest.json` with `component.tsx` from the built-in, researcher and team roots, skipping broken manifests; `search` ranks by tag overlap among components whose schema needs a dataset `satisfies`. | §5 Component           | `components/test_library.py` |
| `components/builtin/`   | `data-table` (AG Grid, sort pushed into the spec, first-rows notice) and `time-series` (Lightweight Charts, column pickers) with their manifests. Tested from `web/src/builtins/`.                                                | §9 Built-in components | none                         |

## quarry.server

The FastAPI app and the session machinery behind it, composing `quarry.agent`,
`quarry.components` and `quarry.kernel`.

| Module              | Responsibility                                                                                                                                                                                                                                                                              | Spec                          | Tests                    |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------- | ------------------------ |
| `server/models.py`  | `Session`, `SessionMeta`, `Step`, `View`, `Snapshot`, `KernelStatus` (with `replay_needed`), `ProviderInfo`, `new_id`, `now_iso`.                                                                                                                                                           | §5 Session, §5 Step, §5 View  | `server/test_store.py`   |
| `server/store.py`   | `SessionStore` under `<root>/sessions`: `session.json` and `steps/NNNN.json` per session, written atomically; `update_step` rewrites a finished step in place.                                                                                                                              | §11 Persistence layout        | `server/test_store.py`   |
| `server/kernels.py` | `KernelManager`: one `KernelClient` per session, started on first use and after a death, flagged `replay_needed` when spawned for a session with steps; `restart` replays steps and returns a `ReplayReport`.                                                                               | §6 Kernel                     | `server/test_kernels.py` |
| `server/service.py` | `SessionService`: prompt and manual steps on a background thread, one at a time per session, repair prompts (`StepRequest.repair`), `record_snapshot`, restart and the system prompt gated by the runtime manifest; `provider_from_config`, `SessionBusy`, `StepNotFound`, `SessionStatus`. | §4 Architecture, §8 Loop      | `server/test_app.py`     |
| `server/app.py`     | `create_app`: the routes (including `POST /sessions/{id}/steps/{step_id}/snapshots`), bearer-token auth, HTTP error mapping, and the static UI (with `Access-Control-Allow-Origin` for the sandboxed frame) or a plain-text root.                                                           | §4 Architecture, §12 Security | `server/test_app.py`     |

## web

The browser UI, one Vite project with two entries, built by `npm run build` into
`src/quarry/static/` (`index.html`, `runtime.html`, `assets/`,
`runtime-manifest.json`, `transpile-check.mjs`), which the wheel ships as an
artifact. The host app holds the token and talks to the server; each view runs
in a sandboxed iframe that reaches the host only through `postMessage`.

| Module                              | Responsibility                                                                                                                                                                                                    | Spec                 | Tests                                                      |
| ----------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------------- | ---------------------------------------------------------- |
| `web/src/shared/api-types.ts`       | TypeScript mirrors of the server's pydantic models, as serialised (`schema`, not `schema_`).                                                                                                                      | §5 Data model        | `host/api/client.test.ts`                                  |
| `web/src/shared/bridge-types.ts`    | `HostToRuntime` (`mount`, `restore`, `queryResult`, `schemaResult`) and `RuntimeToHost` (`ready`, `query`, `schema`, `stateChanged`, `error`) with their type guards.                                             | §9 View runtime      | `runtime/bridge.test.ts`, `host/bridge/HostBridge.test.ts` |
| `web/src/host/api/`                 | `readToken`, `readSession`, `sessionHash` (the fragment), `ApiClient` with one method per route and `ApiError`, query `keys`, `ApiProvider`, React Query hooks that poll while a step runs.                       | §4 Architecture      | `auth.test.ts`, `client.test.ts`, `hooks.test.tsx`         |
| `web/src/host/bridge/HostBridge.ts` | The host side of the bridge: trusts `event.source === iframe.contentWindow` only, queues `mount` until `ready`, answers `query` and `schema`, forwards `stateChanged` and `error`.                                | §9 View runtime, §12 | `HostBridge.test.ts`                                       |
| `web/src/host/components/`          | Presentational pieces: `SessionRail`, `StepCard` (ledger index and status rule), `DatasetChips`, `CodeDrawer`, `PromptBox`, `ViewFrame` (the sandboxed iframe and error overlay), `KernelBanner`, `TokenMissing`. | §9 Frontend          | `PromptBox`, `StepCard`, `KernelBanner` tests              |
| `web/src/host/containers/`          | `SessionPage` (rail, column, prompt, restart), `StepList`, `ViewFrameContainer` (one bridge per view, snapshots posted, "Fix this view" repair).                                                                  | §9 Frontend          | `ViewFrameContainer.test.tsx`                              |
| `web/src/runtime/loader.ts`         | `loadComponent`: Sucrase transpile, allowlisted `require`, default-export check.                                                                                                                                  | §9 View runtime, §12 | `loader.test.ts`                                           |
| `web/src/runtime/modules.ts`        | `MODULES`, the import allowlist with lazy chunks per chart library; `libraries.ts` names what the manifest advertises.                                                                                            | §9 View runtime      | `loader.test.ts`                                           |
| `web/src/runtime/bridge.ts`         | `RuntimeBridge`: correlation ids for `query` and `schema`, `stateChanged` with the specs issued since the last change, `error`.                                                                                   | §9 View runtime      | `bridge.test.ts`                                           |
| `web/src/runtime/state.ts`          | `ViewStateStore`: debounced `onChange`, `replace` for restore, stable snapshots.                                                                                                                                  | §9 View state        | `state.test.ts`                                            |
| `web/src/runtime/cache.ts`          | `RequestCache`: idempotent per-view query and schema requests, safe to call during render.                                                                                                                        | §9 View runtime      | `hooks.test.tsx`                                           |
| `web/src/runtime/hooks.ts`          | `useQuery`, `useViewState`, `useDatasetSchema`, what views import from `@quarry/hooks`.                                                                                                                           | §9 Hooks             | `hooks.test.tsx`                                           |
| `web/src/runtime/mount.tsx`         | `createRuntime`: posts `ready`, mounts a view inside `RuntimeProvider` and `ErrorBoundary`, handles `restore`, reports load, render and uncaught errors.                                                          | §9 View runtime      | `mount.test.tsx`                                           |
| `web/src/runtime/main.tsx`          | The iframe entry: `window.parent.postMessage(..., "*")`, accepts messages from `window.parent` only.                                                                                                              | §12 Security         | `tests/e2e/test_ui.py`                                     |
| `web/src/styles/tokens.css`         | Design tokens (IBM Plex, limestone, serpentine, status colours); `web/src/components/ui/` holds the shadcn components.                                                                                            | §9 Frontend          | none                                                       |
| `web/tools/transpile-check.ts`      | The node checker bundled to `transpile-check.mjs` for `CommandTranspiler`.                                                                                                                                        | §8 Tools             | `tests/agent/test_transpile.py`                            |

## Tests

| File                                 | Provides                                                                                                                                                       |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/query/fixtures.py`            | The shared `trades()` frame, the `SPECS` list, zoned, naive and integer-sum cases, and `utc_connection()`.                                                     |
| `tests/kernel/fixtures.py`           | `BUSY_LOOP` step code and the `HEAVY` DuckDB query, for the interrupt tests.                                                                                   |
| `tests/data/fake_firmlib.py`         | A stand-in firm loader, `load_daily`, imported as `tests.data.fake_firmlib:load_daily`.                                                                        |
| `tests/query/test_equivalence.py`    | Every fixture spec returns equal results from `to_polars` and `to_sql`. `query/test_source_target.py` runs the same specs through executed `to_source` output. |
| `tests/test_end_to_end_core.py`      | A real kernel over a parquet cache: execute, query, `to_source` round trip, `sql_local`, snapshot.                                                             |
| `tests/test_package.py`              | `quarry.__version__` is a string.                                                                                                                              |
| `tests/agent/test_live_providers.py` | One real call per provider, skipped unless `QUARRY_ANTHROPIC_API_KEY` or `QUARRY_OPENAI_API_KEY` is set.                                                       |
| `tests/e2e/conftest.py`              | The `serve` fixture: uvicorn in a daemon thread on a free port, the built UI, one scripted `FakeProvider` per server. Skipped without a web build.             |
| `tests/e2e/test_ui.py`               | Playwright: a table view round trip, and a refused import that shows "Fix this view" and completes a repair step.                                              |

## Commands

The gate commands are in the [README](../../README.md#development),
[driving the server from curl](../../README.md#driving-the-server-from-curl-stage-2)
shows `quarry serve` and its routes, and
[using the browser UI](../../README.md#using-the-browser-ui-stage-3) covers the
web build and dev loop. `.verify.toml` lists the same gates plus
`uv lock --check` and a prettier check of the Markdown docs.
