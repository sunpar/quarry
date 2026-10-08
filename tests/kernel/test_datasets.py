import json
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal

import duckdb
import polars as pl
import pytest

from quarry.kernel.datasets import (
    DatasetMeta,
    backing_of,
    dataset_names,
    describe,
    is_dataset,
    to_json_rows,
)


def frame() -> pl.DataFrame:
    return pl.DataFrame({"d": [date(2024, 1, 1)], "x": [1.5], "s": ["a"]})


def test_is_dataset_for_each_type() -> None:
    assert is_dataset(frame())
    assert is_dataset(frame().lazy())
    assert is_dataset(duckdb.connect().sql("SELECT 1 AS one"))
    assert not is_dataset([1, 2])
    assert not is_dataset(None)


def test_backing_of() -> None:
    assert backing_of(frame()) == "polars"
    assert backing_of(frame().lazy()) == "polars_lazy"
    assert backing_of(duckdb.connect().sql("SELECT 1 AS one")) == "duckdb"


def test_describe_eager_counts_rows_and_previews() -> None:
    meta = describe("f", frame(), count_rows=False)
    assert meta.name == "f"
    assert meta.rows == 1
    assert [c.name for c in meta.schema_] == ["d", "x", "s"]
    assert meta.schema_[0].dtype == "Date"
    assert meta.preview == [{"d": "2024-01-01", "x": 1.5, "s": "a"}]


def test_describe_lazy_defers_row_count() -> None:
    assert describe("f", frame().lazy(), count_rows=False).rows is None
    assert describe("f", frame().lazy(), count_rows=True).rows == 1


def test_describe_duckdb_relation() -> None:
    rel = duckdb.connect().sql("SELECT 1 AS one, 'x' AS s")
    meta = describe("r", rel, count_rows=True)
    assert meta.backing == "duckdb"
    assert meta.rows == 1
    assert [c.name for c in meta.schema_] == ["one", "s"]
    assert [c.dtype for c in meta.schema_] == ["Int32", "String"]
    assert meta.preview == [{"one": 1, "s": "x"}]


def test_describe_duckdb_relation_defers_row_count() -> None:
    rel = duckdb.connect().sql("SELECT * FROM range(30)")
    meta = describe("r", rel, count_rows=False)
    assert meta.rows is None
    assert len(meta.preview) == 20


def test_describe_serializes_schema_key() -> None:
    meta = describe("f", frame(), count_rows=False)
    assert "schema" in meta.model_dump(by_alias=True)
    assert DatasetMeta.model_validate(meta.model_dump(by_alias=True)) == meta


def test_describe_round_trips_through_json_mode() -> None:
    meta = describe("f", frame(), count_rows=True)
    wire = json.loads(json.dumps(meta.model_dump(by_alias=True, mode="json")))
    assert DatasetMeta.model_validate(wire) == meta


def test_dataset_names_skips_private_and_non_datasets() -> None:
    ns = {"a": frame(), "_b": frame(), "c": 3, "pl": pl}
    assert dataset_names(ns) == {"a"}


def test_to_json_rows_handles_datetime_and_null() -> None:
    df = pl.DataFrame({"t": [None], "x": [None]}, schema={"t": pl.Datetime, "x": pl.Int64})
    assert to_json_rows(df) == [{"t": None, "x": None}]


def test_to_json_rows_decimal_is_number() -> None:
    df = pl.DataFrame({"x": [Decimal("1.50"), Decimal("3")]})
    assert to_json_rows(df) == [{"x": 1.5}, {"x": 3}]
    summed = duckdb.connect().sql("SELECT sum(i) AS s FROM range(3) t(i)").pl()
    assert summed.schema["s"] == pl.Decimal(38, 0)
    assert to_json_rows(summed) == [{"s": 3}]


def test_to_json_rows_binary_is_base64() -> None:
    df = pl.DataFrame({"b": [b"\x00\x01ab", None]})
    assert to_json_rows(df) == [{"b": "AAFhYg=="}, {"b": None}]


def test_to_json_rows_naive_datetime_uses_t_separator() -> None:
    df = pl.DataFrame({"t": [datetime(2024, 1, 1, 9, 30), datetime(2024, 1, 1, 9, 30, 0, 123456)]})
    assert to_json_rows(df) == [{"t": "2024-01-01T09:30:00"}, {"t": "2024-01-01T09:30:00.123456"}]


def test_to_json_rows_keeps_native_temporal_shapes() -> None:
    df = pl.DataFrame(
        {
            "tz": [datetime(2024, 1, 1, 9, 30, tzinfo=UTC)],
            "dur": [timedelta(hours=1)],
            "tm": [time(9, 30)],
            "nan": [float("nan")],
        }
    )
    assert to_json_rows(df) == [
        {"tz": "2024-01-01T09:30:00+00:00", "dur": "PT3600S", "tm": "09:30:00", "nan": None}
    ]


