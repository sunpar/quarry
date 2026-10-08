"""Registry of the firm's internal loader functions, declared in loaders.toml."""

from __future__ import annotations

import importlib
import keyword
import tomllib
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from quarry.errors import exception_message


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
    """The loaders declared in `path`. Never raises: every kernel builds its namespace from
    this, so a broken file, entry, or import becomes a failure and the rest still bind."""
    registry = LoaderRegistry()
    if not path.exists():
        return registry
    entries = _read_entries(path)
    if isinstance(entries, LoaderFailure):
        registry.failures.append(entries)
        return registry
    for index, entry in enumerate(entries):
        spec = _check(index, entry, taken={s.name for s in registry.specs})
        if isinstance(spec, LoaderFailure):
            registry.failures.append(spec)
            continue
        registry.specs.append(spec)
        try:
            registry.functions[spec.name] = _import(spec.import_)
        # Importing runs the firm's module code, which can fail in any way (a server it reaches
        # at import time is down, or it calls sys.exit()). Any failed import skips that loader;
        # the kernel still starts. A KeyboardInterrupt is not a failed import, so it propagates.
        # The message is guarded too: the module's exception can fail in its own __str__.
        except (Exception, SystemExit) as exc:
            error = f"{spec.import_}: {type(exc).__name__}: {exception_message(exc)}"
            registry.failures.append(LoaderFailure(name=spec.name, error=error))
    return registry


def describe_loaders(registry: LoaderRegistry) -> str:
    return "\n".join(
        f"loaders.{s.name}: {s.signature} -- {s.description}"
        for s in registry.specs
        if s.name in registry.functions
    )


def _read_entries(path: Path) -> list[object] | LoaderFailure:
    try:
        with path.open("rb") as handle:
            raw = tomllib.load(handle)
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        return LoaderFailure(name=path.name, error=f"{type(exc).__name__}: {exc}")
    entries = raw.get("loader", [])
    if not isinstance(entries, list):
        error = "`loader` must be an array of tables: start each entry with [[loader]]"
        return LoaderFailure(name=path.name, error=error)
    return entries


def _check(index: int, entry: object, *, taken: set[str]) -> LoaderSpec | LoaderFailure:
    """`entry` as a spec that can be bound as `loaders.<name>`, or why it cannot."""
    try:
        spec = LoaderSpec.model_validate(entry)
    except ValidationError as exc:
        return LoaderFailure(name=_entry_name(index, entry), error=_invalid(exc))
    if not spec.name.isidentifier() or keyword.iskeyword(spec.name):
        error = f"{spec.name!r} is not a Python identifier, so loaders.<name> cannot reach it"
        return LoaderFailure(name=spec.name, error=error)
    if spec.name in taken:
        error = f"duplicate name {spec.name!r}: the first entry with this name is kept"
        return LoaderFailure(name=spec.name, error=error)
    return spec


def _entry_name(index: int, entry: object) -> str:
    name = entry.get("name") if isinstance(entry, dict) else None
    return name if isinstance(name, str) else f"loader[{index}]"


def _invalid(exc: ValidationError) -> str:
    problems = "; ".join(
        f"{'.'.join(str(part) for part in error['loc']) or 'entry'}: {error['msg']}"
        for error in exc.errors()
    )
    return f"invalid loader entry: {problems}"


def _import(target: str) -> Callable[..., object]:
    module_name, _, attr = target.partition(":")
    if not module_name or not attr:
        raise ValueError(f"import must look like module:function, got {target!r}")
    module = importlib.import_module(module_name)
    func: object = getattr(module, attr)
    if not callable(func):
        raise ValueError(f"{target} is not callable")
    return func
