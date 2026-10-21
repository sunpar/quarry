"""Arrow IPC for the browser: a frame cast to the types Perspective's reader accepts."""

from __future__ import annotations

import json
from collections.abc import Callable

import polars as pl
import pyarrow as pa
from polars.datatypes import DataTypeClass


def for_viewer(frame: pl.DataFrame) -> pl.DataFrame:
    """`frame` with every dtype Perspective rejects cast to one it reads.

    Perspective reads unsigned integers as signed, so 4,000,000,000 in a UInt32 reads back as
    -294,967,296: UInt8, UInt16 and UInt32 become Int64. Float16, UInt64, Decimal and 128-bit
    integers become Float64 (lossy past 2**53; Arrow here is a display transport). Categorical,
    Enum, Duration, Time and Binary become String. Nested columns become one JSON string per
    row. An extension column becomes its storage, converted the same way. Everything else passes
    through unchanged.
    """
    return convert_columns(frame, _viewer_expr)


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


def convert_columns(
    frame: pl.DataFrame, convert: Callable[[pl.Expr, pl.DataType], pl.Expr | None]
) -> pl.DataFrame:
    """`frame` with each column replaced by `convert(column, dtype)` where that is not None."""
    # pl.nth, not pl.col: a column named like a regex (`^a.*$`) or `*` would select others.
    exprs = [
        expr.alias(name)
        for index, (name, dtype) in enumerate(frame.schema.items())
        if (expr := convert(pl.nth(index), dtype)) is not None
    ]
    return frame.with_columns(exprs) if exprs else frame


def _viewer_expr(col: pl.Expr, dtype: pl.DataType | DataTypeClass) -> pl.Expr | None:
    if isinstance(dtype, pl.BaseExtension):
        # The storage, even when unchanged: the field would keep the extension name.
        storage = col.ext.storage()
        converted = _viewer_expr(storage, dtype.ext_storage())
        return storage if converted is None else converted
    if isinstance(dtype, pl.UInt8 | pl.UInt16 | pl.UInt32):
        return col.cast(pl.Int64)
    if isinstance(dtype, pl.Float16 | pl.UInt64 | pl.Decimal | pl.Int128 | pl.UInt128):
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
