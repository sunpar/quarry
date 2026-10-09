"""Execute step code in a persistent namespace and track dataset lineage."""

from __future__ import annotations

import base64
import contextlib
import io
import time
import traceback
import uuid
import weakref
from collections.abc import Callable, Mapping
from pathlib import Path
from types import FrameType
from typing import Final, Literal

import duckdb
import polars as pl
import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field

from quarry.errors import NOT_FAILURES, exception_message
from quarry.kernel.arrow import arrow_ipc
from quarry.kernel.datasets import (
    Column,
    Dataset,
    DatasetMeta,
    backing_of,
    dataset_names,
    importable_projection,
    importable_relation,
    is_dataset,
    relation_frame,
    to_json_rows,
    undescribed,
)
from quarry.kernel.datasets import describe as describe_dataset
from quarry.kernel.lineage import CodeNames, analyze, dataset_reads, dataset_writes
from quarry.query.polars_target import to_polars
from quarry.query.source_target import imported_names, to_source
from quarry.query.spec import Json, QueryError, QuerySpec
from quarry.query.sql_target import quote_ident, relation_view, split_for_relation, to_sql

TAIL_BYTES: Final = 4096
_NOTHING_STORED: Final = CodeNames(frozenset(), frozenset(), frozenset())

Status = Literal["ok", "error", "interrupted"]
# Whether a namespace value is still the object a name was bound to when the check was made.
_IsSame = Callable[[object], bool]


class ExecError(BaseModel):
    type: str
    message: str
    traceback: str

    @classmethod
    def from_exception(cls, exc: BaseException) -> ExecError:
        # format_exception already survives a failing __str__ ("<exception str() failed>").
        trace = "".join(traceback.format_exception(exc))
        return cls(type=type(exc).__name__, message=exception_message(exc), traceback=trace)


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


class ToCodeResult(BaseModel):
    code: str


