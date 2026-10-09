"""The five tools the agent can call, executed against one session's kernel."""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Annotated, Any, Final

from pydantic import BaseModel, BeforeValidator, Field, ValidationError

from quarry.agent.transpile import Transpiler
from quarry.agent.types import ToolCall, ToolDef, ToolResult
from quarry.components.library import ComponentLibrary
from quarry.kernel.client import KernelClient, RpcFailure
from quarry.kernel.executor import ExecResult, Status
from quarry.query.spec import Json

RUN_PYTHON: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {
        "code": {
            "type": "string",
            "description": (
                "Python to execute in the session kernel. polars is `pl`, duckdb is `duckdb`, "
                "loaders under `loaders.*`, `sql(query)`, `pq(glob)`, `sql_local(query)`. Assign "
                "results to well-named top-level variables; every top-level DataFrame, LazyFrame "
                "or DuckDB relation becomes a dataset."
            ),
        }
    },
    "required": ["code"],
}
DESCRIBE_DATASET: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {"name": {"type": "string"}},
    "required": ["name"],
}
SEARCH_COMPONENTS: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {
        "dataset": {
            "type": "string",
            "description": (
                "Dataset the component should render; filters by schema compatibility. "
                "An empty string searches without a dataset."
            ),
        },
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["dataset", "tags"],
}
INITIAL_STATE: Final[dict[str, Json]] = {
    "type": "string",
    "description": 'JSON object encoded as a string, e.g. "{}"',
}
RENDER_VIEW: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {
        "component_id": {"type": "string"},
        "datasets": {"type": "array", "items": {"type": "string"}},
        "initial_state": INITIAL_STATE,
    },
    "required": ["component_id", "datasets", "initial_state"],
}
WRITE_VIEW: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {
        "source": {
            "type": "string",
            "description": (
                "A TSX module whose default export is the component. Only `react`, the design "
                "system, the chart libraries listed in the guide, and the hooks module may be "
                "imported."
            ),
        },
        "datasets": {"type": "array", "items": {"type": "string"}},
        "initial_state": INITIAL_STATE,
    },
    "required": ["source", "datasets", "initial_state"],
}

TOOL_DEFS: Final[list[ToolDef]] = [
    ToolDef(
        name="run_python",
        description="Execute Python in the session kernel and register any datasets it assigns.",
        input_schema=RUN_PYTHON,
    ),
    ToolDef(
        name="describe_dataset",
        description="Schema, row count and preview of a dataset.",
        input_schema=DESCRIBE_DATASET,
    ),
    ToolDef(
        name="search_components",
        description="Find library components compatible with a dataset, ranked by tags.",
        input_schema=SEARCH_COMPONENTS,
    ),
    ToolDef(
        name="render_view",
        description="Mount a library component against named datasets.",
        input_schema=RENDER_VIEW,
    ),
    ToolDef(
        name="write_view",
        description="Mount a new TSX component you wrote against named datasets.",
        input_schema=WRITE_VIEW,
    ),
]


class PendingView(BaseModel):
    component_id: str
    source: str
    initial_state: dict[str, Json] = Field(default_factory=dict)
    datasets: list[str] = Field(default_factory=list)


class CodeRun(BaseModel):
    """One execution of code in the kernel, kept so restart can replay it as its own unit."""

    code: str
    status: Status


class _RunPython(BaseModel):
    code: str


class _Describe(BaseModel):
    name: str


class _Search(BaseModel):
    dataset: str
    tags: list[str] = Field(default_factory=list)


def _parse_state(value: object) -> dict[str, Json]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str):
        raise ValueError("initial_state must be a JSON object string")
    parsed = json.loads(value or "{}")
    if not isinstance(parsed, dict):
        raise ValueError("initial_state must encode a JSON object")
    return parsed


StateJson = Annotated[dict[str, Json], BeforeValidator(_parse_state)]


