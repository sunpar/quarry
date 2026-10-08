"""Every fixture spec must produce the same result on both execution targets."""

import polars as pl
import pytest
from polars.testing import assert_frame_equal

from quarry.query import QuerySpec
from quarry.query.polars_target import to_polars
from quarry.query.sql_target import to_sql
from tests.query.fixtures import SPECS, trades, utc_connection


def normalize(df: pl.DataFrame) -> pl.DataFrame:
    df = df.select(sorted(df.columns))
    numeric = [c for c, t in df.schema.items() if t.is_numeric()]
    df = df.with_columns([pl.col(c).cast(pl.Float64) for c in numeric])
    return df.sort(df.columns)


@pytest.mark.parametrize("spec", SPECS, ids=[s.model_dump_json() for s in SPECS])
def test_targets_agree(spec: QuerySpec) -> None:
    frame = trades()
    via_polars = to_polars(spec, frame).collect()
    conn = utc_connection()
    conn.register("trades", frame)
    via_sql = conn.sql(to_sql(spec, "trades")).pl()
    assert_frame_equal(normalize(via_polars), normalize(via_sql), check_dtypes=False, rel_tol=1e-9)