class Executor:
    def __init__(
        self,
        namespace: dict[str, object],
        *,
        conn: duckdb.DuckDBPyConnection,
        row_cap: int,
        tail_bytes: int = TAIL_BYTES,
    ) -> None:
        """`conn` is the namespace's DuckDB connection, which an interrupt also stops."""
        self._ns = namespace
        self._conn = conn
        self._row_cap = row_cap
        self._tail = tail_bytes
        # Each helper an earlier step defined, with a test that its name still holds it.
        self._defined: dict[str, _IsSame] = {}
        # The metadata `execute` and `list_datasets` computed for each dataset since the last step.
        # Step code is what changes datasets, so each step clears it; a preview runs a plan or a
        # query, and the server lists on every prompt step.
        self._described: dict[str, DatasetMeta] = {}
        self._running = False
        self._interrupted = False  # whether the SIGINT handler interrupted the current step
        self._stopped = False

    @property
    def running(self) -> bool:
        """True only inside a step's `exec` or one describe of its writes: the guarded regions,
        the only places an interrupt may land."""
        return self._running

    @property
    def stopped(self) -> bool:
        return self._stopped

    def stop(self) -> None:
        """Interrupt every step from now on: the one running, found by a SIGINT sent after this,
        and each guarded region that starts after it (a step's exec, a describe of its writes),
        which ends as soon as it is running. A step about to start never runs."""
        self._stopped = True

    def _check_stopped(self) -> None:
        """Called in a guarded region, after `_running` is set: end it as an interrupt would."""
        if self._stopped:
            self._interrupted = True
            raise KeyboardInterrupt

    def on_sigint(self, signum: int, frame: FrameType | None) -> None:
        """The kernel's SIGINT handler: interrupt the step's guarded region, and record it.

        Anywhere else (idle, between a step's guarded regions, answering any other request) a
        KeyboardInterrupt would escape and end the kernel, so the signal is dropped there.
        """
        if self._running:
            self._interrupted = True
            # An interrupted `.pl()` returns while DuckDB's workers run on, holding up the next
            # query on the namespace's connection. With no query running, this changes nothing.
            self._conn.interrupt()
            raise KeyboardInterrupt

    def execute(self, code: str) -> ExecResult:
        """Run `code` in the namespace; every failure, even describing a write, is a result."""
        started = time.monotonic()
        self._interrupted = False
        # Whatever the step ends as, it may have changed any dataset, even in place
        # (`df.extend(...)`); the writes below are described after it, so they are current.
        self._described.clear()
        before = {name: _identity_check(self._ns[name]) for name in dataset_names(self._ns)}
        out, err = _TailWriter(self._tail), _TailWriter(self._tail)
        status, error, names, prior = self._exec(code, out, err)
        # On error or interrupt a store in the code may never have run, so only the namespace
        # itself can say what changed.
        stored = names if names is not None and status == "ok" else _NOTHING_STORED
        writes = _written(stored, before, self._ns)
        described = [self._describe_write(name) for name in writes]
        self._described.update({meta.name: meta for meta, _ in described if meta.error is None})
        describe_errors = [e for _, e in described if e is not None]
        if self._interrupted:
            # Whatever followed the interrupt: DuckDB raises its own RuntimeError for it, and a
            # step can catch it and finish.
            status, error = "interrupted", None
        elif status == "ok" and describe_errors:
            status, error = "error", describe_errors[0]
        defines = [] if names is None else _newly_bound(names.defines, prior, self._ns)
        # Helpers as they were when the step started, as `before` is for datasets.
        reads = [] if names is None else dataset_reads(names, set(before), set(self._defined))
        # A name rebound to anything else, or deleted, no longer holds the helper a later
        # step would read.
        self._defined = {
            name: same
            for name, same in self._defined.items()
            if name in self._ns and same(self._ns[name])
        }
        self._defined.update({name: _identity_check(self._ns[name]) for name in defines})
        return ExecResult(
            status=status,
            stdout_tail=out.getvalue(),
            stderr_tail=err.getvalue(),
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
        """Every dataset; one that cannot be described carries an `error` instead of a schema.

        A dataset is described once between steps; a failed description is not kept.
        """
        metas: list[DatasetMeta] = []
        for name in sorted(dataset_names(self._ns)):
            meta = self._described.get(name)
            if meta is None:
                meta = self._describe_guarded(name)[0]
                if meta.error is None:
                    self._described[name] = meta
            metas.append(meta)
        return metas

    def query(self, spec: QuerySpec) -> QueryResult:
        """Run `spec`, returning at most `row_cap` rows; `truncated` when more rows exist."""
        obj = self._dataset(spec.dataset)
        capped = spec.model_copy(update={"limit": self._capped(spec.limit)})
        frame = _run_query(capped, obj, self._conn)
        truncated = frame.height > self._row_cap
        frame = frame.head(self._row_cap)
        arrow = spec.format == "arrow"
        # The rows come from json.loads, so validating them would only walk every value again.
        return QueryResult.model_construct(
            schema_=[Column(name=n, dtype=str(t)) for n, t in frame.schema.items()],
            rows=None if arrow else to_json_rows(frame),
            arrow_base64=_arrow_base64(frame) if arrow else None,
            row_count=frame.height,
            truncated=truncated,
        )

    def to_code(self, specs: list[QuerySpec]) -> ToCodeResult:
        """Each spec as Python assigning `<dataset>_<n>` (`_result_names`), rendered with the
        live schema; QueryError when a generated import would rebind a dataset."""
        blocks: list[str] = []
        imported: set[str] = set()
        for spec, result_name in zip(specs, _result_names(specs, self._ns), strict=True):
            obj = self._dataset(spec.dataset)
            projection = None
            if isinstance(obj, duckdb.DuckDBPyRelation):
                projection = importable_projection(obj)
                schema = relation_frame(obj, 0).schema
            elif isinstance(obj, pl.LazyFrame):
                schema = obj.collect_schema()
            else:
                schema = obj.schema
            backing = backing_of(obj)
            blocks.append(
                to_source(
                    spec,
                    backing,
                    result_name=result_name,
                    schema=schema,
                    relation_projection=projection,
                )
            )
            imported.update(imported_names(spec, backing, schema=schema))
        # An import binds its name for every later block and in the namespace the code runs in.
        # Every spec's dataset is among these: `_dataset` found each one.
        shadowed = sorted(imported & dataset_names(self._ns))
        if shadowed:
            message = f"dataset {shadowed[0]!r} would be shadowed by a generated import; rename it"
            raise QueryError(message, dataset=shadowed[0])
        return ToCodeResult(code="\n".join(blocks))

    def snapshot(self, name: str, path: Path) -> DatasetMeta:
        """Stream `name` to parquet at `path`, which then holds all of it or what it held before.

        The metadata describes the written file, under the backing of the dataset it came from.
        """
        obj = self._dataset(name)
        path.parent.mkdir(parents=True, exist_ok=True)
        # Beside `path`, so the rename stays on one filesystem; not *.parquet, so no glob reads it.
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        try:
            _write_parquet(obj, temp)
            temp.replace(path)
        finally:
            temp.unlink(missing_ok=True)  # gone already once the rename succeeded
        # Not a glob: `prices[2024].parquet` names one file.
        meta = describe_dataset(name, pl.scan_parquet(path, glob=False), count_rows=True)
        return meta.model_copy(update={"backing": backing_of(obj)})

    def _exec(
        self, code: str, out: _TailWriter, err: _TailWriter
    ) -> tuple[Status, ExecError | None, CodeNames | None, dict[str, _IsSame]]:
        """Run `code`; also its names, once it parses, and what the names it defines held."""
        names: CodeNames | None = None
        prior: dict[str, _IsSame] = {}
        try:
            names = analyze(code)
            compiled = compile(code, "<step>", "exec")
            # A def that never ran leaves its name as it was, which only identity can tell.
            prior = {n: _identity_check(self._ns[n]) for n in names.defines if n in self._ns}
            with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                self._running = True
                try:
                    self._check_stopped()  # a SIGINT that missed this step came after `stop`
                    exec(compiled, self._ns)  # executing researcher code is the kernel's job
                finally:
                    self._running = False
        except KeyboardInterrupt:
            return "interrupted", None, names, prior
        # SystemExit included: a step calling exit() must not end the kernel.
        except BaseException as exc:
            return "error", ExecError.from_exception(exc), names, prior
        return "ok", None, names, prior

    def _describe_write(self, name: str) -> tuple[DatasetMeta, ExecError | None]:
        """`_describe_guarded`, open to the step's interrupt; once the step is interrupted, its
        writes are left undescribed."""
        if not self._interrupted:
            with contextlib.suppress(KeyboardInterrupt):
                # Inline, not a context manager: entering its `__exit__` would run a pending
                # signal's handler with the flag still set, outside this try.
                self._running = True
                try:
                    self._check_stopped()
                    described = self._describe_guarded(name)
                finally:
                    self._running = False
                if not self._interrupted:  # DuckDB turns the interrupt into its own error
                    return described
        return undescribed(name, self._dataset(name), error="interrupted"), None

    def _describe_guarded(self, name: str) -> tuple[DatasetMeta, ExecError | None]:
        """Metadata for `name`; if describing fails, metadata carrying the error, and the error."""
        obj = self._dataset(name)
        try:
            return describe_dataset(name, obj, count_rows=False), None
        except NOT_FAILURES:
            raise
        except BaseException as exc:  # polars panics are BaseException, not Exception
            error = ExecError.from_exception(exc)
            meta = undescribed(name, obj, error=f"{error.type}: {error.message}")
            return meta, error.model_copy(update={"message": f"{name}: {error.message}"})

    def _capped(self, limit: int | None) -> int:
        """`limit` when it is within the cap, else one row past it to detect truncation."""
        return limit if limit is not None and limit <= self._row_cap else self._row_cap + 1

    def _dataset(self, name: str) -> Dataset:
        obj = self._ns.get(name)
        if not is_dataset(obj):
            raise KeyError(name)
        return obj


class _TailWriter(io.TextIOBase):
    """A text stream that keeps only the last `limit` characters written to it.

    A step can print without end, and all of it but the tail would be thrown away anyway.
    """

    def __init__(self, limit: int) -> None:
        super().__init__()
        self._limit = limit
        self._chunks: list[str] = []
        self._held = 0

    def writable(self) -> bool:
        return True

    def write(self, s: str, /) -> int:
        if s:  # an empty chunk would never count toward a trim
            self._chunks.append(s)
            self._held += len(s)
            # Trimming only past twice the limit copies each character a bounded number of
            # times, however small the writes.
            if self._held > 2 * self._limit:
                tail = self.getvalue()
                self._chunks, self._held = [tail], len(tail)
        return len(s)

    def getvalue(self) -> str:
        text = "".join(self._chunks)
        return text[max(len(text) - self._limit, 0) :]


def _written(
    stored: CodeNames, before: Mapping[str, _IsSame], namespace: Mapping[str, object]
) -> list[str]:
    """Datasets the code stored, newly bound, or rebound to another object (a helper's `global`)."""
    after = dataset_names(namespace)
    rebound = {name for name in after & before.keys() if not before[name](namespace[name])}
    return sorted({*dataset_writes(stored, set(before), after), *rebound})


def _newly_bound(
    names: frozenset[str], prior: Mapping[str, _IsSame], namespace: Mapping[str, object]
) -> list[str]:
    """`names` the step bound: new to the namespace, or holding another object than before."""
    return sorted(
        n for n in names if n in namespace and not (n in prior and prior[n](namespace[n]))
    )


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


def _result_names(specs: list[QuerySpec], namespace: Mapping[str, object]) -> list[str]:
    """`<dataset>_<n>` for the nth spec, its suffix raised past every name the namespace binds,
    any spec reads, or an earlier spec was given, so no block overwrites what another reads."""
    taken = {spec.dataset for spec in specs}
    names: list[str] = []
    for n, spec in enumerate(specs, start=1):
        suffix = n
        while (name := f"{spec.dataset}_{suffix}") in taken or name in namespace:
            suffix += 1
        taken.add(name)
        names.append(name)
    return names


def _run_query(spec: QuerySpec, obj: Dataset, conn: duckdb.DuckDBPyConnection) -> pl.DataFrame:
    if not isinstance(obj, duckdb.DuckDBPyRelation):
        return to_polars(spec, obj).collect()
    # As describe reports it, so the spec's filters, sorts and aggs see the types it advertises
    # (an INTERVAL is text), and a repeated `a` is `a` and `a_1`, which SQL can tell apart.
    rel = importable_relation(obj)
    sql_part, polars_part = split_for_relation(spec)
    # Unique per query: `query` replaces a temp view of its name, and the drop below removes
    # it, so a fixed name could destroy a view the researcher made under it.
    view = f"{relation_view(spec.dataset)}_{uuid.uuid4().hex[:8]}"
    sql = to_sql(sql_part, view, columns=rel.columns)
    try:
        frame = relation_frame(rel.query(view, sql))
    finally:
        # `query` registers the view on the relation's connection, where it would pin the
        # relation's data for the kernel's lifetime.
        drop = f"DROP VIEW {quote_ident(view)}"
        try:
            conn.execute(drop)
        except duckdb.CatalogException:
            # The relation came from another connection, which only its own `query` reaches;
            # that re-binds the relation first (re-globbing a read_parquet), so it comes last.
            obj.query(view, drop)
    return frame if polars_part is None else to_polars(polars_part, frame).collect()


def _write_parquet(obj: Dataset, path: Path) -> None:
    if isinstance(obj, pl.DataFrame):
        obj.write_parquet(path)
    elif isinstance(obj, pl.LazyFrame):
        obj.sink_parquet(path)
    else:
        # Through Arrow, batch by batch, as `.pl()` converts: DuckDB's own write_parquet stores
        # other types than describe and query report (HUGEINT as a double, UUID as bytes).
        reader = importable_relation(obj).to_arrow_reader()
        with pq.ParquetWriter(path, reader.schema, compression="zstd") as writer:
            for batch in reader:
                writer.write_batch(batch)


def _arrow_base64(frame: pl.DataFrame) -> str:
    return base64.b64encode(arrow_ipc(frame)).decode("ascii")
