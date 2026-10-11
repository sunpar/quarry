"""Walk a session's lineage backward from a dataset and concatenate the code that made it."""

from __future__ import annotations

import ast
import io
import tokenize

from quarry.kernel.lineage import analyze
from quarry.query.source_target import py_comment
from quarry.server.models import Step


def recipe_steps(steps: list[Step], dataset: str) -> list[Step]:
    """Every step the dataset depends on, in index order; KeyError if nothing wrote it."""
    ordered = sorted((s for s in steps if s.status != "running"), key=lambda s: s.index)
    root = _producer(ordered, dataset, before=len(ordered))
    if root is None:
        raise KeyError(dataset)
    # Pairs of a step's position and the position its names resolve before. At its own, a step
    # resolves its reads; a helper's step also resolves every name its code loads before each
    # step calling the helper, since a function reads its globals when called, including names
    # that did not exist yet when it was defined, which its step's reads leave out.
    pending = [(root, root)]
    seen: set[tuple[int, int]] = set()
    loads: dict[int, frozenset[str]] = {}
    while pending:
        pos, at = pending.pop()
        if (pos, at) in seen:
            continue
        seen.add((pos, at))
        step = ordered[pos]
        if at != pos and pos not in loads:
            loads[pos] = _loads(step)
        for name in step.reads if at == pos else loads[pos]:
            producer = _producer(ordered, name, before=at)
            if producer is None:
                continue
            pending.append((producer, producer))
            if name in ordered[producer].defines:
                pending.append((producer, at))
    return [ordered[pos] for pos in sorted({pos for pos, _ in seen})]


def raw_recipe(steps: list[Step]) -> str:
    blocks: list[str] = []
    for step in steps:
        code = "\n".join(run.code.rstrip("\n") for run in step.runs if run.status == "ok")
        if code == "":
            continue
        label = py_comment(f"step {step.index + 1}: {step.prompt or step.kind}")
        blocks.append(f"{label}\n{code}\n")
    return hoist_future("\n".join(blocks))


def scoped_recipe(recipe: str, name: str) -> str:
    """`recipe` as code that binds only `name` where it runs: the recipe runs in a function
    named `name`, which the result then replaces, so the other datasets it makes on the way
    stay local to it. Its `from __future__` imports stay at module level, the only place Python
    takes them."""
    future, rest = _split_future(recipe)
    return f"{future}def {name}():\n{_indent(rest)}    return {name}\n\n\n{name} = {name}()\n"


def hoist_future(code: str) -> str:
    """`code` with every `from __future__` import first, as joined recipes need: Python refuses
    one after any other statement."""
    future, rest = _split_future(code)
    return future + rest


def _split_future(code: str) -> tuple[str, str]:
    """The lines holding module-level `from __future__` imports, and the rest of `code`."""
    tree = ast.parse(code)
    lines = _lines(code)
    moved = {
        i
        for node in tree.body
        if isinstance(node, ast.ImportFrom) and node.module == "__future__"
        for i in range(node.lineno - 1, node.end_lineno or node.lineno)
    }
    future = "".join(lines[i] for i in sorted(moved))
    rest = "".join(line for i, line in enumerate(lines) if i not in moved)
    return future, rest


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
    return "".join(
        line if n in inside or line.strip() == "" else "    " + line
        for n, line in enumerate(_lines(code), start=1)
    )


def _lines(code: str) -> list[str]:
    """`code`'s lines as `ast` and `tokenize` count them: `str.splitlines` also breaks at
    characters such as U+2028, which a string literal may hold."""
    return io.StringIO(code).readlines()


def _loads(step: Step) -> frozenset[str]:
    """Every name the step's code loads, inside its functions too."""
    return frozenset().union(*(analyze(run.code).loads for run in step.runs if run.status == "ok"))


def _producer(ordered: list[Step], name: str, *, before: int) -> int | None:
    """The position of the latest step before position `before` that wrote or defined `name`."""
    for pos in range(before - 1, -1, -1):
        if name in ordered[pos].writes or name in ordered[pos].defines:
            return pos
    return None
