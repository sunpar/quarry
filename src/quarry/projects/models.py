"""Project records as persisted on disk (spec section 5, Project)."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quarry.kernel.datasets import Column
from quarry.query.spec import Backing, Json

SaveMode = Literal["live", "pinned"]


class CanvasCard(BaseModel):
    view: str
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    w: int = Field(ge=1)
    h: int = Field(ge=1)


class ProjectMeta(BaseModel):
    slug: str
    name: str
    description: str = ""
    created_at: str
    updated_at: str
    canvas: list[CanvasCard] = Field(default_factory=list)


class SavedDatasetMeta(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str = ""
    backing: Backing
    schema_: list[Column] = Field(alias="schema")
    rows: int | None
    mode: SaveMode
    saved_at: str
    source_session: str
    source_step: str
    validated: bool
    validation_error: str | None = None


class SavedViewMeta(BaseModel):
    name: str
    description: str = ""
    datasets: list[str]
    component_id: str
    saved_at: str
    source_session: str
    source_step: str


class Project(BaseModel):
    meta: ProjectMeta
    datasets: list[SavedDatasetMeta]
    views: list[SavedViewMeta]


class SavedViewFiles(BaseModel):
    """One saved view as read back from disk."""

    meta: SavedViewMeta
    source: str
    state: dict[str, Json]
    queries: list[dict[str, Json]]
