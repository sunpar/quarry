"""One provider call that turns a raw step concatenation into a self-contained recipe."""

from __future__ import annotations

import ast
import re
from typing import Final

from quarry.agent.types import Message, Provider, ProviderError

TIDY_SYSTEM: Final = """\
You tidy Python recipes for a quant researcher. You receive a script that concatenates the
notebook steps which produced one dataset, and that dataset's name. Return one self-contained
Python script that produces exactly the same dataset bound to that name.

Rules: remove loads, assignments, prints and plotting the dataset does not depend on; keep
every loader call, filter, join, aggregation and column expression unchanged in meaning; keep
the imports and helper functions the dataset needs; keep the data helpers sql, pq, sql_local
and loaders as they are; end with the dataset bound to its name. Reply with Python code only,
no fences and no prose."""

_FENCE = re.compile(r"^```[a-zA-Z]*\n(.*?)\n?```\s*$", re.DOTALL)


def strip_fences(text: str) -> str:
    match = _FENCE.match(text.strip())
    body = match.group(1) if match else text.strip()
    return body.rstrip("\n") + "\n"


def tidy_recipe(provider: Provider, raw: str, dataset: str) -> str | None:
    prompt = f"Dataset name: {dataset}\n\nScript:\n{raw}"
    try:
        turn = provider.complete(
            system=TIDY_SYSTEM, messages=[Message(role="user", text=prompt)], tools=[]
        )
    except ProviderError:
        return None
    code = strip_fences(turn.text)
    if code.strip() == "" or not _binds(code, dataset):
        return None
    return code


def _binds(code: str, name: str) -> bool:
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store) and node.id == name:
            return True
    return False
