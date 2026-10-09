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
    relation_frame,
    to_json_rows,
    undescribed,
    unique_names,
)
from quarry.query.sql_target import quote_ident


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


def test_describe_leaves_origin_step_to_the_server() -> None:
    meta = describe("f", frame(), count_rows=False)
    assert meta.origin_step is None
    stamped = meta.model_copy(update={"origin_step": "abc123"})
    wire = json.loads(json.dumps(stamped.model_dump(by_alias=True, mode="json")))
    assert DatasetMeta.model_validate(wire).origin_step == "abc123"


def test_describe_round_trips_through_json_mode() -> None:
    meta = describe("f", frame(), count_rows=True)
    wire = json.loads(json.dumps(meta.model_dump(by_alias=True, mode="json")))
    assert DatasetMeta.model_validate(wire) == meta


def test_dataset_names_includes_underscore_names_and_skips_non_datasets() -> None:
    ns = {"a": frame(), "_b": frame(), "c": 3, "pl": pl}
    assert dataset_names(ns) == {"a", "_b"}


class Opaque:
    """A proxy whose `__class__` raises, so `isinstance` cannot be asked about it."""

    @property
    def __class__(self) -> type:
        raise RuntimeError("no class")


class OpaqueLazyFrame(Opaque, pl.LazyFrame):
    pass


def test_dataset_detection_uses_the_type_not_its_class_attribute() -> None:
    assert not is_dataset(Opaque())
    assert dataset_names({"p": Opaque(), "a": frame()}) == {"a"}
    lazy = OpaqueLazyFrame({"a": [1]})
    assert is_dataset(lazy)
    assert backing_of(lazy) == "polars_lazy"


def test_dataset_names_ignores_non_string_keys() -> None:
    ns: dict[object, object] = {1: frame(), "a": frame()}
    assert dataset_names(ns) == {"a"}


def test_undescribed_meta_carries_error_and_round_trips() -> None:
    meta = undescribed("lf", frame().lazy(), error="ColumnNotFoundError: nope")
    assert (meta.backing, meta.schema_, meta.rows, meta.preview) == ("polars_lazy", [], None, [])
    wire = json.loads(json.dumps(meta.model_dump(by_alias=True, mode="json")))
    assert wire["schema"] == []
    assert wire["error"] == "ColumnNotFoundError: nope"
    assert DatasetMeta.model_validate(wire) == meta
    assert describe("f", frame(), count_rows=False).error is None


def test_to_json_rows_handles_datetime_and_null() -> None:
    df = pl.DataFrame({"t": [None], "x": [None]}, schema={"t": pl.Datetime, "x": pl.Int64})
    assert to_json_rows(df) == [{"t": None, "x": None}]


def test_to_json_rows_decimal_is_an_exact_string_at_its_scale() -> None:
    df = pl.DataFrame({"x": [Decimal("1.50"), Decimal("3")]})
    assert to_json_rows(df) == [{"x": "1.50"}, {"x": "3.00"}]
    summed = duckdb.connect().sql("SELECT sum(i) AS s FROM range(3) t(i)").pl()
    assert summed.schema["s"] == pl.Decimal(38, 0)
    assert to_json_rows(summed) == [{"s": "3"}]


def test_to_json_rows_decimal_keeps_every_digit_at_any_depth() -> None:
    beyond_float = "9007199254740993"  # 2**53 + 1, which a Float64 rounds to ...992
    long_fraction = "0.1234567890123456789012345678901234567"
    df = pl.DataFrame(
        {
            "big": [Decimal(beyond_float)],
            "frac": [Decimal(long_fraction)],
            "nested": [[Decimal(beyond_float), None]],
        }
    )
    assert df.schema["nested"] == pl.List(pl.Decimal(38, 0))
    assert to_json_rows(df) == [
        {"big": beyond_float, "frac": long_fraction, "nested": [beyond_float, None]}
    ]


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
            "st": {"d": "1.5", "t": "2024-01-01T09:30:00", "n": 1},
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
    assert row["total"] == "2"


def test_describe_relation_with_interval_column() -> None:
    rel = duckdb.connect().sql(
        "SELECT TIMESTAMP '2024-01-02' - TIMESTAMP '2024-01-01' AS gap, 1 AS n"
    )
    meta = describe("r", rel, count_rows=True)
    assert [(c.name, c.dtype) for c in meta.schema_] == [("gap", "String"), ("n", "Int32")]
    assert meta.preview == [{"gap": "1 day", "n": 1}]
    assert meta.rows == 1


def test_describe_relation_with_nested_interval_and_union() -> None:
    rel = duckdb.connect().sql(
        "SELECT [INTERVAL 1 DAY] AS l, union_value(k := 1) AS u, {'INTERVAL': 1} AS st"
    )
    meta = describe("r", rel, count_rows=False)
    assert [c.dtype for c in meta.schema_] == ["String", "String", "Struct({'INTERVAL': Int32})"]
    assert meta.preview == [{"l": "[1 day]", "u": "1", "st": {"INTERVAL": 1}}]