class Thing:
    def __str__(self) -> str:
        return "thing"


def test_to_json_rows_object_is_str() -> None:
    df = pl.DataFrame({"o": [Thing(), None, 3]}, schema={"o": pl.Object})
    assert to_json_rows(df) == [{"o": "thing"}, {"o": None}, {"o": "3"}]


def test_to_json_rows_converts_inside_nested_types() -> None:
    naive = datetime(2024, 1, 1, 9, 30)
    df = pl.DataFrame(
        {
            "lb": [[b"ab", None]],
            "st": [{"d": Decimal("1.5"), "t": naive, "n": 1}],
            "ab": [[b"ab", b"cd"]],
            "ls": [[{"t": naive}]],
        },
        schema_overrides={"ab": pl.Array(pl.Binary, 2)},
    )
    assert to_json_rows(df) == [
        {
            "lb": ["YWI=", None],
            "st": {"d": 1.5, "t": "2024-01-01T09:30:00", "n": 1},
            "ab": ["YWI=", "Y2Q="],
            "ls": [{"t": "2024-01-01T09:30:00"}],
        }
    ]


def test_to_json_rows_map_is_object_or_entries() -> None:
    df = pl.DataFrame(
        {"sk": [{"a": 1}], "ik": [{1: "a"}], "bv": [{"a": b"ab"}]},
        schema={
            "sk": pl.Map(pl.String, pl.Int64),
            "ik": pl.Map(pl.Int32, pl.String),
            "bv": pl.Map(pl.String, pl.Binary),
        },
    )
    assert to_json_rows(df) == [
        {
            "sk": {"a": 1},
            "ik": [{"key": 1, "value": "a"}],
            "bv": [{"key": "a", "value": "YWI="}],
        }
    ]


def test_describe_duckdb_relation_with_exotic_types() -> None:
    rel = duckdb.connect().sql(
        "SELECT 'ab'::BLOB AS bl, MAP {1: 'a'} AS m, 12345678901234567890123::VARINT AS big,"
        " '2024-01-01 09:30'::TIMESTAMP AS ts, sum(2) AS total"
    )
    meta = describe("r", rel, count_rows=True)
    row = meta.preview[0]
    assert row["bl"] == "YWI="
    assert row["m"] == [{"key": 1, "value": "a"}]
    assert isinstance(row["big"], str)
    assert row["ts"] == "2024-01-01T09:30:00"
    assert row["total"] == 2


NATIVE_CASES: list[tuple[pl.Series, object]] = [
    (pl.Series("i8", [1, None], dtype=pl.Int8), 1),
    (pl.Series("u64", [2**64 - 1, None], dtype=pl.UInt64), 2**64 - 1),
    (pl.Series("i128", [2**100, None], dtype=pl.Int128), 2**100),
    (pl.Series("u128", [2**100, None], dtype=pl.UInt128), 2**100),
    (pl.Series("f16", [1.5, None], dtype=pl.Float16), 1.5),
    (pl.Series("f32", [float("inf"), None], dtype=pl.Float32), None),
    (pl.Series("bool", [True, None]), True),
    (pl.Series("cat", ["a", None], dtype=pl.Categorical), "a"),
    (pl.Series("enum", ["a", None], dtype=pl.Enum(["a"])), "a"),
    (pl.Series("null", [None, None], dtype=pl.Null), None),
    (pl.Series("date", [date(2024, 1, 1), None]), "2024-01-01"),
    (
        pl.Series("dt_ns", [datetime(2024, 1, 1), None], dtype=pl.Datetime("ns")),
        "2024-01-01T00:00:00",
    ),
    (pl.Series("arr_dec", [[Decimal("1")], None], dtype=pl.Array(pl.Decimal(10, 0), 1)), [1]),
    (pl.Series("list_list_bin", [[[b"x"]], None]), [["eA=="]]),
    (pl.Series("^b.*$", [b"x", None]), "eA=="),
    (
        pl.Series(
            "map_dt_key", [{datetime(2024, 1, 1): 1}, None], dtype=pl.Map(pl.Datetime, pl.Int64)
        ),
        [{"key": "2024-01-01T00:00:00", "value": 1}],
    ),
]


@pytest.mark.parametrize(
    ("series", "first"), [pytest.param(s, first, id=s.name) for s, first in NATIVE_CASES]
)
def test_to_json_rows_emits_json_native_values_for_every_dtype(
    series: pl.Series, first: object
) -> None:
    assert to_json_rows(series.to_frame()) == [{series.name: first}, {series.name: None}]
