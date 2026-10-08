"""The declarative query language under every view and every to-code action."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, JsonValue, model_validator

FilterOp = Literal[
    "eq",
    "ne",
    "lt",
    "le",
    "gt",
    "ge",
    "in",
    "not_in",
    "between",
    "contains",
    "starts_with",
    "is_null",
    "not_null",
]
AggFn = Literal["sum", "mean", "min", "max", "count", "median", "std", "first", "last"]
PivotAggFn = Literal["sum", "mean", "min", "max", "count", "median", "first", "last"]
Json = JsonValue

LIST_OPS: frozenset[str] = frozenset({"in", "not_in"})
NULL_OPS: frozenset[str] = frozenset({"is_null", "not_null"})


class QueryError(Exception):
    """A spec references a column the dataset does not have."""

    def __init__(self, column: str, dataset: str) -> None:
        super().__init__(f"Column {column!r} does not exist in dataset {dataset!r}")
        self.column = column
        self.dataset = dataset


class Filter(BaseModel):
    col: str
    op: FilterOp
    value: Json = None

    @model_validator(mode="after")
    def _check_value_shape(self) -> Filter:
        if self.op == "between":
            if not isinstance(self.value, list) or len(self.value) != 2:
                raise ValueError("between requires a two-element list value")
        elif self.op in LIST_OPS:
            if not isinstance(self.value, list):
                raise ValueError(f"{self.op} requires a list value")
        elif self.op in NULL_OPS and self.value is not None:
            raise ValueError(f"{self.op} takes no value")
        return self


class Agg(BaseModel):
    col: str
    fn: AggFn
    alias: str | None = None

    @property
    def name(self) -> str:
        return self.alias or f"{self.col}_{self.fn}"


class Pivot(BaseModel):
    index: list[str]
    columns: str
    values: str
    agg: PivotAggFn


class Sort(BaseModel):
    col: str
    desc: bool = False


class QuerySpec(BaseModel):
    dataset: str
    select: list[str] | None = None
    filters: list[Filter] = Field(default_factory=list)
    group_by: list[str] | None = None
    aggs: list[Agg] = Field(default_factory=list)
    pivot: Pivot | None = None
    sort: list[Sort] = Field(default_factory=list)
    limit: int | None = Field(default=None, gt=0)
    offset: int = Field(default=0, ge=0)
    format: Literal["json", "arrow"] = "json"

    @model_validator(mode="after")
    def _check_shape(self) -> QuerySpec:
        if self.group_by is not None and self.pivot is not None:
            raise ValueError("group_by and pivot cannot both be set")
        if self.aggs and self.group_by is None:
            raise ValueError("aggs require group_by")
        if self.group_by is not None and not self.aggs:
            raise ValueError("group_by requires at least one entry in aggs")
        return self