def test_relation_frame_keeps_odd_and_duplicate_names() -> None:
    rel = duckdb.connect().sql('SELECT INTERVAL 1 HOUR AS "my gap", 1 AS "a""b", 2 AS "a""b"')
    result = relation_frame(rel)
    assert result.columns == ["my gap", 'a"b', 'a"b_1']
    assert result.row(0) == ("01:00:00", 1, 2)


@pytest.mark.parametrize(
    "names",
    [
        ["a", "a"],
        ["a", "a", "a", "a_1"],
        ["a_1", "a", "a"],
        ["A", "a"],
        ["a", "a", "A", "a_1"],
        ["k", "v", "k", "v"],
        ["a", "b"],
    ],
    ids=str,
)
def test_unique_names_are_the_names_pl_gives(names: list[str]) -> None:
    select = ", ".join(f"{n} AS {quote_ident(name)}" for n, name in enumerate(names))
    assert unique_names(names) == duckdb.connect().sql(f"SELECT {select}").pl().columns


def test_relation_frame_limit() -> None:
    rel = duckdb.connect().sql("SELECT * FROM range(30)")
    assert relation_frame(rel).height == 30
    assert relation_frame(rel, limit=5).height == 5


def test_to_json_rows_keeps_chrono_extremes_and_nulls_beyond() -> None:
    days = pl.Series("d", [95_026_236, 95_026_237, -96_465_292, -96_465_293], dtype=pl.Int32)
    assert to_json_rows(days.cast(pl.Date).to_frame()) == [
        {"d": "+262142-12-31"},
        {"d": None},
        {"d": "-262143-01-01"},
        {"d": None},
    ]
    micros = pl.Series(
        "t", [8_210_266_876_799_999_999, 8_210_266_876_800_000_000, -8_334_601_228_800_000_000]
    )
    assert to_json_rows(micros.cast(pl.Datetime("us")).to_frame()) == [
        {"t": "+262142-12-31T23:59:59.999999"},
        {"t": None},
        {"t": "-262143-01-01T00:00:00"},
    ]
    assert to_json_rows(micros.cast(pl.Datetime("us", "UTC")).to_frame())[:2] == [
        {"t": "+262142-12-31T23:59:59.999999+00:00"},
        {"t": None},
    ]


def duckdb_column(name: str, literal: str) -> pl.Series:
    """`literal` and then a null, as DuckDB hands them to polars."""
    sql = f"SELECT x FROM (VALUES (1, {literal}), (2, NULL)) t(i, x) ORDER BY i"
    return duckdb.connect().sql(sql).pl().get_column("x").alias(name)


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
    (pl.Series("arr_dec", [[Decimal("1")], None], dtype=pl.Array(pl.Decimal(10, 0), 1)), ["1"]),
    (pl.Series("list_list_bin", [[[b"x"]], None]), [["eA=="]]),
    (pl.Series("^b.*$", [b"x", None]), "eA=="),
    (
        pl.Series(
            "map_dt_key", [{datetime(2024, 1, 1): 1}, None], dtype=pl.Map(pl.Datetime, pl.Int64)
        ),
        [{"key": "2024-01-01T00:00:00", "value": 1}],
    ),
    (duckdb_column("inf_date", "'infinity'::DATE"), None),
    (duckdb_column("neg_inf_date", "'-infinity'::DATE"), None),
    (
        duckdb_column("inf_date_list", "['infinity'::DATE, '2024-01-01'::DATE]"),
        [None, "2024-01-01"],
    ),
    (duckdb_column("inf_date_struct", "{'d': 'infinity'::DATE}"), {"d": None}),
    (duckdb_column("inf_ts", "'infinity'::TIMESTAMP"), None),
    (duckdb_column("inf_ts_ms", "'infinity'::TIMESTAMP_MS"), None),
    (duckdb_column("neg_inf_tstz", "'-infinity'::TIMESTAMPTZ"), None),
    (duckdb_column("inf_ts_list", "['infinity'::TIMESTAMP]"), [None]),
    (pl.Series("ms_2_62", [2**62, None]).cast(pl.Datetime("ms")), None),
    (pl.Series("ms_2_62_utc", [2**62, None]).cast(pl.Datetime("ms", "UTC")), None),
    (pl.Series("dur_ms_min", [-(2**63), None]).cast(pl.Duration("ms")), None),
]


@pytest.mark.parametrize(
    ("series", "first"), [pytest.param(s, first, id=s.name) for s, first in NATIVE_CASES]
)
def test_to_json_rows_emits_json_native_values_for_every_dtype(
    series: pl.Series, first: object
) -> None:
    assert to_json_rows(series.to_frame()) == [{series.name: first}, {series.name: None}]
