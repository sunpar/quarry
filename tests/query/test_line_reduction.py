"""Whole-domain lines agree across backings and exported Python."""

import struct
from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

import duckdb
import polars as pl
import pytest
from polars.testing import assert_frame_equal
from pydantic import ValidationError

from quarry.kernel.executor import Executor
from quarry.query import Backing, Filter, QueryError, QuerySpec, to_polars, to_source, to_sql
from tests.query.fixtures import BACKINGS, bind, execute, utc_connection


def line_spec(budget: int = 50_000) -> QuerySpec:
    return QuerySpec.model_validate(
        {"dataset": "ticks", "line_reduce": {"time": "ts", "value": "px", "max_rows": budget}}
    )


def ticks(values: Sequence[float | None], times: list[int] | None = None) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "ts": pl.Series(
                [
                    datetime(2026, 1, 1) + timedelta(seconds=n)
                    for n in (times or range(len(values)))
                ],
                dtype=pl.Datetime("us"),
            ),
            "px": pl.Series(values, dtype=pl.Float64),
        }
    )


@pytest.mark.parametrize("backing", BACKINGS)
@pytest.mark.parametrize("cap", [100, 50_000])
def test_whole_domain_survives_server_cap_and_to_code(backing: Backing, cap: int) -> None:
    frame = ticks([float(n % 17) for n in range(60_001)])
    frame[-2, "px"] = -10_000
    frame[-1, "px"] = 20_000
    ex = Executor({"ticks": bind(frame, backing)}, conn=utc_connection(), row_cap=cap)
    requested = line_spec()
    result = ex.query(requested)
    assert result.truncated is False
    assert result.reduced is True
    assert result.source_row_count == frame.height
    assert 4 <= result.row_count <= cap
    assert result.rows is not None
    assert result.rows[0]["ts"] == "2026-01-01T00:00:00"
    assert result.rows[-1]["px"] == 20_000
    assert min(row["px"] for row in result.rows if isinstance(row["px"], int | float)) == -10_000
    ns: dict[str, object] = {"pl": pl, "ticks": bind(frame, backing)}
    exec(ex.to_code([requested]).code, ns)
    assert isinstance(ns["ticks_1"], pl.DataFrame)
    assert ns["ticks_1"].height == result.row_count
    assert_frame_equal(ns["ticks_1"], to_polars(line_spec(cap), frame).collect())


@pytest.mark.parametrize(
    ("frame", "budget"),
    [
        (ticks([5, -9, 12, 4, 6, -2, 10, 3], [0, 1, 1, 2, 20, 100, 101, 900]), 4),
        (ticks([5, -9, 12, 4, 6, -2, 10, 3], [0] * 8), 4),
        (ticks([1, 8, None, None, -4, 9, None, 3, 4]), 8),
        (ticks([None] * 9), 2),
        (ticks([3, 2]), 2),
        (ticks([3, 3, 3]), 3),
        (ticks([]), 1),
    ],
)
def test_reduction_targets_and_sources_agree_in_order(frame: pl.DataFrame, budget: int) -> None:
    spec = line_spec(budget)
    expected = to_polars(spec, frame).collect()
    with utc_connection() as conn:
        conn.register("ticks", frame)
        assert_frame_equal(expected, conn.sql(to_sql(spec, "ticks")).pl())
    for backing in BACKINGS:
        assert_frame_equal(
            expected,
            execute(to_source(spec, backing, schema=frame.schema), {"ticks": bind(frame, backing)}),
        )
    assert expected.height <= budget


