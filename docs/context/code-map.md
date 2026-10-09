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
| `cli.py`      | `quarry serve`: creates a missing root owner-only, picks a free port and a token, prints the SSH tunnel banner, and runs the app on `127.0.0.1` under uvicorn.                            | §12 Security          | `test_cli.py`     |
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

| Module               | Responsibility                                                                                                                                                                                                                                                                 | Spec                           | Tests                     |
| -------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------ | ------------------------- |
| `kernel/__main__.py` | `python -m quarry.kernel` entry: `main`, `serve` (a reader thread answers `interrupt` and `shutdown` while the main thread runs requests), `apply_memory_cap` (`RLIMIT_DATA`).                                                                                                 | §6 Kernel, §6 Resource limits  | `kernel/test_main.py`     |
| `kernel/protocol.py` | Newline-delimited JSON-RPC: `Request`, `Response`, `RpcError`, `InterruptResult`, `encode`, `decode_request`, `decode_response`, `read_lines`.                                                                                                                                 | §6 Kernel                      | `kernel/test_protocol.py` |
| `kernel/service.py`  | `KernelService.handle` dispatches `execute`, `describe`, `list_datasets`, `query`, `snapshot` and `shutdown` to the `Executor`; any failure becomes an error response.                                                                                                         | §6 Methods                     | `kernel/test_protocol.py` |
| `kernel/client.py`   | `KernelClient.spawn` starts the kernel over a Unix socket; one method per RPC method, plus `is_alive` and `close`, which never raises; every failure is `KernelDead` or `RpcFailure`. `spawn(threads=)` sets `POLARS_MAX_THREADS`.                                             | §6 Kernel                      | `kernel/test_client.py`   |
| `kernel/datasets.py` | `DatasetMeta` and `Column`, `is_dataset`, `backing_of`, `describe` (schema, row count, JSON preview), `to_json_rows`, `importable_relation`.                                                                                                                                   | §5 Dataset                     | `kernel/test_datasets.py` |
| `kernel/executor.py` | `Executor`: `execute` (runs code in the namespace, returns `ExecResult` with reads and writes), `describe`, `list_datasets` (reuses the metadata cached since the last step), `query` (returns `QueryResult`, capped at `row_cap`), `snapshot` (parquet), `on_sigint`, `stop`. | §6 Methods, §6 Lineage capture | `kernel/test_executor.py` |
| `kernel/lineage.py`  | `analyze` (an `ast` pass returning `CodeNames`), `dataset_reads`, `dataset_writes`.                                                                                                                                                                                            | §6 Lineage capture             | `kernel/test_lineage.py`  |

## quarry.data

The firm loaders, SQL Server and parquet access that `build_namespace` binds
into the kernel namespace; it depends on `quarry.config` and `quarry.errors`
only.

| Module              | Responsibility                                                                                                                                                                             | Spec               | Tests                    |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------ | ------------------------ |
| `data/namespace.py` | `build_namespace(config, temp_dir)` returns the starting namespace; `configure_connection` sets the DuckDB connection up.                                                                  | §7 Data layer      | `data/test_namespace.py` |
| `data/loaders.py`   | `load_loaders` reads `loaders.toml` and records failures as `LoaderFailure` rather than raising; `LoaderRegistry`, `LoaderSpec`, `LoaderFailure`, `describe_loaders`, `describe_failures`. | §7 Loader registry | `data/test_loaders.py`   |
| `data/mssql.py`     | `make_sql(dsn, reader=)` returns `sql(query, params=)`, which reads SQL Server through arrow-odbc into a polars frame.                                                                     | §7 SQL Server      | `data/test_mssql.py`     |
| `data/parquet.py`   | `ParquetCatalog` with `pq` (hive-partitioned `read_parquet`) and `sql_local`; `scan_layout` lists each dataset's partition keys and never raises.                                          | §7 Parquet catalog | `data/test_parquet.py`   |

## quarry.agent

The provider-neutral loop behind prompt steps. Its tools drive a `KernelClient`
and a `ComponentLibrary`, and `context` reads `quarry.server.models.Step` to
summarize earlier steps.

