import duckdb
import polars as pl
import pytest

from quarry.kernel.datasets import DatasetMeta
from quarry.kernel.executor import Executor
from quarry.kernel.protocol import (
    Request,
    Response,
    RpcError,
    decode_request,
    decode_response,
    encode,
)
from quarry.kernel.service import KernelService


def service() -> KernelService:
    return KernelService(Executor({"pl": pl, "duckdb": duckdb}, conn=duckdb.connect(), row_cap=10))


class FakePanic(BaseException):
    """Stands in for pyo3's PanicException, which is a BaseException but not an Exception."""


class Unprintable(Exception):
    def __str__(self) -> str:
        raise RuntimeError("no message")


class RaisingExecutor(Executor):
    """An executor whose `describe` raises `exc`."""

    def __init__(self, exc: BaseException) -> None:
        super().__init__({}, conn=duckdb.connect(), row_cap=10)
        self._exc = exc

    def describe(self, name: str) -> DatasetMeta:
        raise self._exc


def test_encode_decode_round_trip() -> None:
    req = Request(id=1, method="execute", params={"code": "x = 1"})
    assert decode_request(encode(req)) == req
    resp = Response(id=1, result={"ok": True})
    assert decode_response(encode(resp)) == resp
    assert encode(req).endswith(b"\n")


def test_encode_replaces_lone_surrogates() -> None:
    line = encode(Response(id=1, result="a\udcffb"))
    assert line.endswith(b"\n")
    assert decode_response(line).result == "a?b"


def test_execute_dispatch() -> None:
    resp = service().handle(
        Request(id=1, method="execute", params={"code": "df = pl.DataFrame({'a': [1]})"})
    )
    assert resp.error is None
    assert isinstance(resp.result, dict)
    assert resp.result["writes"] == ["df"]


def test_describe_unknown_is_error_response() -> None:
    resp = service().handle(Request(id=2, method="describe", params={"name": "nope"}))
    assert resp.error is not None
    assert resp.error.type == "KeyError"


def test_unknown_method() -> None:
    resp = service().handle(Request(id=3, method="fly", params={}))
    assert resp.error is not None
    assert resp.error.type == "UnknownMethod"


def test_query_validation_error() -> None:
    svc = service()
    svc.handle(Request(id=1, method="execute", params={"code": "df = pl.DataFrame({'a': [1]})"}))
    resp = svc.handle(Request(id=2, method="query", params={"spec": {"dataset": "df", "limit": 0}}))
    assert resp.error is not None
    assert resp.error.type == "ValidationError"


@pytest.mark.parametrize("method", ["execute", "describe", "query", "snapshot"])
def test_missing_params_is_error_not_crash(method: str) -> None:
    resp = service().handle(Request(id=9, method=method, params={}))
    assert resp.error is not None


def test_polars_compute_error_is_error_response() -> None:
    svc = service()
    svc.handle(Request(id=1, method="execute", params={"code": "df = pl.DataFrame({'a': [1]})"}))
    spec = {"dataset": "df", "filters": [{"col": "a", "op": "contains", "value": "x"}]}
    resp = svc.handle(Request(id=2, method="query", params={"spec": spec}))
    assert resp.result is None
    assert resp.error is not None
    assert resp.error.type == "InvalidOperationError"


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (FakePanic("polars panicked"), RpcError(type="FakePanic", message="polars panicked")),
        (Unprintable(), RpcError(type="Unprintable", message="<unprintable Unprintable>")),
    ],
)
def test_any_failure_is_error_response(exc: BaseException, expected: RpcError) -> None:
    resp = KernelService(RaisingExecutor(exc)).handle(
        Request(id=4, method="describe", params={"name": "df"})
    )
    assert resp == Response(id=4, error=expected)


@pytest.mark.parametrize("exc", [KeyboardInterrupt(), SystemExit(0), GeneratorExit()])
def test_kernel_exits_and_interrupts_are_not_swallowed(exc: BaseException) -> None:
    with pytest.raises(type(exc)):
        KernelService(RaisingExecutor(exc)).handle(
            Request(id=5, method="describe", params={"name": "df"})
        )