@pytest.mark.parametrize(
    "dtype",
    [
        pl.Date,
        pl.Datetime("ms"),
        pl.Datetime("us"),
        pl.Datetime("ns"),
        pl.Datetime("us", "America/New_York"),
    ],
)
@pytest.mark.parametrize("value_dtype", [pl.Int8, pl.UInt64, pl.Float32, pl.Decimal(20, 2)])
def test_axis_types_and_order_agree(dtype: pl.DataType, value_dtype: pl.DataType) -> None:
    frame = ticks([4, 2, 9, 8, 3, 7, 5, 1]).with_columns(
        pl.col("ts").cast(dtype), pl.col("px").cast(value_dtype)
    )
    expected = to_polars(line_spec(4), frame).collect()
    for backing in BACKINGS:
        actual = execute(
            to_source(line_spec(4), backing, schema=frame.schema), {"ticks": bind(frame, backing)}
        )
        compared = expected
        if backing == "duckdb" and isinstance(dtype, pl.Datetime) and dtype.time_zone:
            # A DuckDB relation advertises the UTC schema it already acquired at binding.
            compared = compared.with_columns(pl.col("ts").dt.convert_time_zone("UTC"))
        assert_frame_equal(compared, actual)
    assert expected["px"].dtype == frame["px"].dtype


def test_missing_times_are_omitted_and_nonfinite_values_mark_gaps() -> None:
    frame = ticks([1, float("nan"), float("inf"), float("-inf"), 2, 3])
    frame[5, "ts"] = None
    result = to_polars(line_spec(5), frame).collect()
    assert result["px"].to_list() == [1, None, None, None, 2]
    ex = Executor({"ticks": frame}, conn=utc_connection(), row_cap=5)
    out = ex.query(line_spec(5))
    assert out.source_row_count == 5
    assert out.reduced is False


def test_arrow_metadata_does_not_become_an_axis_column() -> None:
    frame = ticks([1, 3, 2, 4, 8, 7, 5, 6]).rename({"ts": "_quarry_input_rows"})
    spec = QuerySpec.model_validate(
        {
            "dataset": "ticks",
            "line_reduce": {"time": "_quarry_input_rows", "value": "px", "max_rows": 4},
            "format": "arrow",
        }
    )
    out = Executor({"ticks": frame}, conn=utc_connection(), row_cap=4).query(spec)
    assert [column.name for column in out.schema_] == ["_quarry_input_rows", "px"]
    assert out.arrow_base64
    assert out.source_row_count == 8
    assert out.reduced is True


def test_temporal_filter_source_imports_agree() -> None:
    spec = line_spec(4).model_copy(
        update={"filters": [Filter(col="ts", op="ge", value="2026-01-01T00:00:02")]}
    )
    frame = ticks([2, 8, 4, 9, 1, 7, 3, 6])
    expected = to_polars(spec, frame).collect()
    for backing in BACKINGS:
        assert_frame_equal(
            expected,
            execute(to_source(spec, backing, schema=frame.schema), {"ticks": bind(frame, backing)}),
        )


@pytest.mark.parametrize("name", ["i", "I"])
def test_axis_alias_does_not_override_time_order(name: str) -> None:
    frame = ticks([3, 1, 4, 2]).rename({"px": name})
    spec = QuerySpec.model_validate(
        {"dataset": "ticks", "line_reduce": {"time": "ts", "value": name, "max_rows": 4}}
    )
    for backing in BACKINGS:
        assert_frame_equal(
            frame,
            execute(to_source(spec, backing, schema=frame.schema), {"ticks": bind(frame, backing)}),
        )


@pytest.mark.parametrize("dtype", [pl.Date, pl.Datetime("us")])
def test_wide_dates_do_not_narrow_to_nanoseconds(dtype: pl.DataType) -> None:
    frame = pl.DataFrame(
        {
            "ts": pl.Series(
                [datetime(year, 1, 1) for year in [1600, 1750, 2000, 2500, 3000, 4000]]
            ).cast(dtype),
            "px": [3, 1, 5, 4, 9, 2],
        }
    )
    expected = frame[[0, 1, 4, 5]]
    assert_frame_equal(to_polars(line_spec(4), frame).collect(), expected)
    for backing in BACKINGS:
        assert_frame_equal(
            expected,
            execute(
                to_source(line_spec(4), backing, schema=frame.schema),
                {"ticks": bind(frame, backing)},
            ),
        )


