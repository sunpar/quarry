from pathlib import Path

from quarry.kernel.client import KernelClient
from quarry.kernel.datasets import DatasetMeta
from quarry.projects.validate import validate_recipe

RECIPE = (
    "import polars as pl\n"
    "prices = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03'], 'px': [1.0, 2.0]})\n"
)


def expected_for(root: Path, code: str) -> DatasetMeta:
    kernel = KernelClient.spawn(root)
    try:
        kernel.execute(code)
        return kernel.describe("prices")
    finally:
        kernel.shutdown()
        kernel.close()


def test_matching_recipe_validates(tmp_path: Path) -> None:
    expected = expected_for(tmp_path, RECIPE)
    result = validate_recipe(tmp_path, RECIPE, "prices", expected)
    assert result.ok and result.error is None
    assert result.meta is not None and result.meta.rows == 2


def test_row_count_mismatch_fails(tmp_path: Path) -> None:
    expected = expected_for(tmp_path, RECIPE)
    fewer = "import polars as pl\nprices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})\n"
    result = validate_recipe(tmp_path, fewer, "prices", expected)
    assert not result.ok and result.error is not None and "rows" in result.error


def test_schema_mismatch_and_errors_fail(tmp_path: Path) -> None:
    expected = expected_for(tmp_path, RECIPE)
    renamed = RECIPE.replace("'px'", "'close'")
    assert "close" in (validate_recipe(tmp_path, renamed, "prices", expected).error or "")
    broken = "prices = undefined_name()\n"
    assert "NameError" in (validate_recipe(tmp_path, broken, "prices", expected).error or "")
    unbound = "x = 1\n"
    assert "prices" in (validate_recipe(tmp_path, unbound, "prices", expected).error or "")
