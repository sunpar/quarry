"""Project routes: create and list projects, save datasets and views, lay out the canvas."""

from __future__ import annotations

from collections.abc import Callable
from typing import TypeVar

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from quarry.kernel.client import KernelDead
from quarry.projects.models import (
    CanvasCard,
    Project,
    ProjectMeta,
    SavedDatasetMeta,
    SavedViewMeta,
)
from quarry.server.kernels import SessionBusy
from quarry.server.projects import (
    ProjectService,
    SaveDatasetRequest,
    SavedView,
    SaveViewRequest,
    UnknownDataset,
)
from quarry.server.service import SessionService, StepNotFound

T = TypeVar("T")


class CreateProjectRequest(BaseModel):
    name: str
    description: str = ""


def register_project_routes(
    api: APIRouter, projects: ProjectService, sessions: SessionService
) -> None:
    @api.post("/projects", status_code=201)
    def create_project(body: CreateProjectRequest) -> ProjectMeta:
        if body.name.strip() == "":
            raise HTTPException(status_code=400, detail="a project needs a name")
        return projects.create(body.name.strip(), body.description)

    @api.get("/projects")
    def list_projects() -> list[ProjectMeta]:
        return projects.list()

    @api.get("/projects/{slug}")
    def get_project(slug: str) -> Project:
        return _found(lambda: projects.get(slug))

    @api.get("/projects/{slug}/views/{name}")
    def get_saved_view(slug: str, name: str) -> SavedView:
        return _found(lambda: projects.view(slug, name))

    @api.post("/projects/{slug}/datasets")
    def save_dataset(slug: str, body: SaveDatasetRequest) -> SavedDatasetMeta:
        return _saving(lambda: projects.save_dataset(slug, body))

    @api.post("/projects/{slug}/views")
    def save_view(slug: str, body: SaveViewRequest) -> SavedViewMeta:
        return _saving(lambda: projects.save_view(slug, body))

    @api.put("/projects/{slug}/canvas")
    def set_canvas(slug: str, body: list[CanvasCard]) -> ProjectMeta:
        return _found(lambda: projects.set_canvas(slug, body))


def _found(call: Callable[[], T]) -> T:
    try:
        return call()
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=f"not found: {exc}") from exc


def _saving(call: Callable[[], T]) -> T:
    try:
        return _found(call)
    except (UnknownDataset, StepNotFound) as exc:
        raise HTTPException(status_code=404, detail=f"not found: {exc}") from exc
    except SessionBusy as exc:
        raise HTTPException(
            status_code=409, detail="a step is running; save when it finishes"
        ) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except KernelDead as exc:
        raise HTTPException(status_code=503, detail="kernel is dead; restart the session") from exc