@pytest.mark.parametrize("dtype", [pl.Int128, pl.UInt128])
def test_full_precision_128_bit_values_survive_reduction(dtype: pl.DataType) -> None:
    high = 2**127 - 1 if dtype == pl.Int128 else 2**128 - 1
    frame = ticks([3, 1, 5, 4, 9, 2]).with_columns(
        pl.Series("px", [3, 1, 5, 4, high, 2], dtype=dtype)
    )
    expected = frame[[0, 1, 4, 5]]
    assert_frame_equal(to_polars(line_spec(4), frame).collect(), expected)
    for backing in ("polars", "polars_lazy"):
        assert_frame_equal(
            expected,
            execute(
                to_source(line_spec(4), backing, schema=frame.schema),
                {"ticks": bind(frame, backing)},
            ),
        )


@pytest.mark.parametrize("zone", [None, "UTC", "America/New_York"])
def test_submicrosecond_time_bins_and_dtypes_survive(zone: str | None) -> None:
    frame = pl.DataFrame(
        {
            "ts": pl.Series(range(12), dtype=pl.Int64).cast(pl.Datetime("ns", zone)),
            "px": [1, 3, 9, 4, 8, 6, 7, -9, 2, 5, 0, 3],
        }
    )
    expected = frame[[0, 2, 5, 6, 7, 11]]
    assert_frame_equal(to_polars(line_spec(8), frame).collect(), expected)
    for backing in ("polars", "polars_lazy"):
        assert_frame_equal(
            expected,
            execute(
                to_source(line_spec(8), backing, schema=frame.schema),
                {"ticks": bind(frame, backing)},
            ),
        )


@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
def test_source_can_assign_back_to_its_input(backing: Backing) -> None:
    frame = ticks([3, 1, 5, 4, 9, 2])
    namespace: dict[str, object] = {"pl": pl, "ticks": bind(frame, backing)}
    exec(to_source(line_spec(4), backing, result_name="ticks", schema=frame.schema), namespace)
    assert isinstance(namespace["ticks"], pl.DataFrame)
    assert_frame_equal(namespace["ticks"], frame[[0, 1, 4, 5]])


@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize("result_name", ["pl", "duckdb"])
def test_source_assigns_helper_names_after_reduction(backing: Backing, result_name: str) -> None:
    frame = ticks([3, 1, 5, 4, 9, 2])
    namespace: dict[str, object] = {"pl": pl, "ticks": bind(frame, backing)}
    exec(to_source(line_spec(4), backing, result_name=result_name, schema=frame.schema), namespace)
    result = namespace[result_name]
    assert isinstance(result, pl.DataFrame)
    assert_frame_equal(result, frame[[0, 1, 4, 5]])


def test_to_code_keeps_private_namespace_bindings() -> None:
    frame = ticks([3, 1, 5, 4, 9, 2])
    keep = pl.DataFrame({"keep": [1]})
    namespace: dict[str, object] = {
        "pl": pl,
        "ticks": frame,
        "_quarry_ticks_1_connection": keep,
        "_quarry_ticks_2_connection": 42,
    }
    ex = Executor(namespace, conn=utc_connection(), row_cap=4)
    exec(ex.to_code([line_spec(4)]).code, namespace)
    assert namespace["_quarry_ticks_1_connection"] is keep
    assert namespace["_quarry_ticks_2_connection"] == 42
    assert isinstance(namespace["ticks_1"], pl.DataFrame)
    assert_frame_equal(namespace["ticks_1"], frame[[0, 1, 4, 5]])


def test_extrema_and_duplicate_time_ties_are_deterministic() -> None:
    frame = ticks([3, 9, -4, -4, 7, 2, 1], [0, 0, 1, 1, 2, 9, 10])
    spec = line_spec(4)
    expected = ticks([3, 9, -4, 1], [0, 0, 1, 10])
    assert_frame_equal(to_polars(spec, frame.reverse()).collect(), expected)


def test_gap_markers_keep_each_null_run_and_domain_endpoints() -> None:
    frame = ticks([None, None, 1, 5, None, None, 3, 9, None])
    result = to_polars(line_spec(9), frame).collect()
    assert_frame_equal(result, frame)
    frame = ticks([None] * 3 + [1, 2, 3, 4, 5] + [None] * 3 + [6, 7, 8, 9, 10] + [None] * 3)
    result = to_polars(line_spec(10), frame).collect()
    assert (
        result.filter(pl.col("px").is_null())["ts"].to_list()
        == frame[[0, 2, 8, 10, 16, 18]]["ts"].to_list()
    )
    assert result[0, "ts"] == frame[0, "ts"]
    assert result[-1, "ts"] == frame[-1, "ts"]


