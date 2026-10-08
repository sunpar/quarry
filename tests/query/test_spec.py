import math

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


@pytest.mark.parametrize(
    ("group_by", "aggs", "duplicate"),
    [
        (["a"], [Agg(col="x", fn="sum", alias="s"), Agg(col="y", fn="mean", alias="s")], "s"),
        (["a"], [Agg(col="x", fn="sum", alias="a")], "a"),
        (["a"], [Agg(col="x", fn="sum"), Agg(col="x", fn="sum")], "x_sum"),
        (["a"], [Agg(col="x", fn="mean"), Agg(col="y", fn="sum", alias="x_mean")], "x_mean"),
        (["a", "a"], [Agg(col="x", fn="sum")], "a"),
    ],
    ids=["two_aliases", "alias_is_group_key", "same_default", "alias_is_default", "group_keys"],
)
def test_duplicate_output_names_rejected(
    group_by: list[str], aggs: list[Agg], duplicate: str
) -> None:
    # polars raises a duplicate-column error at run time, and SQL gets an ambiguous schema.
    with pytest.raises(ValidationError, match=f"duplicate output column {duplicate!r}"):
        QuerySpec(dataset="r", group_by=group_by, aggs=aggs)


def test_duplicate_select_names_rejected() -> None:
    # polars raises a duplicate-column error at run time, while SQL returns the column twice.
    with pytest.raises(ValidationError, match="duplicate select column 'a'"):
        QuerySpec(dataset="r", select=["a", "b", "a"])


@pytest.mark.parametrize(
    ("fields", "message"),
    [
        (
            {"group_by": ["ticker"], "aggs": [Agg(col="x", fn="sum", alias="TICKER")]},
            "duplicate output column 'TICKER': clashes with 'ticker'",
        ),
        ({"select": ["Price", "price"]}, "duplicate select column 'price': clashes with 'Price'"),
    ],
    ids=["output", "select"],
)
def test_names_differing_only_in_case_are_duplicates(
    fields: dict[str, list[str] | list[Agg]], message: str
) -> None:
    # DuckDB identifiers ignore case, so the SQL target cannot tell these apart.
    with pytest.raises(ValidationError, match=message):
        QuerySpec.model_validate({"dataset": "r", **fields})


def test_same_column_with_different_fns_is_allowed() -> None:
    spec = QuerySpec(
        dataset="r", group_by=["a"], aggs=[Agg(col="x", fn="sum"), Agg(col="x", fn="mean")]
    )
    assert [a.name for a in spec.aggs] == ["x_sum", "x_mean"]


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


@pytest.mark.parametrize(
    ("op", "value"), [("in", [1, None]), ("not_in", [None])], ids=["in", "not_in"]
)
def test_list_ops_reject_null_items(op: FilterOp, value: Json) -> None:
    # SQL `NOT IN (..., NULL)` is never true while polars ignores the null: is_null covers it.
    with pytest.raises(ValidationError, match="does not accept null items; use is_null"):
        Filter(col="x", op=op, value=value)


def test_list_ops_accept_non_null_items() -> None:
    assert Filter(col="x", op="in", value=[1, 2]).value == [1, 2]


NON_FINITE_FILTERS: list[tuple[FilterOp, Json]] = [
    (op, value)
    for bad in (math.inf, -math.inf, math.nan)
    for op, value in [
        ("eq", bad),
        ("ge", bad),
        ("in", [1.0, bad]),
        ("not_in", [bad]),
        ("between", [bad, 1.0]),
        ("between", [0.0, bad]),
    ]
]


@pytest.mark.parametrize(("op", "value"), NON_FINITE_FILTERS)
def test_non_finite_filter_values_rejected(op: FilterOp, value: Json) -> None:
    # JSON has no inf or nan: a spec sent to the kernel would carry null in their place.
    with pytest.raises(ValidationError, match="finite"):
        Filter(col="x", op=op, value=value)


@pytest.mark.parametrize("token", ["NaN", "Infinity", "-Infinity", "[1, NaN]"])
def test_non_finite_filter_values_rejected_from_json(token: str) -> None:
    # The kernel decodes requests with pydantic, whose JSON parser accepts these tokens.
    with pytest.raises(ValidationError, match="finite"):
        Filter.model_validate_json(f'{{"col": "x", "op": "in", "value": [{token}]}}')
