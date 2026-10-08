"""Dispatch kernel RPC requests to the executor; every failure becomes an error response."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel

from quarry.kernel.executor import NOT_FAILURES, Executor, exception_message
from quarry.kernel.protocol import Request, Response, RpcError
from quarry.query.spec import Json, QuerySpec


class UnknownMethod(Exception):
    """The request names a method the kernel does not have."""


class KernelService:
    def __init__(self, executor: Executor) -> None:
        self._executor = executor

    def handle(self, request: Request) -> Response:
        """The response to `request`; every failure, a polars panic included, is an error."""
        try:
            result = _jsonable(self._dispatch(request.method, request.params))
            # Already JSON from model_dump; validating it again walks every row of a result.
            return Response.model_construct(id=request.id, result=result)
        except NOT_FAILURES:
            raise
        # Unknown methods, KeyError, QueryError, ValidationError, polars and DuckDB errors,
        # and pyo3's PanicException, which is a BaseException but not an Exception.
        except BaseException as exc:
            error = RpcError(type=type(exc).__name__, message=exception_message(exc))
            return Response(id=request.id, error=error)

    def _dispatch(
        self, method: str, params: dict[str, Json]
    ) -> BaseModel | Sequence[BaseModel] | None:
        match method:
            case "execute":
                return self._executor.execute(_text(params, "code"))
            case "describe":
                return self._executor.describe(_text(params, "name"))
            case "list_datasets":
                return self._executor.list_datasets()
            case "query":
                return self._executor.query(QuerySpec.model_validate(params.get("spec")))
            case "snapshot":
                return self._executor.snapshot(_text(params, "name"), Path(_text(params, "path")))
            case "shutdown":
                return None
            case _:
                raise UnknownMethod(method)


def _text(params: dict[str, Json], key: str) -> str:
    value = params.get(key)
    if not isinstance(value, str):
        raise TypeError(f"param {key!r} must be a string")
    return value


def _jsonable(value: BaseModel | Sequence[BaseModel] | None) -> Json:
    if value is None:
        return None
    if isinstance(value, BaseModel):
        dumped: Json = value.model_dump(by_alias=True, mode="json")
        return dumped
    return [item.model_dump(by_alias=True, mode="json") for item in value]
