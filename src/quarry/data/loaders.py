"""Registry of the firm's internal loader functions, declared in loaders.toml."""

from __future__ import annotations

import importlib
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field


class LoaderSpec(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    name: str
    description: str
    import_: str = Field(alias="import")
    signature: str


class LoaderFailure(BaseModel):
    name: str
    error: str


Loaders = SimpleNamespace


@dataclass(slots=True)
class LoaderRegistry:
    specs: list[LoaderSpec] = field(default_factory=list)
    functions: dict[str, Callable[..., object]] = field(default_factory=dict)
    failures: list[LoaderFailure] = field(default_factory=list)

    def bound(self) -> Loaders:
        return SimpleNamespace(**self.functions)


def load_loaders(path: Path) -> LoaderRegistry:
    registry = LoaderRegistry()
    if not path.exists():
        return registry
    with path.open("rb") as handle:
        raw = tomllib.load(handle)
    for entry in raw.get("loader", []):
        spec = LoaderSpec.model_validate(entry)
        registry.specs.append(spec)
        try:
            registry.functions[spec.name] = _import(spec.import_)
        # Importing runs the firm's module code, which can fail in any way (a server it reaches
        # at import time is down). Any failed import skips that loader; the kernel still starts.
        except Exception as exc:
            error = f"{spec.import_}: {type(exc).__name__}: {exc}"
            registry.failures.append(LoaderFailure(name=spec.name, error=error))
    return registry


def describe_loaders(registry: LoaderRegistry) -> str:
    return "\n".join(
        f"loaders.{s.name}: {s.signature} -- {s.description}"
        for s in registry.specs
        if s.name in registry.functions
    )


def _import(target: str) -> Callable[..., object]:
    module_name, _, attr = target.partition(":")
    if not module_name or not attr:
        raise ValueError(f"import must look like module:function, got {target!r}")
    module = importlib.import_module(module_name)
    func: object = getattr(module, attr)
    if not callable(func):
        raise ValueError(f"{target} is not callable")
    return func
