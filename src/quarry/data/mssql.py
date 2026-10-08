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
        batches = list(read(query, dsn, params))
        if not batches:
            return pl.DataFrame()
        table = pa.Table.from_batches(batches)
        frame = pl.from_arrow(table)
        if not isinstance(frame, pl.DataFrame):
            raise TypeError("expected a DataFrame from Arrow table")
        return frame

    return sql


def _odbc_reader(query: str, dsn: str, params: Sequence[object] | None) -> Iterable[pa.RecordBatch]:
    from arrow_odbc import read_arrow_batches_from_odbc

    # arrow-odbc binds every parameter as VARCHAR, so it accepts only str, or None for NULL.
    parameters = None if params is None else [None if p is None else str(p) for p in params]
    batches: Iterable[pa.RecordBatch] = read_arrow_batches_from_odbc(
        query=query, connection_string=dsn, parameters=parameters
    )
    return batches