class _Render(BaseModel):
    component_id: str
    datasets: list[str]
    initial_state: StateJson = Field(default_factory=dict)


class _Write(BaseModel):
    source: str
    datasets: list[str]
    initial_state: StateJson = Field(default_factory=dict)


class ToolExecutor:
    def __init__(
        self, *, kernel: KernelClient, library: ComponentLibrary, transpiler: Transpiler
    ) -> None:
        self._kernel = kernel
        self._library = library
        self._transpiler = transpiler
        self.view: PendingView | None = None
        # Each run_python call that executed: its code and the kernel's result.
        self.runs: list[tuple[str, ExecResult]] = []
        self._routes: dict[str, tuple[type[BaseModel], Callable[[ToolCall, Any], ToolResult]]] = {
            "run_python": (_RunPython, self._run_python),
            "describe_dataset": (_Describe, self._describe),
            "search_components": (_Search, self._search),
            "render_view": (_Render, self._render),
            "write_view": (_Write, self._write),
        }

    def run(self, call: ToolCall) -> ToolResult:
        route = self._routes.get(call.name)
        if route is None:
            return _error(call, f"unknown tool {call.name!r}")
        model, handler = route
        try:
            args = model.model_validate(call.input)
        except ValidationError as exc:
            return _error(call, f"invalid arguments: {exc}")
        return handler(call, args)

    def _run_python(self, call: ToolCall, args: _RunPython) -> ToolResult:
        result = self._kernel.execute(args.code)
        failed = result.status != "ok"
        self.runs.append((args.code, result))
        content = result.model_dump(by_alias=True, mode="json")
        return ToolResult(call_id=call.id, content=json.dumps(content), is_error=failed)

    def _describe(self, call: ToolCall, args: _Describe) -> ToolResult:
        try:
            meta = self._kernel.describe(args.name)
        except RpcFailure as exc:
            return _error(call, str(exc))
        return ToolResult(call_id=call.id, content=meta.model_dump_json(by_alias=True))

    def _search(self, call: ToolCall, args: _Search) -> ToolResult:
        meta = None
        if args.dataset:
            # Listed metadata has the schema without a row count, which can scan everything.
            listed = {m.name: m for m in self._kernel.list_datasets()}
            meta = listed.get(args.dataset)
            if meta is None:
                return _error(call, f"no dataset {args.dataset!r}")
        found = self._library.search(dataset=meta, tags=args.tags)
        return ToolResult(
            call_id=call.id, content=json.dumps([m.model_dump(by_alias=True) for m in found])
        )

    def _render(self, call: ToolCall, args: _Render) -> ToolResult:
        entry = self._library.get(args.component_id)
        if entry is None:
            return _error(call, f"no component {args.component_id!r}")
        source = entry.source_path.read_text()
        return self._mount(call, args.component_id, source, args.datasets, args.initial_state)

    def _write(self, call: ToolCall, args: _Write) -> ToolResult:
        return self._mount(call, "inline", args.source, args.datasets, args.initial_state)

    def _mount(
        self,
        call: ToolCall,
        component_id: str,
        source: str,
        datasets: list[str],
        initial_state: dict[str, Json],
    ) -> ToolResult:
        missing = self._missing_datasets(datasets)
        if missing:
            return _error(call, f"unknown datasets: {missing}")
        problem = self._transpiler.check(source)
        if problem is not None:
            return _error(call, f"transpile error: {problem}")
        self.view = PendingView(
            component_id=component_id,
            source=source,
            initial_state=initial_state,
            datasets=datasets,
        )
        return ToolResult(call_id=call.id, content=json.dumps({"mounted": component_id}))

    def _missing_datasets(self, names: list[str]) -> list[str]:
        known = {m.name for m in self._kernel.list_datasets()}
        return [n for n in names if n not in known]


def _error(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(call_id=call.id, content=json.dumps({"error": message}), is_error=True)
