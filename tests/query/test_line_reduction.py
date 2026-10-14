"""Whole-domain lines agree across backings and exported Python."""

from collections.abc import Sequence
from datetime import datetime, timedelta

import duckdb
import polars as pl
import pytest
from polars.testing import assert_frame_equal
from pydantic import ValidationError

from quarry.kernel.executor import Executor
from quarry.query import Backing, Filter, QuerySpec, to_polars, to_source, to_sql
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
        assert_frame_equal(expected, actual)
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
