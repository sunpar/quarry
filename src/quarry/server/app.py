"""FastAPI application: loopback, bearer token, sessions and steps."""

from __future__ import annotations

import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from quarry.agent.transpile import default_transpiler
from quarry.components.library import ComponentLibrary, builtin_root
from quarry.config import QuarryConfig
from quarry.kernel.client import KernelDead, RpcFailure
from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import QueryResult
from quarry.query.spec import Json, QueryError, QuerySpec
from quarry.server.kernels import KernelManager, ReplayReport
from quarry.server.models import Session, SessionMeta, Step
from quarry.server.service import (
    CreateSessionRequest,
    ManualStepRequest,
    ProviderFactory,
    SessionBusy,
    SessionService,
    SessionStatus,
    StepRequest,
    provider_from_config,
)
from quarry.server.store import SessionStore


def create_app(
    *,
    config: QuarryConfig,
    token: str,
    provider_factory: ProviderFactory = provider_from_config,
    static_dir: Path | None = None,
) -> FastAPI:
    static = static_dir or Path(__file__).parent.parent / "static"
    roots = [builtin_root(), config.root / "components"]
    if config.libraries.team_components is not None:
        roots.append(config.libraries.team_components)
    service = SessionService(
        config=config,
        store=SessionStore(config.root),
        kernels=KernelManager(config.root, threads=config.data.kernel_threads),
        provider_factory=provider_factory,
        library=ComponentLibrary(roots),
        transpiler=default_transpiler(static),
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        service.shutdown()

    app = FastAPI(
        title="Quarry", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.service = service

    def authed(authorization: Annotated[str | None, Header()] = None) -> None:
        # Bytes: compare_digest raises on a str with non-ASCII characters, which a client sends.
        expected = f"Bearer {token}".encode()
        if authorization is None or not secrets.compare_digest(authorization.encode(), expected):
            raise HTTPException(status_code=401, detail="missing or invalid token")

    # Every route but /healthz and the UI's static files needs the token.
    api = APIRouter(dependencies=[Depends(authed)])

    def session_or_404(session_id: str) -> Session:
        try:
            return service.get(session_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="no such session") from exc

    @app.get("/healthz")
    def healthz() -> dict[str, bool]:
        return {"ok": True}

    @api.post("/sessions", status_code=201)
    def create_session(body: CreateSessionRequest) -> SessionMeta:
        return service.create(body.title)

    @api.get("/sessions")
    def list_sessions() -> list[SessionMeta]:
        return service.list()

    @api.get("/sessions/{session_id}")
    def get_session(session_id: str) -> Session:
        return session_or_404(session_id)

    @api.post("/sessions/{session_id}/steps", status_code=202)
    def post_step(session_id: str, body: StepRequest) -> Step:
        session_or_404(session_id)
        return service.start_prompt(session_id, body.prompt)

    @api.post("/sessions/{session_id}/steps/manual", status_code=202)
    def post_manual(session_id: str, body: ManualStepRequest) -> Step:
        session_or_404(session_id)
        return service.start_manual(session_id, body.code)

    @api.get("/sessions/{session_id}/status")
    def get_status(session_id: str) -> SessionStatus:
        session_or_404(session_id)
        return service.status(session_id)

    @api.post("/sessions/{session_id}/interrupt")
    def interrupt(session_id: str) -> dict[str, bool]:
        session_or_404(session_id)
        return {"ok": service.interrupt(session_id)}

    # The body is validated here, not by FastAPI, so a rejected spec is a 400 rather than a 422.
    @api.post("/sessions/{session_id}/query")
    def query(session_id: str, body: dict[str, Json]) -> QueryResult:
        session_or_404(session_id)
        try:
            spec = QuerySpec.model_validate(body)
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return service.query(session_id, spec)
        except (QueryError, RpcFailure) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @api.get("/sessions/{session_id}/datasets")
    def datasets(session_id: str) -> list[DatasetMeta]:
        session_or_404(session_id)
        return service.datasets(session_id)

    @api.post("/sessions/{session_id}/restart")
    def restart(session_id: str) -> ReplayReport:
        session_or_404(session_id)
        return service.restart(session_id)

    # A step or a restart holds the session: new steps, restarts and data reads wait.
    @app.exception_handler(SessionBusy)
    async def session_busy(_request: Request, _exc: SessionBusy) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": "a step or restart is running"})

    # A dead kernel, or one that cannot start, on any route that touches it.
    @app.exception_handler(KernelDead)
    async def kernel_dead(_request: Request, exc: KernelDead) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": f"kernel is not running: {exc}"})

    app.include_router(api)
    if (static / "index.html").exists():
        app.mount("/", StaticFiles(directory=str(static), html=True), name="static")
    else:

        @app.get("/", response_class=PlainTextResponse)
        def root() -> str:
            return (
                "Quarry server is running. The web UI is not built yet; "
                "use the API with your bearer token."
            )

    return app
