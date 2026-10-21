import io
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import polars as pl
import pyarrow as pa

from quarry.kernel.arrow import arrow_ipc, for_viewer


def mixed() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "s": ["a", None],
            "d": [date(2024, 1, 2), None],
            "ts": [datetime(2024, 1, 2, 3), None],
            "z": pl.Series([datetime(2024, 1, 2, 3, tzinfo=ZoneInfo("America/New_York")), None]),
            "dec": pl.Series([Decimal("1.50"), None], dtype=pl.Decimal(38, 2)),
            "cat": pl.Series(["x", None], dtype=pl.Categorical),
            "dur": [timedelta(days=1), None],
            "t": [time(9, 30), None],
            "b": [b"\x00\x01", None],
            "l": [[1, 2], None],
            "st": [{"a": 1}, None],
            "big": pl.Series([1, None], dtype=pl.Int128),
            "u8": pl.Series([255, None], dtype=pl.UInt8),
            "u16": pl.Series([65535, None], dtype=pl.UInt16),
            "u32": pl.Series([4_000_000_000, None], dtype=pl.UInt32),
            "u64": pl.Series([2**63, None], dtype=pl.UInt64),
            "f": [1.5, float("nan")],
            "f16": pl.Series([1.5, None], dtype=pl.Float16),
            "eu": pl.Series([2**64 - 1, None], dtype=pl.UInt64).ext.to(
                pl.Extension("x.u", pl.UInt64)
            ),
            "ed": pl.Series([timedelta(days=1), None]).ext.to(
                pl.Extension("x.d", pl.Duration("us"))
            ),
            "es": pl.Series([{"a": 1}, None]).ext.to(
                pl.Extension("x.s", pl.Struct({"a": pl.Int64}))
            ),
            "ei": pl.Series([1, None]).ext.to(pl.Extension("x.i", pl.Int64)),
            "null": pl.Series([None, None], dtype=pl.Null),
        }
    )


def test_for_viewer_casts_every_unsupported_dtype() -> None:
    out = for_viewer(mixed())
    assert out.schema == pl.Schema(
        {
            "s": pl.String(),
            "d": pl.Date(),
            "ts": pl.Datetime("us"),
            "z": pl.Datetime("us", "America/New_York"),
            "dec": pl.Float64(),
            "cat": pl.String(),
            "dur": pl.String(),
            "t": pl.String(),
            "b": pl.String(),
            "l": pl.String(),
            "st": pl.String(),
            "big": pl.Float64(),
            "u8": pl.Int64(),
            "u16": pl.Int64(),
            "u32": pl.Int64(),
            "u64": pl.Float64(),
            "f": pl.Float64(),
            "f16": pl.Float64(),
            "eu": pl.Float64(),
            "ed": pl.String(),
            "es": pl.String(),
            "ei": pl.Int64(),
            "null": pl.Null(),
        }
    )
    row = out.row(0, named=True)
    assert row["dec"] == 1.5 and row["cat"] == "x" and row["b"] == "AAE="
    assert json.loads(row["l"]) == [1, 2] and json.loads(row["st"]) == {"a": 1}
    assert row["t"] == "09:30:00"
    # Perspective reads every unsigned width as signed: 255 came back as -1, 2**63 as -2**63.
    assert (row["u8"], row["u16"], row["u32"], row["u64"]) == (255, 65535, 4_000_000_000, 2.0**63)
    assert "1d" in row["dur"]
    # An extension column is its storage: Perspective read one over UInt64 as signed and
    # refused one over Duration or Struct.
    assert row["eu"] == 2.0**64 and "1d" in row["ed"] and json.loads(row["es"]) == {"a": 1}
    assert out.row(1, named=True)["l"] is None


def test_arrow_ipc_is_a_stream_with_narrow_strings() -> None:
    data = arrow_ipc(mixed())
    reader = pa.ipc.open_stream(io.BytesIO(data))  # open_file would raise on a stream
    table = reader.read_all()
    assert table.schema.field("s").type == pa.string()
    assert table.schema.field("cat").type == pa.string()
    assert not any(pa.types.is_large_string(f.type) for f in table.schema)
    # Perspective refuses halffloat, and the extension name would survive on the field.
    assert table.schema.field("f16").type == pa.float64()
    assert not any(f.metadata and b"ARROW:extension:name" in f.metadata for f in table.schema)
    assert table.num_rows == 2
    back = pl.read_ipc_stream(io.BytesIO(data))
    assert back["s"].to_list() == ["a", None]


def test_arrow_ipc_keeps_non_finite_floats() -> None:
    back = pl.read_ipc_stream(io.BytesIO(arrow_ipc(pl.DataFrame({"f": [float("inf")]}))))
    assert back["f"][0] == float("inf")


def test_for_viewer_casts_columns_named_like_a_regex_alone() -> None:
    # As pl.col patterns, `^a.*$` would also select `ab`, and `*` every column.
    frame = pl.DataFrame(
        {
            "^a.*$": pl.Series([255], dtype=pl.UInt8),
            "ab": [b"x"],
            "*": pl.Series([4_000_000_000], dtype=pl.UInt32),
        }
    )
    out = for_viewer(frame)
    assert out.schema == pl.Schema({"^a.*$": pl.Int64(), "ab": pl.String(), "*": pl.Int64()})
    assert out.row(0) == (255, "eA==", 4_000_000_000)
