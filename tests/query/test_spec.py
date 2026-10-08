import pytest
from pydantic import BaseModel, ValidationError

from quarry.query import Agg, Filter, FilterOp, Json, Pivot, QuerySpec, Sort


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


@pytest.mark.parametrize(
    ("model", "data"),
    [
        (QuerySpec, {"dataset": "r", "filtr": []}),
        (Filter, {"col": "x", "op": "eq", "value": 1, "vale": 2}),
        (Agg, {"col": "x", "fn": "sum", "alais": "s"}),
        (Pivot, {"index": ["a"], "columns": "b", "values": "x", "agg": "sum", "aggs": "sum"}),
        (Sort, {"col": "x", "descending": True}),
    ],
)
def test_unknown_keys_rejected(model: type[BaseModel], data: dict[str, Json]) -> None:
    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        model.model_validate(data)


@pytest.mark.parametrize("op", ["eq", "ne", "lt", "le", "gt", "ge", "contains", "starts_with"])
@pytest.mark.parametrize("value", [None, [1, 2], {"a": 1}])
def test_scalar_ops_require_scalar_value(op: FilterOp, value: Json) -> None:
    with pytest.raises(ValidationError, match="scalar"):
        Filter(col="x", op=op, value=value)


@pytest.mark.parametrize("value", [1, 2.5, "tech", True])
def test_comparison_ops_accept_scalars(value: Json) -> None:
    assert Filter(col="x", op="eq", value=value).value == value


@pytest.mark.parametrize("op", ["contains", "starts_with"])
def test_text_ops_require_string(op: FilterOp) -> None:
    with pytest.raises(ValidationError, match="string"):
        Filter(col="x", op=op, value=1)
    assert Filter(col="x", op=op, value="te").value == "te"


@pytest.mark.parametrize("op", ["in", "not_in"])
def test_list_ops_reject_empty_list(op: FilterOp) -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        Filter(col="x", op=op, value=[])


def test_empty_select_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        QuerySpec(dataset="r", select=[])


def test_empty_group_by_rejected() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        QuerySpec(dataset="r", group_by=[], aggs=[Agg(col="x", fn="sum")])


def test_pivot_requires_index() -> None:
    with pytest.raises(ValidationError, match="at least 1 item"):
        Pivot(index=[], columns="b", values="x", agg="sum")


def test_pivot_accepts_std() -> None:
    assert Pivot(index=["a"], columns="b", values="x", agg="std").agg == "std"
