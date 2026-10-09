"""Run a recipe in a throwaway kernel and compare what it produces with the live dataset."""

from __future__ import annotations

from pathlib import Path

from quarry.kernel.client import KernelClient, KernelDead, RpcFailure
from quarry.kernel.datasets import DatasetMeta


def validate_recipe(
    root: Path, recipe: str, name: str, expected: DatasetMeta, *, threads: int = 0
) -> str | None:
    """None when the recipe reproduces `expected`, otherwise why it does not."""
    try:
        kernel = KernelClient.spawn(root, threads=threads)
    except KernelDead as exc:
        return f"scratch kernel failed to start: {exc}"
    try:
        result = kernel.execute(recipe)
        if result.status != "ok":
            detail = result.error.traceback if result.error else result.status
            return f"recipe failed: {detail}"
        try:
            actual = kernel.describe(name)
        except RpcFailure as exc:
            return f"recipe did not produce {name}: {exc}"
    except KernelDead as exc:
        return f"scratch kernel died: {exc}"
    finally:
        kernel.shutdown()
        kernel.close()
    return _compare(expected, actual)


def _compare(expected: DatasetMeta, actual: DatasetMeta) -> str | None:
    want = [(c.name, c.dtype) for c in expected.schema_]
    got = [(c.name, c.dtype) for c in actual.schema_]
    if want != got:
        return f"schema differs: expected {want}, recipe produced {got}"
    if expected.rows is not None and actual.rows is not None and expected.rows != actual.rows:
        return f"rows differ: expected {expected.rows}, recipe produced {actual.rows}"
    return None
