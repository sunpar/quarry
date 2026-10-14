"""Export saved project artifacts as a self-contained, script-free HTML report."""

from __future__ import annotations

import json
from collections.abc import Iterator
from html import escape

import polars as pl

from quarry.kernel.datasets import PREVIEW_ROWS
from quarry.projects.models import Project
from quarry.projects.store import ProjectStore

REPORT_BYTES = 5 * 1024 * 1024
_TEXT_CHARS = 4096
_LIMIT_ERROR = "HTML report exceeds 5 MiB; reduce saved content before exporting"

_STYLE = """
body { margin: 0; color: #182d44; background: #fff; font: 16px/1.6 system-ui, sans-serif; }
main { max-width: 960px; margin: auto; padding: 40px 24px; }
h1, h2 { font-family: Georgia, serif; line-height: 1.2; overflow-wrap: anywhere; }
h1 { font-size: 36px; } h2 { font-size: 28px; margin-top: 48px; }
h3 { font-size: 22px; margin-bottom: 8px; overflow-wrap: anywhere; }
header { border-bottom: 4px solid #2c6575; padding-bottom: 24px; }
section { margin: 24px 0; padding-bottom: 24px; border-bottom: 1px solid #c5d0db; }
p { max-width: 75ch; overflow-wrap: anywhere; }
pre { white-space: pre-wrap; overflow-wrap: anywhere; padding: 16px; background: #eff3f7;
      font: 13px/1.5 ui-monospace, monospace; }
details { margin: 16px 0; } summary { cursor: pointer; color: #2c6575; }
summary:focus-visible { outline: 2px solid #2c6575; outline-offset: 4px; }
.table { overflow-x: auto; } table { border-collapse: collapse; font-size: 14px; width: 100%; }
caption { text-align: left; padding: 8px 0; } th { text-align: left; background: #eff3f7; }
th, td { border: 1px solid #c5d0db; padding: 8px 12px; overflow-wrap: anywhere; }
@media print { main { max-width: none; padding: 0; } pre { background: none; } }
"""


class ReportError(Exception):
    """A saved artifact cannot be read, or the report exceeds its output limit."""


def report_html(project: Project, store: ProjectStore) -> str:
    """Render saved records and bounded pinned rows without running recipes or views."""
    chunks: list[str] = []
    size = 0
    try:
        for chunk in _sections(project, store):
            size += len(chunk.encode("utf-8"))
            if size > REPORT_BYTES:
                raise ReportError(_LIMIT_ERROR)
            chunks.append(chunk)
    except (OSError, ValueError, KeyError) as exc:
        raise ReportError(f"cannot read saved artifact: {exc}") from exc
    return "".join(chunks)


def _sections(project: Project, store: ProjectStore) -> Iterator[str]:
    yield (
        '<!doctype html><html lang="en"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; '
        "style-src 'unsafe-inline'; base-uri 'none'; form-action 'none'\">"
        "<title>"
    )
    yield from _text(project.meta.name)
    yield f" | Quarry report</title><style>{_STYLE}</style></head><body><main><header><h1>"
    yield from _text(project.meta.name)
    yield "</h1><p>"
    yield from _text(project.meta.description)
    yield (
        "</p>"
        "<p>Frozen Quarry report. Results come only from saved pinned rows. "
        "Recipes, queries, and views do not run during export.</p>"
        "<p>Upstream freshness unavailable: saved timestamps record Quarry saves, "
        "not source data updates.</p></header>"
        "<details><summary>Project metadata and canvas layout</summary>"
    )
    yield from _json(project.meta.model_dump())
    yield "</details><h2>Saved datasets</h2>"
    if not project.datasets:
        yield "<p>No saved datasets.</p>"
    for dataset in project.datasets:
        yield "<section><h3>"
        yield from _text(dataset.name)
        yield "</h3><p>"
        yield from _text(dataset.description)
        yield "</p><details><summary>Dataset metadata and schema</summary>"
        yield from _json(dataset.model_dump(by_alias=True))
        yield "</details>"
        if dataset.mode == "pinned":
            try:
                preview = pl.read_parquet(
                    store.parquet_path(project.meta.slug, dataset.name), n_rows=PREVIEW_ROWS
                )
            except (OSError, pl.exceptions.PolarsError) as exc:
                raise ReportError(f"cannot read pinned rows for {dataset.name!r}: {exc}") from exc
            yield (
                '<div class="table"><table><caption>'
                f"Pinned preview: first {preview.height} rows, limited to {PREVIEW_ROWS} rows. "
                "This is a dataset preview, not a saved view result.</caption><thead><tr>"
            )
            for name in preview.columns:
                yield '<th scope="col">'
                yield from _text(name)
                yield "</th>"
            yield "</tr></thead><tbody>"
            for row in preview.iter_rows():
                yield "<tr>"
                for value in row:
                    yield "<td>"
                    yield from _text(str(value) if value is not None else "null")
                    yield "</td>"
                yield "</tr>"
            yield "</tbody></table></div>"
        else:
            yield "<p>Live results unavailable: this save contains a recipe, not result rows.</p>"
        yield "<details><summary>Saved recipe</summary><pre>"
        yield from _text(store.read_recipe(project.meta.slug, dataset.name))
        yield "</pre></details></section>"
    yield "<h2>Saved views</h2>"
    if not project.views:
        yield "<p>No saved views.</p>"
    for view in project.views:
        saved = store.read_view(project.meta.slug, view.name)
        yield "<section><h3>"
        yield from _text(view.name)
        yield "</h3><p>"
        yield from _text(view.description)
        yield (
            "</p>"
            "<p>View results unavailable: rendered results are not persisted with saved views.</p>"
            "<details><summary>View metadata</summary>"
        )
        yield from _json(view.model_dump())
        yield "</details><details><summary>Saved state</summary>"
        yield from _json(saved.state)
        yield "</details><details><summary>Saved query specs</summary>"
        yield from _json(saved.queries)
        yield "</details><details><summary>Saved view source</summary><pre>"
        yield from _text(saved.source)
        yield "</pre></details></section>"
    yield "</main></body></html>\n"


def _text(text: str) -> Iterator[str]:
    _bound_text(text)
    for start in range(0, len(text), _TEXT_CHARS):
        yield escape(text[start : start + _TEXT_CHARS])


def _bound_text(text: str, *, json_string: bool = False) -> None:
    if len(text) > REPORT_BYTES:
        raise ReportError(_LIMIT_ERROR)
    size = 2 if json_string else 0
    for start in range(0, len(text), _TEXT_CHARS):
        chunk = text[start : start + _TEXT_CHARS]
        if json_string:
            chunk = json.dumps(chunk, ensure_ascii=False)[1:-1]
        size += len(chunk.encode("utf-8"))
        if size > REPORT_BYTES:
            raise ReportError(_LIMIT_ERROR)


def _json(value: object) -> Iterator[str]:
    for text in _strings(value):
        _bound_text(text, json_string=True)
    yield "<pre>"
    for chunk in json.JSONEncoder(indent=2, ensure_ascii=False).iterencode(value):
        yield from _text(chunk)
    yield "</pre>"


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield from _strings(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)