@pytest.mark.parametrize("budget", [1, 2, 3, 5])
@pytest.mark.parametrize("backing", BACKINGS)
def test_insufficient_budget_explains_gap_cost(budget: int, backing: Backing) -> None:
    ex = Executor(
        {"ticks": bind(ticks([1, None, 2, None, 3, None, 4]), backing)},
        conn=utc_connection(),
        row_cap=100,
    )
    with pytest.raises(duckdb.InvalidInputException, match=r"row budget.*gaps"):
        ex.query(line_spec(budget))


def test_filters_apply_before_whole_domain_reduction() -> None:
    spec = line_spec(4).model_copy(update={"filters": [Filter(col="px", op="ge", value=5)]})
    assert to_polars(spec, ticks([0, 10, 2, 9, 4, 8, 6, 7])).collect()["px"].to_list() == [10, 6, 7]


@pytest.mark.parametrize(
    "extra",
    [
        {"limit": 1},
        {"offset": 1},
        {"sort": [{"col": "ts"}]},
        {"select": ["px"]},
        {"group_by": ["ts"], "aggs": [{"col": "px", "fn": "min"}]},
    ],
)
def test_line_reduction_rejects_partial_domain_and_reshaping(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError, match="line_reduce"):
        QuerySpec.model_validate({**line_spec().model_dump(), **extra})


@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize("budget", [1, 4])
def test_public_source_keeps_private_connection_bindings(backing: Backing, budget: int) -> None:
    frame = ticks([3, 1, 5, 4, 9, 2])
    keep = object()
    private = {
        n: object()
        for n in ["_scope", "_reduce", "_connection", "_frame", "_schema", "_points", "_value"]
    }
    namespace: dict[str, object] = {
        "pl": pl,
        "ticks": bind(frame, backing),
        "_quarry_out_connection": keep,
        **private,
    }
    source = to_source(line_spec(budget), backing, result_name="out", schema=frame.schema)
    if budget == 1:
        with pytest.raises(duckdb.InvalidInputException, match="row budget"):
            exec(source, namespace)
    else:
        exec(source, namespace)
        assert isinstance(namespace["out"], pl.DataFrame)
        assert_frame_equal(namespace["out"], frame[[0, 1, 4, 5]])
    assert namespace["_quarry_out_connection"] is keep
    assert all(namespace[n] is v for n, v in private.items())


@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize("invalid", ["time", "value"])
def test_source_rejects_the_same_invalid_axes_as_live_query(backing: Backing, invalid: str) -> None:
    frame = ticks([3, 1, 5, 4, 9, 2]).with_columns(
        pl.col("ts").cast(pl.Int64) if invalid == "time" else pl.col("px").cast(pl.String)
    )
    with pytest.raises(QueryError, match=f"line_reduce {invalid} must be"):
        to_polars(line_spec(4), frame)
    with pytest.raises(QueryError, match=f"line_reduce {invalid} must be"):
        to_source(line_spec(4), backing, schema=frame.schema)


@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize("dtype", [pl.Float32, pl.Decimal(20, 2), pl.Int128, pl.UInt128])
def test_source_without_schema_restores_runtime_axis_types(
    backing: Backing, dtype: pl.DataType
) -> None:
    frame = ticks([3, 1, 5, 4, 9, 2]).with_columns(
        pl.col("ts").cast(pl.Datetime("ns", "UTC")), pl.col("px").cast(dtype)
    )
    assert_frame_equal(
        execute(to_source(line_spec(4), backing), {"ticks": bind(frame, backing)}),
        to_polars(line_spec(4), frame).collect(),
    )


