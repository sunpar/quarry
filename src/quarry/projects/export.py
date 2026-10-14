"""Export a project as a Jupyter notebook, or one saved dataset as a Python script."""

from __future__ import annotations

import json
import platform
import re
from pathlib import Path

import duckdb
import polars as pl
from pydantic import ValidationError

from quarry import __version__
from quarry.kernel.datasets import (
    backing_of,
    dataset_names,
    importable_projection,
    is_dataset,
    schema_of,
)
from quarry.kernel.lineage import analyze
from quarry.projects.models import Project, SavedDatasetMeta, SavedViewMeta
from quarry.projects.recipe import split_leading_future
from quarry.projects.store import ProjectStore
from quarry.query.source_target import IDENT_RE, imported_names, py_comment, result_names, to_source
from quarry.query.spec import Json, QueryError, QuerySpec
from quarry.server.models import to_code_input


def notebook(project: Project, store: ProjectStore) -> dict[str, Json]:
    """An nbformat 4.5 document: the setup, every saved dataset, then every saved view."""
    slug = project.meta.slug
    names = [d.name for d in project.datasets]
    recipes = [store.read_recipe(slug, name) for name in names]
    # Tokens also reserve exception aliases, which Python deletes after the handler.
    taken = set(names) | {name for recipe in recipes for name in IDENT_RE.findall(recipe)}
    query_runner = result_names([(1, "_quarry_queries")], taken)[0]
    cells: list[dict[str, Json]] = [
        _markdown(f"# {project.meta.name}\n\n{project.meta.description}".rstrip() + "\n"),
        _code(
            _setup(store.root)
            + "\n# Capture the renderer before recipes can rebind Python's builtin names.\n"
            + f"from quarry.projects.export import run_queries as {query_runner}\n"
            + f"{query_runner} = __import__('functools').partial(\n"
            + f"    {query_runner}, namespace=globals()\n"
            + ")\n"
        ),
    ]
    for i, rebinds in _recipe_order(names, recipes):
        cells.append(_markdown(_dataset_heading(project.datasets[i])))
        cells.append(_code(_rebind_warning(rebinds) + recipes[i]))
    for view in project.views:
        saved = store.read_view(slug, view.name)
        cells.append(_markdown(_view_heading(view)))
        queries, dropped = to_code_input(saved.state, saved.queries)
        left_out = py_comment(f"To code leaves out: {', '.join(dropped)}") + "\n" if dropped else ""
        cells.append(
            _code(
                left_out
                + "# Render against the rebuilt datasets, show the Python, then run it.\n"
                + f"{query_runner}({queries!r})\n"
            )
        )
        cells.append(_markdown(_fenced("tsx", saved.source.rstrip())))
    numbered: list[Json] = [{"id": f"cell-{n}", **cell} for n, cell in enumerate(cells)]
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
            "language_info": {"name": "python"},
            "quarry": {
                "export_environment": {
                    "quarry": __version__,
                    "python": platform.python_version(),
                    "polars": pl.__version__,
                    "duckdb": duckdb.__version__,
                }
            },
        },
        "cells": numbered,
    }


def notebook_json(project: Project, store: ProjectStore) -> str:
    return json.dumps(notebook(project, store), indent=1, ensure_ascii=False) + "\n"


def dataset_script(project: Project, store: ProjectStore, name: str) -> str:
    """The setup, then the recipe, as a standalone script; a pinned dataset notes its parquet."""
    saved = next((d for d in project.datasets if d.name == name), None)
    if saved is None:
        raise KeyError(name)
    lines = [
        py_comment(f"{saved.name}: {saved.description}" if saved.description else saved.name),
        py_comment(f"Saved from Quarry project {project.meta.name} on {saved.saved_at}"),
    ]
    if saved.mode == "pinned":
        path = store.parquet_path(project.meta.slug, name)
        lines.append(py_comment(f"Pinned copy: {name} = pl.read_parquet({str(path)!r})"))
    if not saved.validated:
        lines.append(py_comment(f"Not validated: {saved.validation_error}"))
    setup = _setup(store.root)
    future, recipe = split_leading_future(store.read_recipe(project.meta.slug, name))
    return "\n".join(lines) + "\n\n" + future + setup + "\n" + recipe


def _setup(root: Path) -> str:
    """Code binding the kernel's preloads, which recipes and queries use without an import."""
    namespace = (
        f"build_namespace(load_config(Path({str(root.absolute())!r})), Path(tempfile.mkdtemp()))"
    )
    return (
        "# Rebuilds Quarry's kernel namespace (pl, duckdb, pq, sql, sql_local, loaders); needs"
        " quarry importable.\n"
        "import tempfile\n"
        "from pathlib import Path\n\n"
        "from quarry.config import load_config\n"
        "from quarry.data.namespace import build_namespace\n\n"
        f"globals().update({namespace})\n"
    )


