"""Column-reference checks shared by every compile target."""

from __future__ import annotations

from collections.abc import Iterable

from quarry.query.spec import QueryError, QuerySpec


def check_columns(spec: QuerySpec, available: set[str]) -> None:
    """Raise QueryError for the first column `spec` references that does not exist.

    Pivot output columns come from the data, so a pivot spec's sort and select are left
    for the caller to check with `check_output_columns` once the pivoted columns are known.
    """
    _require_columns(spec, _input_columns(spec), available)
    if spec.pivot is None:
        # sort and select run after any group_by, so they see only the columns it produced.
        produced = available
        if spec.group_by is not None:
            produced = {*spec.group_by, *(a.name for a in spec.aggs)}
        check_output_columns(spec, produced)


def check_output_columns(spec: QuerySpec, available: set[str]) -> None:
    """Raise QueryError if sort or select names a column the reshaped frame lacks."""
    _require_columns(spec, [*(s.col for s in spec.sort), *(spec.select or [])], available)


def _input_columns(spec: QuerySpec) -> list[str]:
    names = [f.col for f in spec.filters]
    if spec.group_by is not None:
        names += [*spec.group_by, *(a.col for a in spec.aggs)]
    if spec.pivot is not None:
        names += [*spec.pivot.index, spec.pivot.columns, spec.pivot.values]
    return names


def _require_columns(spec: QuerySpec, names: Iterable[str], available: set[str]) -> None:
    for name in names:
        if name not in available:
            raise QueryError(name, spec.dataset)
