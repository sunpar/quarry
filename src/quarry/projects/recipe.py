"""Walk a session's lineage backward from a dataset and concatenate the code that made it."""

from __future__ import annotations

import io
import tokenize

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
    """`recipe` as code that binds only `name` where it runs: the recipe runs in a function of
    its own, so the other datasets it makes on the way stay local to that function."""
    helper = f"_recall_{name}"
    body = f"{_indent(recipe)}    return {name}\n"
    return f"def {helper}():\n{body}\n\n{name} = {helper}()\ndel {helper}\n"


# 3.12 tokenizes f-strings in parts, and 3.14 t-strings too.
_OPENERS = {
    getattr(tokenize, n) for n in ("FSTRING_START", "TSTRING_START") if hasattr(tokenize, n)
}
_CLOSERS = {getattr(tokenize, n) for n in ("FSTRING_END", "TSTRING_END") if hasattr(tokenize, n)}


def _indent(code: str) -> str:
    """`code` one level in, every line ending in a newline; the lines inside a multi-line
    string stay as written, since indenting them would change the string."""
    code = code if code.endswith("\n") else code + "\n"
    inside: set[int] = set()  # lines, counted from 1, that continue a string
    opened: list[int] = []
    for tok in tokenize.generate_tokens(io.StringIO(code).readline):
        if tok.type in _OPENERS:
            opened.append(tok.start[0])
            continue
        if tok.type == tokenize.STRING:
            first = tok.start[0]
        elif tok.type in _CLOSERS:
            first = opened.pop()
        else:
            continue
        inside.update(range(first + 1, tok.end[0] + 1))
    lines = code.splitlines(keepends=True)
    return "".join(
        line if n in inside or line.strip() == "" else "    " + line
        for n, line in enumerate(lines, start=1)
    )


def _producer(ordered: list[Step], name: str, *, before: int) -> Step | None:
    """The latest step before position `before` that wrote or defined `name`."""
    for step in reversed(ordered[:before]):
        if name in step.writes or name in step.defines:
            return step
    return None
