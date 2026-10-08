"""Component manifests and the three-root library (builtin, researcher, team)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from quarry.kernel.datasets import DatasetMeta

DtypeClass = Literal["datetime", "numeric", "string", "other"]

log = logging.getLogger(__name__)


class SchemaRequirement(BaseModel):
    role: str
    dtype: Literal["datetime", "numeric", "string", "any"]
    min: int = 1


class ComponentSchema(BaseModel):
    requires: list[SchemaRequirement] = Field(default_factory=list)


class ComponentManifest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    contract_version: int = 1
    schema_: ComponentSchema = Field(alias="schema", default_factory=ComponentSchema)
    origin: Literal["builtin", "generated", "imported"]
    created_at: str


class ComponentEntry(BaseModel):
    manifest: ComponentManifest
    source_path: Path


def builtin_root() -> Path:
    return Path(__file__).parent / "builtin"


class ComponentLibrary:
    def __init__(self, roots: list[Path]) -> None:
        self._roots = roots

    def entries(self) -> list[ComponentEntry]:
        seen: dict[str, ComponentEntry] = {}
        for root in self._roots:
            if not root.is_dir():
                continue
            for manifest_path in sorted(root.glob("*/manifest.json")):
                source = manifest_path.parent / "component.tsx"
                if not source.exists():
                    continue
                try:
                    manifest = ComponentManifest.model_validate(
                        json.loads(manifest_path.read_text())
                    )
                # JSONDecodeError and pydantic's ValidationError are both ValueErrors.
                except ValueError as exc:
                    log.warning("skipping component manifest %s: %s", manifest_path, exc)
                    continue
                seen.setdefault(manifest.id, ComponentEntry(manifest=manifest, source_path=source))
        return list(seen.values())

    def get(self, component_id: str) -> ComponentEntry | None:
        return next((e for e in self.entries() if e.manifest.id == component_id), None)

    def search(self, *, dataset: DatasetMeta | None, tags: list[str]) -> list[ComponentManifest]:
        wanted = set(tags)
        matches = [
            e.manifest for e in self.entries() if dataset is None or satisfies(e.manifest, dataset)
        ]
        return sorted(matches, key=lambda m: (-len(wanted & set(m.tags)), m.id))


def satisfies(manifest: ComponentManifest, dataset: DatasetMeta) -> bool:
    counts: dict[str, int] = {"datetime": 0, "numeric": 0, "string": 0, "other": 0}
    for col in dataset.schema_:
        counts[dtype_class(col.dtype)] += 1
    for req in manifest.schema_.requires:
        available = len(dataset.schema_) if req.dtype == "any" else counts[req.dtype]
        if available < req.min:
            return False
    return True


def dtype_class(dtype: str) -> DtypeClass:
    if dtype == "Date" or dtype.startswith("Datetime"):
        return "datetime"
    if dtype.startswith(("Int", "UInt", "Float", "Decimal")):
        return "numeric"
    if dtype in {"String", "Utf8"} or dtype.startswith(("Categorical", "Enum")):
        return "string"
    return "other"
