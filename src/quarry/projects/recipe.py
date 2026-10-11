"""Walk a session's lineage backward from a dataset and concatenate the code that made it."""

from __future__ import annotations

import ast
import io

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


def scoped_recipe(recipe: str, name: str) -> str:
    """`recipe` as code that binds only `name` where it runs. The recipe runs as a module of its
    own, in a copy of the namespace, so the other datasets it makes stay in the copy, and it runs
    as validation ran it: its `from __future__` imports, `import *`, `global` and names that
    shadow a preload, such as `sql = sql(...)`, all mean what they meant there. A lambda binds
    nothing more, and nothing loads `name` before the recipe has made it."""
    lines = "\n".join(f"        {line!r}" for line in _lines(recipe))
    return (
        f"{name} = (\n"
        f"    lambda scope: exec(\n{lines},\n        scope,\n    )\n"
        f"    or scope[{name!r}]\n"
        ")(dict(globals()))\n"
    )


def split_leading_future(code: str) -> tuple[str, str]:
    """The lines up to the last of `code`'s leading `from __future__` imports, and the rest.
    Code put before `code` must go after the first part, since Python takes those imports only
    first. A later one stays where it is: moving it would change how earlier lines compile."""
    end = 0
    for node in ast.parse(code).body:
        if not (isinstance(node, ast.ImportFrom) and node.module == "__future__"):
            break
        end = node.end_lineno or node.lineno
    lines = _lines(code)
    return "".join(lines[:end]), "".join(lines[end:])


def _lines(code: str) -> list[str]:
    """`code`'s lines as `ast` counts them: `str.splitlines` also breaks at characters such as
    U+2028, which a string literal may hold."""
    return io.StringIO(code).readlines()


def _producer(ordered: list[Step], name: str, *, before: int) -> Step | None:
    """The latest step before position `before` that wrote or defined `name`."""
    for step in reversed(ordered[:before]):
        if name in step.writes or name in step.defines:
            return step
    return None
