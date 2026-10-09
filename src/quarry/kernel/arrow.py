"""Arrow IPC for the browser: a frame cast to the types Perspective's reader accepts."""

from __future__ import annotations

import json

import polars as pl
import pyarrow as pa


def for_viewer(frame: pl.DataFrame) -> pl.DataFrame:
    """`frame` with every dtype Perspective rejects cast to one it reads.

    Decimal and 128-bit integers become Float64 (lossy past 2**53; Arrow here is a display
    transport). Categorical, Enum, Duration, Time and Binary become String. Nested columns
    become one JSON string per row. Everything else passes through unchanged.
    """
    # pl.nth, not pl.col: a column named like a regex (`^a.*$`) or `*` would select others.
    exprs = [
        expr.alias(name)
        for index, (name, dtype) in enumerate(frame.schema.items())
        if (expr := _viewer_expr(pl.nth(index), dtype)) is not None
    ]
    return frame.with_columns(exprs) if exprs else frame


def arrow_ipc(frame: pl.DataFrame) -> bytes:
    """`for_viewer(frame)` as Arrow IPC stream bytes with `string`, never `large_string`."""
    table = for_viewer(frame).to_arrow(compat_level=pl.CompatLevel.oldest())
    fields = [
        pa.field(f.name, pa.string(), nullable=f.nullable)
        if pa.types.is_large_string(f.type)
        else f
        for f in table.schema
    ]
    narrowed = table.cast(pa.schema(fields))
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, narrowed.schema) as writer:
        writer.write_table(narrowed)
    return bytes(sink.getvalue().to_pybytes())


def _viewer_expr(col: pl.Expr, dtype: pl.DataType) -> pl.Expr | None:
    if isinstance(dtype, pl.Decimal | pl.Int128 | pl.UInt128):
        return col.cast(pl.Float64)
    if isinstance(dtype, pl.Categorical | pl.Enum | pl.Time):
        return col.cast(pl.String)
    if isinstance(dtype, pl.Duration):
        # polars 2.0 cannot cast Duration to String; its own format reads "1d 2h 3m".
        return col.dt.to_string("polars")
    if isinstance(dtype, pl.Binary):
        return col.bin.encode("base64")
    if isinstance(dtype, pl.List | pl.Array | pl.Struct | pl.Map | pl.Object):
        return col.map_batches(_json_strings, return_dtype=pl.String)
    return None


def _json_strings(series: pl.Series) -> pl.Series:
    # `default=str` covers dates and decimals inside the nested value.
    values = [None if v is None else json.dumps(v, default=str) for v in series.to_list()]
    return pl.Series(series.name, values, dtype=pl.String)
