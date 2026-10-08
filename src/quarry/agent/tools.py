"""The five tools the agent can call, executed against one session's kernel."""

from __future__ import annotations

import json
from typing import Final

from pydantic import BaseModel, Field, ValidationError, field_validator

from quarry.agent.transpile import Transpiler
from quarry.agent.types import ToolCall, ToolDef, ToolResult
from quarry.components.library import ComponentLibrary
from quarry.kernel.client import KernelClient, RpcFailure
from quarry.kernel.executor import ExecResult
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
            "description": "Dataset the component should render; filters by schema compatibility.",
        },
        "tags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["dataset", "tags"],
}
RENDER_VIEW: Final[dict[str, Json]] = {
    "type": "object",
    "properties": {
        "component_id": {"type": "string"},
        "datasets": {"type": "array", "items": {"type": "string"}},
        "initial_state": {
            "type": "string",
            "description": 'JSON object encoded as a string, e.g. "{}"',
        },
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
        "initial_state": {
            "type": "string",
            "description": 'JSON object encoded as a string, e.g. "{}"',
        },
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


class _Render(BaseModel):
    component_id: str
    datasets: list[str]
    initial_state: dict[str, Json] = Field(default_factory=dict)

    @field_validator("initial_state", mode="before")
    @classmethod
    def _state(cls, value: object) -> dict[str, Json]:
        return _parse_state(value)


class _Write(BaseModel):
    source: str
    datasets: list[str]
    initial_state: dict[str, Json] = Field(default_factory=dict)

    @field_validator("initial_state", mode="before")
    @classmethod
    def _state(cls, value: object) -> dict[str, Json]:
        return _parse_state(value)


class ToolExecutor:
    def __init__(
        self, *, kernel: KernelClient, library: ComponentLibrary, transpiler: Transpiler
    ) -> None:
        self._kernel = kernel
        self._library = library
        self._transpiler = transpiler
        self.view: PendingView | None = None
        self.last_python_failed = False
        self.exec_results: list[ExecResult] = []

    def run(self, call: ToolCall) -> ToolResult:
        try:
            match call.name:
                case "run_python":
                    return self._run_python(call, _RunPython.model_validate(call.input))
                case "describe_dataset":
                    return self._describe(call, _Describe.model_validate(call.input))
                case "search_components":
                    return self._search(call, _Search.model_validate(call.input))
                case "render_view":
                    return self._render(call, _Render.model_validate(call.input))
                case "write_view":
                    return self._write(call, _Write.model_validate(call.input))
                case _:
                    return _error(call, f"unknown tool {call.name!r}")
        except ValidationError as exc:
            return _error(call, f"invalid arguments: {exc}")

    def _run_python(self, call: ToolCall, args: _RunPython) -> ToolResult:
        result = self._kernel.execute(args.code)
        self.exec_results.append(result)
        self.last_python_failed = result.status != "ok"
        content = result.model_dump(by_alias=True, mode="json")
        return ToolResult(
            call_id=call.id, content=json.dumps(content), is_error=result.status != "ok"
        )

    def _describe(self, call: ToolCall, args: _Describe) -> ToolResult:
        try:
            meta = self._kernel.describe(args.name)
        except RpcFailure as exc:
            return _error(call, str(exc))
        return ToolResult(call_id=call.id, content=meta.model_dump_json(by_alias=True))

    def _search(self, call: ToolCall, args: _Search) -> ToolResult:
        try:
            meta = self._kernel.describe(args.dataset)
        except RpcFailure as exc:
            return _error(call, str(exc))
        found = self._library.search(dataset=meta, tags=args.tags)
        return ToolResult(
            call_id=call.id, content=json.dumps([m.model_dump(by_alias=True) for m in found])
        )

    def _render(self, call: ToolCall, args: _Render) -> ToolResult:
        entry = self._library.get(args.component_id)
        if entry is None:
            return _error(call, f"no component {args.component_id!r}")
        missing = self._missing_datasets(args.datasets)
        if missing:
            return _error(call, f"unknown datasets: {missing}")
        self.view = PendingView(
            component_id=args.component_id,
            source=entry.source_path.read_text(),
            initial_state=args.initial_state,
            datasets=args.datasets,
        )
        return ToolResult(call_id=call.id, content=json.dumps({"mounted": args.component_id}))

    def _write(self, call: ToolCall, args: _Write) -> ToolResult:
        missing = self._missing_datasets(args.datasets)
        if missing:
            return _error(call, f"unknown datasets: {missing}")
        problem = self._transpiler.check(args.source)
        if problem is not None:
            return _error(call, f"transpile error: {problem}")
        self.view = PendingView(
            component_id="inline",
            source=args.source,
            initial_state=args.initial_state,
            datasets=args.datasets,
        )
        return ToolResult(call_id=call.id, content=json.dumps({"mounted": "inline"}))

    def _missing_datasets(self, names: list[str]) -> list[str]:
        known = {m.name for m in self._kernel.list_datasets()}
        return [n for n in names if n not in known]


def _error(call: ToolCall, message: str) -> ToolResult:
    return ToolResult(call_id=call.id, content=json.dumps({"error": message}), is_error=True)
