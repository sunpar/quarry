"""Execute step code in a persistent namespace and track dataset lineage."""

from __future__ import annotations

import base64
import contextlib
import io
import time
import traceback
import weakref
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Final, Literal

import duckdb
import polars as pl
from pydantic import BaseModel, ConfigDict, Field

from quarry.kernel.datasets import (
    Column,
    Dataset,
    DatasetMeta,
    dataset_names,
    is_dataset,
    relation_frame,
    to_json_rows,
    undescribed,
)
from quarry.kernel.datasets import describe as describe_dataset
from quarry.kernel.lineage import CodeNames, analyze, dataset_reads, dataset_writes
from quarry.query.polars_target import to_polars
from quarry.query.spec import Json, QuerySpec
from quarry.query.sql_target import to_sql

TAIL_BYTES: Final = 4096
# Kernel-level exits and interrupts: a guard that turns failures into results lets these through.
_NOT_FAILURES: Final = (KeyboardInterrupt, SystemExit, GeneratorExit)
_NOTHING_STORED: Final = CodeNames(frozenset(), frozenset(), frozenset())

Status = Literal["ok", "error", "interrupted"]
# Whether a namespace value is still the object a dataset name was bound to before the step.
_IsSame = Callable[[object], bool]


class ExecError(BaseModel):
    type: str
    message: str
    traceback: str


class ExecResult(BaseModel):
    status: Status
    stdout_tail: str
    stderr_tail: str
    error: ExecError | None
    reads: list[str]
    writes: list[str]
    defines: list[str]
    datasets: list[DatasetMeta]
    duration_ms: int


class QueryResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    schema_: list[Column] = Field(alias="schema")
    rows: list[dict[str, Json]] | None
    arrow_base64: str | None
    row_count: int
    truncated: bool


class Executor:
    def __init__(
        self, namespace: dict[str, object], *, row_cap: int, tail_bytes: int = TAIL_BYTES
    ) -> None:
        self._ns = namespace
        self._row_cap = row_cap
        self._tail = tail_bytes
        self._defined: set[str] = set()
        self._running = False

    @property
    def running(self) -> bool:
        """True only while user code is inside `exec`, the one place an interrupt may land."""
        return self._running

    def execute(self, code: str) -> ExecResult:
        """Run `code` in the namespace; every failure, even describing a write, is a result."""
        started = time.monotonic()
        before = {name: _identity_check(self._ns[name]) for name in dataset_names(self._ns)}
        out, err = io.StringIO(), io.StringIO()
        status, error, names = self._exec(code, out, err)
        # On error or interrupt a store in the code may never have run, so only the namespace
        # itself can say what changed.
        stored = names if names is not None and status == "ok" else _NOTHING_STORED
        writes = _written(stored, before, self._ns)
        described = [self._describe_guarded(name) for name in writes]
        describe_errors = [e for _, e in described if e is not None]
        if status == "ok" and describe_errors:
            status, error = "error", describe_errors[0]
        defines = [] if names is None else sorted(n for n in names.defines if n in self._ns)
        reads = [] if names is None else dataset_reads(names, set(before), self._defined)
        self._defined.update(defines)
        return ExecResult(
            status=status,
            stdout_tail=out.getvalue()[-self._tail :],
            stderr_tail=err.getvalue()[-self._tail :],
            error=error,
            reads=reads,
            writes=writes,
            defines=defines,
            datasets=[meta for meta, _ in described],
            duration_ms=int((time.monotonic() - started) * 1000),
        )

    def describe(self, name: str) -> DatasetMeta:
        return describe_dataset(name, self._dataset(name), count_rows=True)

    def list_datasets(self) -> list[DatasetMeta]:
        """Every dataset; one that cannot be described carries an `error` instead of a schema."""
        return [self._describe_guarded(name)[0] for name in sorted(dataset_names(self._ns))]

    def query(self, spec: QuerySpec) -> QueryResult:
        """Run `spec`, returning at most `row_cap` rows; `truncated` when more rows exist."""
        obj = self._dataset(spec.dataset)
        frame = _run_query(spec.model_copy(update={"limit": self._capped(spec.limit)}), obj)
        truncated = frame.height > self._row_cap
        frame = frame.head(self._row_cap)
        arrow = spec.format == "arrow"
        return QueryResult(
            schema=[Column(name=n, dtype=str(t)) for n, t in frame.schema.items()],
            rows=None if arrow else to_json_rows(frame),
            arrow_base64=_arrow_base64(frame) if arrow else None,
            row_count=frame.height,
            truncated=truncated,
        )

    def snapshot(self, name: str, path: Path) -> DatasetMeta:
        frame = _materialize(self._dataset(name))
        path.parent.mkdir(parents=True, exist_ok=True)
        frame.write_parquet(path)
        return describe_dataset(name, frame, count_rows=True)

    def _exec(
        self, code: str, out: io.StringIO, err: io.StringIO
    ) -> tuple[Status, ExecError | None, CodeNames | None]:
        names: CodeNames | None = None
        try:
            names = analyze(code)
            compiled = compile(code, "<step>", "exec")
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self._running = True
                try:
                    exec(compiled, self._ns)  # executing researcher code is the kernel's job
                finally:
                    self._running = False
        except KeyboardInterrupt:
            return "interrupted", None, names
        # SystemExit included: a step calling exit() must not end the kernel.
        except BaseException as exc:
            return "error", _exec_error(exc), names
        return "ok", None, names

    def _describe_guarded(self, name: str) -> tuple[DatasetMeta, ExecError | None]:
        """Metadata for `name`; if describing fails, metadata carrying the error, and the error."""
        obj = self._dataset(name)
        try:
            return describe_dataset(name, obj, count_rows=False), None
        except _NOT_FAILURES:
            raise
        except BaseException as exc:  # polars panics are BaseException, not Exception
            error = _exec_error(exc)
            meta = undescribed(name, obj, error=f"{name}: {error.type}: {error.message}")
            return meta, error.model_copy(update={"message": f"{name}: {error.message}"})

    def _capped(self, limit: int | None) -> int:
        """`limit` when it is within the cap, else one row past it to detect truncation."""
        return limit if limit is not None and limit <= self._row_cap else self._row_cap + 1

    def _dataset(self, name: str) -> Dataset:
        obj = self._ns.get(name)
        if name.startswith("_") or not is_dataset(obj):
            raise KeyError(name)
        return obj


