import pytest

from quarry.agent.tools import CodeRun
from quarry.kernel.executor import Status
from quarry.projects.recipe import raw_recipe, recipe_steps
from quarry.server.models import Step


def step(
    index: int,
    code: str,
    *,
    reads: list[str] | None = None,
    writes: list[str] | None = None,
    defines: list[str] | None = None,
    status: Status = "ok",
    runs: list[CodeRun] | None = None,
    prompt: str | None = None,
) -> Step:
    return Step(
        id=f"st{index}",
        index=index,
        kind="prompt" if prompt else "manual",
        prompt=prompt,
        code=code,
        runs=runs if runs is not None else [CodeRun(code=code, status=status)],
        status=status,
        error=None,
        reads=reads or [],
        writes=writes or [],
        defines=defines or [],
        created_at="2026-10-08T00:00:00+00:00",
    )


def test_walks_reads_and_helpers_in_index_order() -> None:
    steps = [
        step(0, "def clean(df): return df", defines=["clean"], prompt="helper"),
        step(1, "raw = pq('x')", writes=["raw"]),
        step(2, "other = pq('y')", writes=["other"]),
        step(3, "prices = clean(raw)", reads=["clean", "raw"], writes=["prices"]),
        step(4, "later = prices.head()", reads=["prices"], writes=["later"]),
    ]
    assert [s.index for s in recipe_steps(steps, "prices")] == [0, 1, 3]
    assert raw_recipe(recipe_steps(steps, "prices")) == (
        "# step 1: helper\ndef clean(df): return df\n\n"
        "# step 2: manual\nraw = pq('x')\n\n"
        "# step 4: manual\nprices = clean(raw)\n"
    )


def test_latest_writer_before_the_consumer_wins() -> None:
    steps = [
        step(0, "df = a()", writes=["df"]),
        step(1, "out = df.x()", reads=["df"], writes=["out"]),
        step(2, "df = b()", writes=["df"]),
    ]
    assert [s.index for s in recipe_steps(steps, "out")] == [0, 1]


def test_self_rebinding_keeps_the_earlier_writer() -> None:
    steps = [
        step(0, "df = a()", writes=["df"]),
        step(1, "df = df.filter()", reads=["df"], writes=["df"]),
    ]
    assert [s.index for s in recipe_steps(steps, "df")] == [0, 1]


def test_only_ok_runs_of_a_failed_step_are_kept() -> None:
    failed = step(
        1,
        "prices = pq('p')\nprices = prices.bad()",
        writes=["prices"],
        status="error",
        runs=[
            CodeRun(code="prices = pq('p')", status="ok"),
            CodeRun(code="prices = prices.bad()", status="error"),
        ],
    )
    text = raw_recipe(recipe_steps([failed], "prices"))
    assert "prices = pq('p')" in text
    assert "bad()" not in text


def test_unknown_dataset_and_unproduced_reads() -> None:
    steps = [step(0, "df = loaders.x()", reads=["loaders"], writes=["df"])]
    assert [s.index for s in recipe_steps(steps, "df")] == [0]
    with pytest.raises(KeyError):
        recipe_steps(steps, "nope")


def test_label_keeps_every_line_break_and_unprintable_out_of_the_code() -> None:
    steps = [step(0, "df = a()", writes=["df"], prompt="load\rimport os\nnow\x00")]
    assert raw_recipe(steps) == "# step 1: load import os now\\u0000\ndf = a()\n"
