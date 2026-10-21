"""Component manifests and the three-root library (builtin, researcher, team)."""

from __future__ import annotations

import json
import logging
import re
from collections import Counter
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict, Field, PositiveInt

from quarry.kernel.datasets import DatasetMeta
from quarry.projects.files import PRIVATE_DIR, child, write_atomic

DtypeClass = Literal["datetime", "numeric", "string", "other"]
_TYPED: Final[tuple[Literal["datetime", "numeric", "string"], ...]] = (
    "datetime",
    "numeric",
    "string",
)
# `\Z`, not `$`: `$` also matches before a trailing newline.
COMPONENT_ID_RE: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}\Z")

log = logging.getLogger(__name__)


# Manifest models forbid unknown keys: a misspelled one would fall back to its default silently.
class _Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SchemaRequirement(_Manifest):
    role: str
    dtype: Literal["datetime", "numeric", "string", "any"]
    min: PositiveInt = 1


class ComponentSchema(_Manifest):
    requires: list[SchemaRequirement] = Field(default_factory=list)


class ComponentManifest(_Manifest):
    model_config = ConfigDict(populate_by_name=True)

    id: str
    name: str
    description: str
    tags: list[str] = Field(default_factory=list)
    # The only contract the runtime mounts; a manifest for another one is skipped.
    contract_version: Literal[1] = 1
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
                        json.loads(manifest_path.read_bytes())
                    )
                # Unreadable or bad content; JSONDecodeError and ValidationError are ValueErrors.
                except (OSError, ValueError) as exc:
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
    """Each role needs columns of its own: typed roles take their dtype's, and `any` roles
    take what is left."""
    counts: Counter[str] = Counter(dtype_class(col.dtype) for col in dataset.schema_)
    needed: Counter[str] = Counter()
    for req in manifest.schema_.requires:
        needed[req.dtype] += req.min
    if any(counts[dtype] < n for dtype, n in needed.items() if dtype != "any"):
        return False
    return len(dataset.schema_) >= needed.total()


def requirements_for(meta: DatasetMeta) -> list[SchemaRequirement]:
    """One requirement per dtype class the dataset has, so the library offers the component
    to datasets shaped like the one it was written against."""
    counts: Counter[str] = Counter(dtype_class(col.dtype) for col in meta.schema_)
    return [
        SchemaRequirement(role=cls, dtype=cls, min=counts[cls]) for cls in _TYPED if counts[cls] > 0
    ]


def write_component(root: Path, manifest: ComponentManifest, source: str) -> Path:
    """Write `manifest` and `source` into a new `root/<id>/`, returning that directory. A folder
    already there is a FileExistsError: the library skips one with a bad manifest, so it may
    hold files a researcher wrote. The library lists a component once both files exist, so
    the manifest goes last."""
    root.mkdir(mode=PRIVATE_DIR, parents=True, exist_ok=True)
    target = child(root, manifest.id)
    target.mkdir(mode=PRIVATE_DIR)
    write_atomic(target / "component.tsx", source)
    write_atomic(target / "manifest.json", manifest.model_dump_json(by_alias=True, indent=2))
    return target


def dtype_class(dtype: str) -> DtypeClass:
    if dtype == "Date" or dtype.startswith("Datetime"):
        return "datetime"
    if dtype.startswith(("Int", "UInt", "Float", "Decimal")):
        return "numeric"
    if dtype in {"String", "Utf8"} or dtype.startswith(("Categorical", "Enum")):
        return "string"
    return "other"