def _written(
    stored: CodeNames, before: Mapping[str, _IsSame], namespace: Mapping[str, object]
) -> list[str]:
    """Datasets the code stored, newly bound, or rebound to another object (a helper's `global`)."""
    after = dataset_names(namespace)
    rebound = {name for name in after & before.keys() if not before[name](namespace[name])}
    return sorted({*dataset_writes(stored, set(before), after), *rebound})


def _identity_check(obj: object) -> _IsSame:
    """A test for "is this still `obj`" that holds no strong reference to it.

    An id can be reused by a new object once `obj` is freed, which a weak reference cannot match;
    holding `obj` itself would keep every replaced dataset in memory until the step ends.
    """
    try:
        ref = weakref.ref(obj)
    except TypeError:  # the type refuses weak references: an id is the best that is left
        ident = id(obj)
        return lambda current: id(current) == ident
    return lambda current: ref() is current


def _run_query(spec: QuerySpec, obj: Dataset) -> pl.DataFrame:
    if not isinstance(obj, duckdb.DuckDBPyRelation):
        return to_polars(spec, obj).collect()
    if spec.pivot is None:
        return _relation_sql(spec, obj)
    # DuckDB plans PIVOT without an IN list as a MULTI statement, which `relation.query`
    # cannot run: the filters run as SQL and the pivot onward in polars, as `to_source` does.
    pre_pivot = spec.model_copy(
        update={"pivot": None, "sort": [], "limit": None, "offset": 0, "select": None}
    )
    pivoted = to_polars(spec.model_copy(update={"filters": []}), _relation_sql(pre_pivot, obj))
    return pivoted.collect()


def _relation_sql(spec: QuerySpec, rel: duckdb.DuckDBPyRelation) -> pl.DataFrame:
    # `to_source`'s view name: under the dataset's own name, a relation over a same-named
    # table would read itself.
    view = f"_quarry_{spec.dataset}"
    return relation_frame(rel.query(view, to_sql(spec, view, columns=rel.columns)))


def _materialize(obj: Dataset) -> pl.DataFrame:
    if isinstance(obj, pl.LazyFrame):
        return obj.collect()
    if isinstance(obj, duckdb.DuckDBPyRelation):
        return relation_frame(obj)
    return obj


def _arrow_base64(frame: pl.DataFrame) -> str:
    buffer = io.BytesIO()
    frame.write_ipc(buffer)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _exec_error(exc: BaseException) -> ExecError:
    # format_exception already survives a failing __str__ ("<exception str() failed>").
    trace = "".join(traceback.format_exception(exc))
    return ExecError(type=type(exc).__name__, message=_message(exc), traceback=trace)


def _message(exc: BaseException) -> str:
    try:
        return str(exc)
    except _NOT_FAILURES:
        raise
    except BaseException:  # user code's exception can fail in its own __str__
        return f"<unprintable {type(exc).__name__}>"
