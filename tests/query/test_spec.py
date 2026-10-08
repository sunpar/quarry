import pytest
from pydantic import ValidationError

from quarry.query import Agg, Filter, Pivot, QuerySpec


def test_minimal_spec() -> None:
    spec = QuerySpec(dataset="returns")
    assert spec.filters == []
    assert spec.offset == 0
    assert spec.format == "json"


def test_agg_default_name() -> None:
    assert Agg(col="ret", fn="mean").name == "ret_mean"
    assert Agg(col="ret", fn="mean", alias="avg").name == "avg"


def test_group_by_and_pivot_rejected() -> None:
    with pytest.raises(ValidationError, match="group_by"):
        QuerySpec(
            dataset="r",
            group_by=["a"],
            aggs=[Agg(col="x", fn="sum")],
            pivot=Pivot(index=["a"], columns="b", values="x", agg="sum"),
        )


def test_aggs_require_group_by() -> None:
    with pytest.raises(ValidationError, match="group_by"):
        QuerySpec(dataset="r", aggs=[Agg(col="x", fn="sum")])


def test_group_by_requires_aggs() -> None:
    with pytest.raises(ValidationError, match="aggs"):
        QuerySpec(dataset="r", group_by=["a"])


def test_between_requires_pair() -> None:
    with pytest.raises(ValidationError, match="between"):
        Filter(col="x", op="between", value=[1])
    Filter(col="x", op="between", value=[1, 2])


def test_in_requires_list() -> None:
    with pytest.raises(ValidationError, match="list"):
        Filter(col="x", op="in", value=1)


def test_null_ops_take_no_value() -> None:
    with pytest.raises(ValidationError, match="value"):
        Filter(col="x", op="is_null", value=1)
    Filter(col="x", op="not_null")


def test_limit_and_offset_bounds() -> None:
    with pytest.raises(ValidationError):
        QuerySpec(dataset="r", limit=0)
    with pytest.raises(ValidationError):
        QuerySpec(dataset="r", offset=-1)


def test_round_trips_json() -> None:
    spec = QuerySpec(
        dataset="r",
        filters=[Filter(col="sector", op="eq", value="tech")],
        group_by=["sector"],
        aggs=[Agg(col="ret", fn="mean")],
        sort=[{"col": "ret_mean", "desc": True}],
        limit=10,
    )
    assert QuerySpec.model_validate_json(spec.model_dump_json()) == spec
