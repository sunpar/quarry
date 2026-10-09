"""Projects on disk: one directory per project, datasets and views as subdirectories."""

from __future__ import annotations

import builtins
import json
import re
import threading
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel

from quarry.projects.files import PRIVATE_DIR, write_atomic
from quarry.projects.models import (
    CanvasCard,
    Project,
    ProjectMeta,
    SavedDatasetMeta,
    SavedViewFiles,
    SavedViewMeta,
)
from quarry.query.spec import Json
from quarry.server.models import now_iso

_NAME_RE = re.compile(r"[a-z0-9][a-z0-9_-]{0,63}")

M = TypeVar("M", bound=BaseModel)


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "project"


def check_view_name(name: str) -> None:
    if _NAME_RE.fullmatch(name) is None:
        raise ValueError("view names are lowercase letters, digits, '-' and '_', up to 64 chars")


def _read_all(directory: Path, model: type[M]) -> list[M]:
    """Every `<directory>/<name>/meta.json` that exists, in name order."""
    return [
        model.model_validate_json((p / "meta.json").read_text())
        for p in sorted(directory.glob("*/"))
        if (p / "meta.json").exists()
    ]


class ProjectStore:
    def __init__(self, root: Path) -> None:
        self._dir = root / "projects"
        # Routes run on a thread pool: every read-modify-write of project.json, and the slug
        # choice in create, happens under this lock so a save's touch cannot drop a canvas write.
        self._meta_lock = threading.Lock()

    def create(self, name: str, description: str = "") -> ProjectMeta:
        base = slugify(name)
        with self._meta_lock:
            slug, n = base, 1
            while (self._dir / slug).exists():
                n += 1
                slug = f"{base}-{n}"
            now = now_iso()
            meta = ProjectMeta(
                slug=slug, name=name, description=description, created_at=now, updated_at=now
            )
            self._write_meta(meta)
        return meta

    def list(self) -> list[ProjectMeta]:
        if not self._dir.is_dir():
            return []
        metas = [
            self._read_meta(p.name) for p in self._dir.iterdir() if (p / "project.json").exists()
        ]
        # The slug breaks ties: "Momentum" and "momentum" share a lowercased name.
        return sorted(metas, key=lambda m: (m.name.lower(), m.slug))

    def meta(self, slug: str) -> ProjectMeta:
        return self._read_meta(slug)

    def get(self, slug: str) -> Project:
        base = self._project_dir(slug)
        return Project(
            meta=self._read_meta(slug),
            datasets=_read_all(base / "datasets", SavedDatasetMeta),
            views=_read_all(base / "views", SavedViewMeta),
        )

    def set_canvas(self, slug: str, cards: builtins.list[CanvasCard]) -> ProjectMeta:
        views = [c.view for c in cards]
        if len(set(views)) != len(views):  # a card is keyed by its view
            raise ValueError("a canvas holds each view once")
        with self._meta_lock:
            meta = self._read_meta(slug).model_copy(update={"canvas": cards})
            self._write_meta(meta)
        return meta

    def write_dataset(self, slug: str, meta: SavedDatasetMeta, *, recipe: str, raw: str) -> None:
        base = self._dataset_dir(slug, meta.name)
        base.mkdir(mode=PRIVATE_DIR, parents=True, exist_ok=True)
        write_atomic(base / "recipe.raw.py", raw)
        write_atomic(base / "recipe.py", recipe)
        write_atomic(base / "meta.json", meta.model_dump_json(by_alias=True, indent=2))
        if meta.mode == "live":  # a pinned save before this one left its rows
            (base / "data.parquet").unlink(missing_ok=True)
        self._touch(slug)

    def read_recipe(self, slug: str, name: str) -> str:
        path = self._dataset_dir(slug, name) / "recipe.py"
        if not path.exists():
            raise KeyError(name)
        return path.read_text()

    def parquet_path(self, slug: str, name: str) -> Path:
        return self._dataset_dir(slug, name) / "data.parquet"

    def pinned_path(self, slug: str, name: str) -> Path:
        """Where a pinned save snapshots, in a dataset directory made private first: the
        kernel's own mkdir would make it at the kernel's umask."""
        base = self._dataset_dir(slug, name)
        base.mkdir(mode=PRIVATE_DIR, parents=True, exist_ok=True)
        return base / "data.parquet"

    def write_view(
        self,
        slug: str,
        meta: SavedViewMeta,
        *,
        source: str,
        state: dict[str, Json],
        queries: builtins.list[dict[str, Json]],
    ) -> None:
        check_view_name(meta.name)
        base = self._project_dir(slug) / "views" / meta.name
        base.mkdir(mode=PRIVATE_DIR, parents=True, exist_ok=True)
        write_atomic(base / "view.tsx", source)
        write_atomic(base / "state.json", json.dumps(state, indent=2))
        # The query specs behind the saved state; Stage 5's export renders them with to_source.
        write_atomic(base / "queries.json", json.dumps(queries, indent=2))
        write_atomic(base / "meta.json", meta.model_dump_json(indent=2))
        self._touch(slug)

    def read_view(self, slug: str, name: str) -> SavedViewFiles:
        base = self._project_dir(slug) / "views" / name
        if not (base / "meta.json").exists():
            raise KeyError(name)
        meta = SavedViewMeta.model_validate_json((base / "meta.json").read_text())
        state: dict[str, Json] = json.loads((base / "state.json").read_text())
        queries: list[dict[str, Json]] = json.loads((base / "queries.json").read_text())
        return SavedViewFiles(
            meta=meta, source=(base / "view.tsx").read_text(), state=state, queries=queries
        )

    def _dataset_dir(self, slug: str, name: str) -> Path:
        if not name.isidentifier():
            raise ValueError(f"{name!r} is not a dataset name")
        return self._project_dir(slug) / "datasets" / name

    def _project_dir(self, slug: str) -> Path:
        path = self._dir / slug
        if not (path / "project.json").exists():
            raise KeyError(slug)
        return path

    def _read_meta(self, slug: str) -> ProjectMeta:
        return ProjectMeta.model_validate_json(
            (self._project_dir(slug) / "project.json").read_text()
        )

    def _write_meta(self, meta: ProjectMeta) -> None:
        # Builds the path directly: a new project has no project.json for _project_dir to find.
        path = self._dir / meta.slug
        path.mkdir(mode=PRIVATE_DIR, parents=True, exist_ok=True)
        write_atomic(path / "project.json", meta.model_dump_json(indent=2))

    def _touch(self, slug: str) -> None:
        with self._meta_lock:
            self._write_meta(self._read_meta(slug).model_copy(update={"updated_at": now_iso()}))
