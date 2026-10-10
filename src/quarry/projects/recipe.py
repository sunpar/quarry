"""Walk a session's lineage backward from a dataset and concatenate the code that made it."""

from __future__ import annotations

from quarry.query.source_target import py_comment
from quarry.server.models import Step


def recipe_steps(steps: list[Step], dataset: str) -> list[Step]:
    """Every step the dataset depends on, in index order; KeyError if nothing wrote it."""
    ordered = sorted((s for s in steps if s.status != "running"), key=lambda s: s.index)
    root = _producer(ordered, dataset, before=len(ordered))
    if root is None:
        raise KeyError(dataset)
    chosen: dict[int, Step] = {}
    pending = [root]
    while pending:
        step = pending.pop()
        if step.index in chosen:
            continue
        chosen[step.index] = step
        position = ordered.index(step)
        for name in step.reads:
            producer = _producer(ordered, name, before=position)
            if producer is not None and producer.index not in chosen:
                pending.append(producer)
    return [chosen[i] for i in sorted(chosen)]


def raw_recipe(steps: list[Step]) -> str:
    blocks: list[str] = []
    for step in steps:
        code = "\n".join(run.code.rstrip("\n") for run in step.runs if run.status == "ok")
        if code == "":
            continue
        label = py_comment(f"step {step.index + 1}: {step.prompt or step.kind}")
        blocks.append(f"{label}\n{code}\n")
    return "\n".join(blocks)


def _producer(ordered: list[Step], name: str, *, before: int) -> Step | None:
    """The latest step before position `before` that wrote or defined `name`."""
    for step in reversed(ordered[:before]):
        if name in step.writes or name in step.defines:
            return step
    return None