def _recipe_order(names: list[str], recipes: list[str]) -> list[tuple[int, list[str]]]:
    """Each saved dataset's index in the order its recipe runs, with the saved datasets an
    earlier recipe loaded that this one assigns again.

    A raw recipe replays its upstream steps, so it can rebind another saved dataset to data
    from before a later step changed it. A recipe that assigns another saved dataset therefore
    runs before that dataset's own recipe, which binds it last. Recipes in a cycle, which assign
    each other directly or around it, run in saved order among themselves, even when a recipe
    outside the cycle must run before one of them. Every other choice takes the earliest saved
    recipe that can run.
    """
    n = len(names)
    index = {name: i for i, name in enumerate(names)}
    assigns = [
        {index[n] for n in _stores(recipe) if n in index} - {i} for i, recipe in enumerate(recipes)
    ]
    reaches = [_reachable(assigns, i) for i in range(n)]
    # i runs before j when i's recipe assigns j and j's does not reach back to i. Inside a cycle,
    # where each reaches the other, i runs before j when it was saved first: one total order per
    # cycle, so the graph stays acyclic.
    after = [
        {
            i
            for i in range(n)
            if (j in assigns[i] and i not in reaches[j])
            or (i < j and j in reaches[i] and i in reaches[j])
        }
        for j in range(n)
    ]
    order: list[int] = []
    while len(order) < n:
        ready = (j for j in range(n) if j not in order and after[j].issubset(order))
        order.append(min(ready))
    return [
        (j, [names[i] for i in sorted(assigns[j]) if i in order[:k]]) for k, j in enumerate(order)
    ]


def _stores(recipe: str) -> frozenset[str]:
    try:
        return analyze(recipe).stores
    except SyntaxError:  # a recipe that does not parse constrains no other
        return frozenset()


def _reachable(edges: list[set[int]], start: int) -> set[int]:
    seen: set[int] = set()
    stack = [start]
    while stack:
        for j in edges[stack.pop()] - seen:
            seen.add(j)
            stack.append(j)
    return seen


def _rebind_warning(rebinds: list[str]) -> str:
    if not rebinds:
        return ""
    names = ", ".join(rebinds)
    warning = f"This recipe also assigns {names}, which an earlier cell loaded, and may rebind it"
    return py_comment(warning) + "\n"


def run_queries(queries: list[dict[str, Json]], namespace: dict[str, object]) -> None:
    """Render, display and execute a saved view's queries against the notebook's datasets.

    Result names avoid the execution namespace. An invalid query keeps its position number
    and is displayed as a comment; other queries in its view still run.
    """
    blocks: dict[int, str] = {}
    specs: list[tuple[int, QuerySpec]] = []
    for n, raw in enumerate(queries, start=1):
        try:
            specs.append((n, QuerySpec.model_validate(raw)))
        except ValidationError as exc:
            blocks[n] = _unrendered(n, str(exc))
    names = result_names([(n, spec.dataset) for n, spec in specs], namespace)
    datasets = dataset_names(namespace)
    for (n, spec), name in zip(specs, names, strict=True):
        obj = namespace[spec.dataset]
        if not is_dataset(obj):
            raise KeyError(spec.dataset)
        backing = backing_of(obj)
        schema = schema_of(obj)
        projection = (
            importable_projection(obj) if isinstance(obj, duckdb.DuckDBPyRelation) else None
        )
        try:
            blocks[n] = to_source(
                spec, backing, result_name=name, schema=schema, relation_projection=projection
            )
            # An import binds its name for every later cell, a recipe's dataset included.
            shadowed = sorted(set(imported_names(spec, backing, schema=schema)) & datasets)
            if shadowed:
                reason = (
                    f"dataset {shadowed[0]!r} would be shadowed by a generated import; rename it"
                )
                blocks[n] = _unrendered(n, reason)
        except QueryError as exc:
            blocks[n] = _unrendered(n, str(exc))
    source = "\n".join(blocks[n] for n in sorted(blocks))
    print(source)
    exec(source, namespace)


def _unrendered(n: int, reason: str) -> str:
    return py_comment(f"query {n} could not be rendered: {reason}") + "\n"


def _fenced(language: str, source: str) -> str:
    # Longer than any run of backticks in the source, which would otherwise close it early.
    longest = max((len(run) for run in re.findall(r"`+", source)), default=0)
    fence = "`" * max(3, longest + 1)
    return f"{fence}{language}\n{source}\n{fence}\n"


def _dataset_heading(d: SavedDatasetMeta) -> str:
    detail = f"{d.description}\n\n" if d.description else ""
    status = "validated" if d.validated else f"not validated: {d.validation_error}"
    rows = d.rows if d.rows is not None else "?"
    return f"## {d.name}\n\n{detail}{d.mode}, {rows} rows, {status}\n"


def _view_heading(v: SavedViewMeta) -> str:
    detail = f"{v.description}\n\n" if v.description else ""
    return (
        f"## View: {v.name}\n\n{detail}Component `{v.component_id}` over {', '.join(v.datasets)}.\n"
    )


def _markdown(source: str) -> dict[str, Json]:
    return {"cell_type": "markdown", "metadata": {}, "source": source}


def _code(source: str) -> dict[str, Json]:
    return {
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": source,
    }