@pytest.mark.parametrize("backing", ["polars", "polars_lazy"])
@pytest.mark.parametrize("invalid", ["time", "value"])
def test_source_without_schema_refuses_invalid_axes(backing: Backing, invalid: str) -> None:
    frame = ticks([3, 1, 5, 4, 9, 2]).with_columns(
        pl.col("ts").cast(pl.Int64) if invalid == "time" else pl.col("px").cast(pl.String)
    )
    with pytest.raises(ValueError, match=f"line_reduce {invalid} must be"):
        execute(to_source(line_spec(4), backing), {"ticks": bind(frame, backing)})


def test_source_without_schema_keeps_date_literal_filters() -> None:
    frame = ticks([3, 1, 5, 4, 9, 2]).with_columns(pl.col("ts").cast(pl.Date))
    spec = line_spec(4).model_copy(
        update={"filters": [Filter(col="ts", op="ge", value="2026-01-01")]}
    )
    assert_frame_equal(
        execute(to_source(spec, "polars"), {"ticks": frame}), to_polars(spec, frame).collect()
    )


def test_source_filter_literal_coercion_still_requires_schema() -> None:
    frame = ticks([0, 1, 2, 3, 4, 5])
    spec = line_spec(4).model_copy(update={"filters": [Filter(col="px", op="in", value=[1])]})
    with pytest.raises(pl.exceptions.InvalidOperationError, match="is_in"):
        execute(to_source(spec, "polars"), {"ticks": frame})
    assert_frame_equal(
        execute(to_source(spec, "polars", schema=frame.schema), {"ticks": frame}),
        to_polars(spec, frame).collect(),
    )


@pytest.mark.parametrize("dtype", [pl.Float32, pl.Float64])
def test_generated_floating_values_match_live_reduction_bit_for_bit(dtype: pl.DataType) -> None:
    scalar, integer, bits = (
        ("f", "I", [1, 0x80000000, 0x3F800001, 0x3F800002, 0x7F7FFFFF])
        if dtype == pl.Float32
        else (
            "d",
            "Q",
            [1, 0x8000000000000000, 0x3FF0000000000001, 0x3FF0000000000002, 0x7FEFFFFFFFFFFFFF],
        )
    )
    values = [struct.unpack(scalar, struct.pack(integer, b))[0] for b in bits]
    frame = ticks(values).with_columns(pl.col("px").cast(dtype))
    expected = to_polars(line_spec(8), frame).collect()
    result = execute(to_source(line_spec(8), "polars"), {"ticks": frame})
    assert_frame_equal(result, expected, check_exact=True)
    assert [struct.pack(scalar, v) for v in result["px"]] == [
        struct.pack(scalar, v) for v in expected["px"]
    ]


def test_generated_fractional_decimals_match_live_reduction_exactly() -> None:
    frame = ticks([0, 1, 2, 3, 4, 5]).with_columns(
        pl.Series(
            "px",
            [Decimal(s) for s in ["0.01", "1.03", "-2.12", "99.99", "0.05", "6.23"]],
            dtype=pl.Decimal(20, 2),
        )
    )
    assert_frame_equal(
        execute(to_source(line_spec(4), "polars"), {"ticks": frame}),
        to_polars(line_spec(4), frame).collect(),
        check_exact=True,
    )


@pytest.mark.parametrize("result_name", ["ticks", "pl", "isinstance", "ValueError"])
def test_source_refusal_preserves_requested_output(result_name: str) -> None:
    frame = ticks([3, 1, 5, 4, 9, 2])
    namespace: dict[str, object] = {"pl": pl, "ticks": frame}
    if result_name not in namespace:
        namespace[result_name] = object()
    previous = namespace[result_name]
    with pytest.raises(duckdb.InvalidInputException, match="row budget"):
        exec(to_source(line_spec(1), "polars", result_name=result_name), namespace)
    assert namespace[result_name] is previous


@pytest.mark.parametrize("result_name", ["isinstance", "ValueError"])
def test_source_accepts_builtin_result_names(result_name: str) -> None:
    frame = ticks([3, 1, 5, 4, 9, 2])
    namespace: dict[str, object] = {"pl": pl, "ticks": frame}
    exec(to_source(line_spec(4), "polars", result_name=result_name), namespace)
    result = namespace[result_name]
    assert isinstance(result, pl.DataFrame)
    assert_frame_equal(result, to_polars(line_spec(4), frame).collect())
