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
            "u": pl.Series([2**63, None], dtype=pl.UInt64),
            "f": [1.5, float("nan")],
        }
    )


def test_for_viewer_casts_every_unsupported_dtype() -> None:
    out = for_viewer(mixed())
    assert out.schema == pl.Schema(
        {
            "s": pl.String,
            "d": pl.Date,
            "ts": pl.Datetime("us"),
            "z": pl.Datetime("us", "America/New_York"),
            "dec": pl.Float64,
            "cat": pl.String,
            "dur": pl.String,
            "t": pl.String,
            "b": pl.String,
            "l": pl.String,
            "st": pl.String,
            "big": pl.Float64,
            "u": pl.UInt64,
            "f": pl.Float64,
        }
    )
    row = out.row(0, named=True)
    assert row["dec"] == 1.5 and row["cat"] == "x" and row["b"] == "AAE="
    assert json.loads(row["l"]) == [1, 2] and json.loads(row["st"]) == {"a": 1}
    assert row["t"] == "09:30:00"
    assert "1d" in row["dur"]
    assert out.row(1, named=True)["l"] is None


def test_arrow_ipc_is_a_stream_with_narrow_strings() -> None:
    data = arrow_ipc(mixed())
    reader = pa.ipc.open_stream(io.BytesIO(data))  # open_file would raise on a stream
    table = reader.read_all()
    assert table.schema.field("s").type == pa.string()
    assert table.schema.field("cat").type == pa.string()
    assert not any(pa.types.is_large_string(f.type) for f in table.schema)
    assert table.num_rows == 2
    back = pl.read_ipc_stream(io.BytesIO(data))
    assert back["s"].to_list() == ["a", None]


def test_arrow_ipc_keeps_non_finite_floats() -> None:
    back = pl.read_ipc_stream(io.BytesIO(arrow_ipc(pl.DataFrame({"f": [float("inf")]}))))
    assert back["f"][0] == float("inf")
