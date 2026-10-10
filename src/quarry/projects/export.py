"""Export a project as a Jupyter notebook, or one saved dataset as a Python script."""

from __future__ import annotations

import json
import uuid
from collections.abc import Mapping

from pydantic import ValidationError

from quarry.projects.models import Project, SavedDatasetMeta, SavedViewMeta
from quarry.projects.store import ProjectStore
from quarry.query.source_target import imported_names, result_names, to_source
from quarry.query.spec import Backing, Json, QueryError, QuerySpec

NO_SCHEMA_NOTE = (
    "# Rendered from the saved view's queries without a schema: literals are as the view sent\n"
    '# them, and integer sums are plain, so an Int64 sum can wrap. Run "To code" in a session\n'
    "# for a rendering against the live schema.\n"
)


def notebook(project: Project, store: ProjectStore) -> dict[str, Json]:
    """An nbformat 4.5 document: every saved dataset, then every saved view."""
    slug = project.meta.slug
    cells: list[Json] = [
        _markdown(f"# {project.meta.name}\n\n{project.meta.description}".rstrip() + "\n")
    ]
    for dataset in project.datasets:
        cells.append(_markdown(_dataset_heading(dataset)))
        cells.append(_code(store.read_recipe(slug, dataset.name)))
    backings = {d.name: d.backing for d in project.datasets}
    # Every name a cell binds, so no view's result overwrites what another cell reads.
    taken = set(backings)
    for view in project.views:
        saved = store.read_view(slug, view.name)
        cells.append(_markdown(_view_heading(view)))
        cells.append(_code(_queries_source(saved.queries, backings, taken)))
        cells.append(_markdown(f"```tsx\n{saved.source.rstrip()}\n```\n"))
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


def notebook_json(project: Project, store: ProjectStore) -> str:
    return json.dumps(notebook(project, store), indent=1, ensure_ascii=False) + "\n"


def dataset_script(project: Project, store: ProjectStore, name: str) -> str:
    """The recipe as a standalone script; a pinned dataset also notes its parquet file."""
    saved = next((d for d in project.datasets if d.name == name), None)
    if saved is None:
        raise KeyError(name)
    lines = [
        _comment(f"{saved.name}: {saved.description}" if saved.description else saved.name),
        _comment(f"Saved from Quarry project {project.meta.name} on {saved.saved_at}"),
    ]
    if saved.mode == "pinned":
        path = store.parquet_path(project.meta.slug, name)
        lines.append(_comment(f"Pinned copy: {name} = pl.read_parquet({str(path)!r})"))
    if not saved.validated:
        lines.append(_comment(f"Not validated: {saved.validation_error}"))
    return "\n".join(lines) + "\n\n" + store.read_recipe(project.meta.slug, name)


def _queries_source(
    queries: list[dict[str, Json]], backings: Mapping[str, Backing], taken: set[str]
) -> str:
    """The view's queries as Python, each assigning a name outside `taken`, which gains them.

    A query that fails validation still uses up its position's number.
    """
    blocks: dict[int, str] = {}
    specs: list[tuple[int, QuerySpec]] = []
    for n, raw in enumerate(queries, start=1):
        try:
            specs.append((n, QuerySpec.model_validate(raw)))
        except ValidationError as exc:
            blocks[n] = _unrendered(n, str(exc))
    names = result_names([(n, spec.dataset) for n, spec in specs], taken)
    taken.update(names)
    for (n, spec), name in zip(specs, names, strict=True):
        backing = backings.get(spec.dataset, "polars")
        # An import binds its name for every later cell, a saved dataset's included.
        shadowed = sorted(set(imported_names(spec, backing)) & backings.keys())
        if shadowed:
            reason = f"dataset {shadowed[0]!r} would be shadowed by a generated import; rename it"
            blocks[n] = _unrendered(n, reason)
            continue
        try:
            blocks[n] = to_source(spec, backing, result_name=name)
        except QueryError as exc:
            blocks[n] = _unrendered(n, str(exc))
    return "\n".join([NO_SCHEMA_NOTE, *(blocks[n] for n in sorted(blocks))])


def _unrendered(n: int, reason: str) -> str:
    return _comment(f"query {n} could not be rendered: {reason}") + "\n"


def _comment(text: str) -> str:
    # Every line break, `\r` included, would end the comment and run the rest as code.
    return "# " + " ".join(text.splitlines())


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
    return {"id": uuid.uuid4().hex[:8], "cell_type": "markdown", "metadata": {}, "source": source}


def _code(source: str) -> dict[str, Json]:
    return {
        "id": uuid.uuid4().hex[:8],
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": source,
    }
