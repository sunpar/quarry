"""Save datasets and views into projects, and lay out their canvases."""

from __future__ import annotations

import builtins

from pydantic import BaseModel

from quarry.config import ConfigError, QuarryConfig
from quarry.kernel.client import RpcFailure
from quarry.projects.models import (
    CanvasCard,
    Project,
    ProjectMeta,
    SavedDatasetMeta,
    SavedViewFiles,
    SavedViewMeta,
    SaveMode,
)
from quarry.projects.recipe import raw_recipe, recipe_steps
from quarry.projects.store import NAME_RE, ProjectStore
from quarry.projects.tidy import tidy_recipe
from quarry.projects.validate import validate_recipe
from quarry.server.models import Step, now_iso
from quarry.server.service import ProviderFactory, SessionService, StepNotFound


class SaveDatasetRequest(BaseModel):
    session_id: str
    dataset: str
    mode: SaveMode
    description: str = ""


class SaveViewRequest(BaseModel):
    session_id: str
    step_id: str
    name: str
    description: str = ""
    mode: SaveMode


class UnknownDataset(Exception):
    pass


SavedView = SavedViewFiles  # the API returns the saved view exactly as stored


class ProjectService:
    def __init__(
        self,
        *,
        config: QuarryConfig,
        store: ProjectStore,
        sessions: SessionService,
        provider_factory: ProviderFactory,
    ) -> None:
        self._config = config
        self._store = store
        self._sessions = sessions
        self._provider_factory = provider_factory

    def create(self, name: str, description: str) -> ProjectMeta:
        return self._store.create(name, description)

    def list(self) -> builtins.list[ProjectMeta]:
        return self._store.list()

    def get(self, slug: str) -> Project:
        return self._store.get(slug)

    def set_canvas(self, slug: str, cards: builtins.list[CanvasCard]) -> ProjectMeta:
        return self._store.set_canvas(slug, cards)

    def view(self, slug: str, name: str) -> SavedView:
        return self._store.read_view(slug, name)

    def save_dataset(self, slug: str, req: SaveDatasetRequest) -> SavedDatasetMeta:
        self._store.meta(slug)  # KeyError for an unknown project before touching the session
        # KeyError for an unknown session before any kernel starts for it: KernelManager.get
        # spawns a kernel for any id.
        self._sessions.get(req.session_id)
        # Busy is checked before anything else so a running step answers 409, never 404.
        with self._sessions.hold(req.session_id) as kernel:
            steps = self._sessions.get(req.session_id).steps
            lineage = recipe_steps(steps, req.dataset)
            raw = raw_recipe(lineage)
            try:
                expected = kernel.describe(req.dataset)
            except RpcFailure as exc:
                raise UnknownDataset(req.dataset) from exc
            if req.mode == "pinned":
                kernel.snapshot(req.dataset, self._store.parquet_path(slug, req.dataset))
        threads = self._config.data.kernel_threads
        tidied = self._tidy(raw, req.dataset)
        candidate = tidied if tidied is not None else raw
        result = validate_recipe(
            self._config.root, candidate, req.dataset, expected, threads=threads
        )
        if not result.ok and tidied is not None:
            result = validate_recipe(self._config.root, raw, req.dataset, expected, threads=threads)
            candidate = raw
        meta = SavedDatasetMeta(
            name=req.dataset,
            description=req.description,
            backing=expected.backing,
            schema=expected.schema_,
            rows=expected.rows,
            mode=req.mode,
            saved_at=now_iso(),
            source_session=req.session_id,
            source_step=lineage[-1].id,
            validated=result.ok,
            validation_error=result.error,
        )
        self._store.write_dataset(slug, meta, recipe=candidate, raw=raw)
        return meta

    def save_view(self, slug: str, req: SaveViewRequest) -> SavedViewMeta:
        if NAME_RE.match(req.name) is None:  # before any dataset save spends a kernel
            raise ValueError(
                "view names are lowercase letters, digits, '-' and '_', up to 64 chars"
            )
        step = self._find_step(req.session_id, req.step_id)
        if step.view is None:
            raise StepNotFound(req.step_id)
        saved = {d.name for d in self._store.get(slug).datasets}
        for name in step.view.datasets:
            if name not in saved:
                self.save_dataset(
                    slug, SaveDatasetRequest(session_id=req.session_id, dataset=name, mode=req.mode)
                )
        latest = step.view.snapshots[-1] if step.view.snapshots else None
        state = latest.state if latest is not None else step.view.initial_state
        queries = latest.queries if latest is not None else []
        meta = SavedViewMeta(
            name=req.name,
            description=req.description,
            datasets=step.view.datasets,
            component_id=step.view.component_id,
            saved_at=now_iso(),
            source_session=req.session_id,
            source_step=step.id,
        )
        self._store.write_view(slug, meta, source=step.view.source, state=state, queries=queries)
        return meta

    def _tidy(self, raw: str, dataset: str) -> str | None:
        """The tidied recipe, or None when no provider is configured: a save never needs one."""
        try:
            provider = self._provider_factory(self._config)
        except ConfigError:
            return None
        return tidy_recipe(provider, raw, dataset)

    def _find_step(self, session_id: str, step_id: str) -> Step:
        for step in self._sessions.get(session_id).steps:
            if step.id == step_id:
                return step
        raise StepNotFound(step_id)
