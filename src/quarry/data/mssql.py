"""SQL Server access returning polars frames via Arrow."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence

import polars as pl
import pyarrow as pa

BatchReader = Callable[[str, str, Sequence[object] | None], Iterable[pa.RecordBatch]]
SqlFn = Callable[..., pl.DataFrame]


def make_sql(dsn: str, reader: BatchReader | None = None) -> SqlFn:
    read = reader or _odbc_reader

    def sql(query: str, *, params: Sequence[object] | None = None) -> pl.DataFrame:
        """Run `query` on SQL Server; `params` fill its `?` placeholders, sent as text."""
        if not dsn:
            raise RuntimeError(
                "SQL Server DSN not configured: set data.mssql_dsn or QUARRY_MSSQL_DSN"
            )
        table = _table(read(query, dsn, params))
        if table is None:
            return pl.DataFrame()
        frame = pl.from_arrow(table)
        if not isinstance(frame, pl.DataFrame):
            raise TypeError("expected a DataFrame from Arrow table")
        return frame

    return sql


def _table(batches: Iterable[pa.RecordBatch]) -> pa.Table | None:
    """The batches as one table; None when there are none and nothing gives their schema."""
    if isinstance(batches, pa.RecordBatchReader):
        return batches.read_all()  # carries the schema even when the query returns no rows
    collected = list(batches)
    return pa.Table.from_batches(collected) if collected else None


def _odbc_reader(query: str, dsn: str, params: Sequence[object] | None) -> Iterable[pa.RecordBatch]:
    try:
        from arrow_odbc import read_arrow_batches_from_odbc
    except ModuleNotFoundError as exc:
        if exc.name != "arrow_odbc":  # arrow_odbc is installed but lacks a dependency
            raise
        raise ModuleNotFoundError(
            "sql() needs the mssql extra: uv pip install 'quarry[mssql]'", name="arrow_odbc"
        ) from exc

    # arrow-odbc binds every parameter as VARCHAR, so it accepts only str, or None for NULL.
    parameters = None if params is None else [None if p is None else str(p) for p in params]
    reader = read_arrow_batches_from_odbc(query=query, connection_string=dsn, parameters=parameters)
    # A pyarrow reader keeps the result's schema, which a bare iterator loses when no rows come.
    batches: Iterable[pa.RecordBatch] = reader.into_pyarrow_record_batch_reader()
    return batches
