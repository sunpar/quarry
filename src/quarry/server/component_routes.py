"""Component library routes: list every library entry, save a generated component."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quarry.agent.transpile import Transpiler
from quarry.components.library import (
    COMPONENT_ID_RE,
    ComponentLibrary,
    ComponentManifest,
    ComponentSchema,
    SchemaRequirement,
    requirements_for,
    write_component,
)
from quarry.server.models import now_iso
from quarry.server.service import SessionService


class SaveComponentRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    source: str
    # The dataset the view was written against; its dtype classes become the schema requirement.
    session_id: str | None = None
    dataset: str | None = None


def register_component_routes(
    api: APIRouter,
    *,
    library: ComponentLibrary,
    researcher_root: Path,
    transpiler: Transpiler,
    sessions: SessionService,
) -> None:
    @api.get("/components")
    def list_components() -> list[ComponentManifest]:
        return [e.manifest for e in library.entries()]

    @api.post("/components", status_code=201)
    def save_component(body: SaveComponentRequest) -> ComponentManifest:
        if COMPONENT_ID_RE.match(body.id) is None:
            raise HTTPException(status_code=400, detail="ids are lowercase letters, digits and '-'")
        if library.get(body.id) is not None:
            raise HTTPException(status_code=409, detail=f"component {body.id!r} already exists")
        problem = transpiler.check(body.source)
        if problem is not None:
            raise HTTPException(status_code=400, detail=f"transpile error: {problem}")
        requires: list[SchemaRequirement] = []
        if body.session_id is not None and body.dataset is not None:
            try:
                sessions.get(body.session_id)  # KeyError before a kernel is spawned for a bad id
                listed = sessions.datasets(body.session_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="no such session") from exc
            meta = next((d for d in listed if d.name == body.dataset), None)
            if meta is None:
                raise HTTPException(status_code=404, detail=f"no dataset {body.dataset!r}")
            requires = requirements_for(meta)
        manifest = ComponentManifest(
            id=body.id,
            name=body.name,
            description=body.description,
            tags=body.tags,
            schema=ComponentSchema(requires=requires),
            origin="generated",
            created_at=now_iso(),
        )
        write_component(researcher_root, manifest, body.source)
        return manifest
