# Code map

What each module in `src/quarry` is responsible for, which section of the design
spec it implements, and which tests cover it. Each stage adds a section for its
packages.

## quarry

The top-level package holds the version, the config loader, and failure helpers
shared by `quarry.kernel` and `quarry.data`; `kernel.__main__` loads the config
and `data.namespace` builds from it.

| Module        | Responsibility                                                                                                                                                                            | Spec                  | Tests             |
| ------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | --------------------- | ----------------- |
| `__init__.py` | `__version__` only.                                                                                                                                                                       | §17 Repository layout | `test_package.py` |
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

## Tests

| File                              | Provides                                                                                                                                                       |
| --------------------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `tests/query/fixtures.py`         | The shared `trades()` frame, the `SPECS` list, zoned, naive and integer-sum cases, and `utc_connection()`.                                                     |
| `tests/kernel/fixtures.py`        | `BUSY_LOOP` step code and the `HEAVY` DuckDB query, for the interrupt tests.                                                                                   |
| `tests/data/fake_firmlib.py`      | A stand-in firm loader, `load_daily`, imported as `tests.data.fake_firmlib:load_daily`.                                                                        |
| `tests/query/test_equivalence.py` | Every fixture spec returns equal results from `to_polars` and `to_sql`. `query/test_source_target.py` runs the same specs through executed `to_source` output. |
| `tests/test_end_to_end_core.py`   | A real kernel over a parquet cache: execute, query, `to_source` round trip, `sql_local`, snapshot.                                                             |
| `tests/test_package.py`           | `quarry.__version__` is a string.                                                                                                                              |

## Commands

The gate commands are in the [README](../../README.md#development).
`.verify.toml` lists the same gates plus `uv lock --check` and a prettier check
of the Markdown docs.