| Module                        | Responsibility                                                                                                                                                                                      | Spec                  | Tests                                                 |
| ----------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | ----------------------------------------------------- |
| `agent/types.py`              | `Message`, `ToolCall`, `ToolResult`, `ToolDef`, `AssistantTurn` with its stop reason, the `Provider` protocol and `ProviderError`.                                                                  | §8 Provider interface | `agent/test_types.py`                                 |
| `agent/anthropic_provider.py` | `AnthropicProvider` calls `client.beta.messages.create` and maps stop reasons; `to_api_messages`, `to_api_tools`, `from_api_response`.                                                              | §8 Provider interface | `agent/test_anthropic_provider.py`                    |
| `agent/openai_provider.py`    | `OpenAIProvider` over chat completions; `to_openai_messages`, `to_openai_tools`, `from_openai_response`.                                                                                            | §8 Provider interface | `agent/test_openai_provider.py`                       |
| `agent/fake.py`               | `FakeProvider` returns scripted turns, for tests.                                                                                                                                                   | §14 Testing           | used by `agent/test_loop.py` and `server/test_app.py` |
| `agent/tools.py`              | `TOOL_DEFS`, the five strict tool schemas; `ToolExecutor.run` sends each call to the kernel, the library or the transpiler and records each run's code and result and the `PendingView`; `CodeRun`. | §8 Tools              | `agent/test_tools.py`                                 |
| `agent/context.py`            | `build_system` (contract, library guide, loaders, parquet layout, helpers), `build_summary` (earlier steps and datasets within a token budget), `enabled_libraries`.                                | §8 Context            | `agent/test_context.py`                               |
| `agent/guide.md`              | The library guide, cut to the enabled libraries by `build_system`.                                                                                                                                  | §8 Library guide      | `agent/test_context.py`                               |
| `agent/transpile.py`          | The `Transpiler` protocol, `CommandTranspiler` (runs `transpile-check.mjs` under node, with a 30 s timeout), `NoopTranspiler` and `default_transpiler`.                                             | §8 Tools              | `agent/test_transpile.py`                             |
| `agent/loop.py`               | `run_agent_step` (provider calls, tool dispatch, the 12-call cap, the repair rule and the cancel), `StepOutcome`, `step_lineage`.                                                                   | §8 Loop               | `agent/test_loop.py`                                  |

## quarry.components

The component library the agent searches and mounts from. It reads `DatasetMeta`
from `quarry.kernel` to match schemas.

| Module                  | Responsibility                                                                                                                                                                                                                    | Spec                   | Tests                        |
| ----------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------- | ---------------------------- |
| `components/library.py` | `ComponentLibrary` reads `*/manifest.json` with `component.tsx` from the built-in, researcher and team roots, skipping broken manifests; `search` ranks by tag overlap among components whose schema needs a dataset `satisfies`. | §5 Component           | `components/test_library.py` |
| `components/builtin/`   | The built-in components. Empty until Stage 3.                                                                                                                                                                                     | §9 Built-in components | none                         |

## quarry.server

The FastAPI app and the session machinery behind it, composing `quarry.agent`,
`quarry.components` and `quarry.kernel`.

| Module              | Responsibility                                                                                                                                                                                                                                         | Spec                          | Tests                    |
| ------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ----------------------------- | ------------------------ |
| `server/models.py`  | `Session`, `SessionMeta`, `Step`, `View`, `Snapshot`, `KernelStatus`, `ProviderInfo`, `new_id`, `now_iso`.                                                                                                                                             | §5 Session, §5 Step, §5 View  | `server/test_store.py`   |
| `server/store.py`   | `SessionStore` under `<root>/sessions`: `session.json` and `steps/NNNN.json` per session, owner-only, written atomically and fsynced.                                                                                                                  | §11 Persistence layout        | `server/test_store.py`   |
| `server/kernels.py` | `KernelManager`: one `KernelClient` per session, started on first use; a dead or killed one stays dead until `restart`, which replays each step's runs and returns a `ReplayReport`.                                                                   | §6 Kernel                     | `server/test_kernels.py` |
| `server/service.py` | `SessionService`: prompt and manual steps on a background thread, one at a time per session, with a cancel each; restart, which stops a running step; `origin_step` stamps; the system prompt; `provider_from_config`, `SessionBusy`, `SessionStatus`. | §4 Architecture, §8 Loop      | `server/test_app.py`     |
| `server/app.py`     | `create_app`: the routes, bearer-token auth, HTTP error mapping, and the static UI or a plain-text root.                                                                                                                                               | §4 Architecture, §12 Security | `server/test_app.py`     |

## Tests

| File                                 | Provides                                                                                                                                                       |
| ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/query/fixtures.py`            | The shared `trades()` frame, the `SPECS` list, zoned, naive and integer-sum cases, and `utc_connection()`.                                                     |
| `tests/fixtures.py`                  | `root_ignores_modes`, `chmodded` and `umask`, for tests that make paths unreadable or check the modes Quarry creates.                                          |
| `tests/kernel/fixtures.py`           | `BUSY_LOOP` step code and the `HEAVY` DuckDB query, for the interrupt tests.                                                                                   |
| `tests/data/fake_firmlib.py`         | A stand-in firm loader, `load_daily`, imported as `tests.data.fake_firmlib:load_daily`.                                                                        |
| `tests/query/test_equivalence.py`    | Every fixture spec returns equal results from `to_polars` and `to_sql`. `query/test_source_target.py` runs the same specs through executed `to_source` output. |
| `tests/test_end_to_end_core.py`      | A real kernel over a parquet cache: execute, query, `to_source` round trip, `sql_local`, snapshot.                                                             |
| `tests/test_package.py`              | `quarry.__version__` is a string.                                                                                                                              |
| `tests/agent/test_live_providers.py` | One real call per provider, skipped unless `QUARRY_ANTHROPIC_API_KEY` or `QUARRY_OPENAI_API_KEY` is set.                                                       |

## Commands

The gate commands are in the [README](../../README.md#development), and
[driving the server from curl](../../README.md#driving-the-server-from-curl-stage-2)
shows `quarry serve` and its routes. `.verify.toml` lists the same gates plus
`uv lock --check` and a prettier check of the Markdown docs.
