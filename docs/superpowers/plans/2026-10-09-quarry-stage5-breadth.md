# Quarry Stage 5: Breadth Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Finish the spec's breadth: the remaining seven built-in components, Perspective over Arrow, "to code" for any view, saving generated components into the researcher's library, notebook and script export with CLI project commands, the opt-in licensed chart libraries, and the lineage, query-source and status gaps deferred from Stages 1 to 4.

**Architecture:** The kernel gains two small pure pieces: an Arrow transport that casts a frame to the types Perspective reads, and a `to_code` RPC that renders query specs with `to_source` against the live schema. The server gains four route groups (to-code, components, export, libraries) and serves locally installed Highcharts and SciChart packages under `/libs/` with the static CORS header Stage 3 added. The runtime's import allowlist grows to the full spec table; Plotly, ECharts, Recharts, TanStack Table and d3 are bundled chunks, Perspective is wrapped in `@quarry/perspective` (its config maps to a query spec, lossily and deterministically), and the two licensed libraries load from `/libs/` only when the server reports them enabled. Export is a hand-built nbformat 4 document validated by `nbformat` in tests. Everything new is reachable from the host: a "To code" drawer that becomes a manual step, a "Save to library" dialog, export and recipe downloads.

**Tech Stack:** Python 3.11+, polars 2, DuckDB 1.5.6, pyarrow 25, pydantic 2, FastAPI, the Stage 1 to 4 code as merged; `nbformat` 5.11 as a dev dependency (validation only). Web: the Stage 3 Vite 8 / React 19 / TypeScript 6 project plus `plotly.js-dist-min` 4.1.2, `react-plotly.js` 4.1.0, `echarts` 6.1.0, `echarts-for-react` 3.0.6, `recharts` 3.10.1, `@tanstack/react-table` 9.2.8, `d3` 7.9.0 + `@types/d3` 7.4, `@types/plotly.js` 3.0, `@types/react-plotly.js` 2.6, `@finos/perspective`, `@finos/perspective-viewer`, `@finos/perspective-viewer-datagrid`, `@finos/perspective-viewer-d3fc` 3.8.0. Highcharts 13.1 and SciChart 6.0 are never in `package.json`; they come from the researcher's own installs.

**Spec:** `docs/superpowers/specs/2026-10-08-quarry-design.md` (sections 3 Decisions, 5 Component, 8 Tools and Library guide, 9 Iframe runtime / Bridge / Hooks / Built-in components / To code, 10 Export, 11 Config, 12 Security, 14 Testing, 15 stage 5). The Stage 5 and "Any time" items in `docs/open-items.md`, and the Stage 4 deferrals (lineage through SQL strings, attribute mutation, `SessionStatus.busy`), are addressed or explicitly deferred in "Open items" at the end.

## Global Constraints

- All earlier Global Constraints still apply: typed Python with built-in generics, ruff format and check, mypy strict; TypeScript strict, no `any`, `interface` for props, no `React.FC`, files under 250 lines, prettier on every file; bare Conventional Commit types, no scopes, no attribution trailers.
- Base branch is the Stage 4 branch (or `main` once it is merged). Every "Consumes" line names Stage 3 and 4 code as planned; before each host task, re-read the real files and let code win over this plan's TypeScript.
- Spec section 9 and 12 amendment, made in Task 2: the runtime CSP is `default-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; worker-src blob:; style-src 'self' 'unsafe-inline'; img-src data: blob:; font-src 'self'; connect-src 'self'`. "No network" now reads: no network beyond the Quarry server's own static files. API routes need the bearer token, which the frame never holds, so `connect-src 'self'` opens nothing the bridge did not already mediate. Only the sandboxed frame's own bundle, `/libs/` and wasm files get `Access-Control-Allow-Origin: *`; API routes never do.
- The licensed libraries are never bundled, never in `web/package.json`, and never advertised unless both the license key and the install path are configured and the path exists. A key without a path logs one warning at startup and leaves the library disabled.
- `format: "arrow"` results are Arrow IPC **stream** bytes (not file), written at `pl.CompatLevel.oldest()` after the casts in Task 1. Anything JSON rows render exactly (Decimal strings, big integers) may lose precision in Arrow; Arrow is a display transport for Perspective, not the source of truth.
- "To code" renders with the dataset's live schema from the kernel (`to_source(..., schema=)`), so literals coerce as `to_polars` coerces them. Export renders saved queries without a schema (only dtype strings are on disk) and says so in a comment line.
- Every query spec that reaches `to_source` with a bad identifier, a non-ASCII-NFKC name, or a malformed value raises `QueryError`, never `ValueError` or `TypeError`.
- Perspective to query spec is lossy by design: expressions, column sorts, `ends with`, more than one `split_by`, and any aggregate without a `QuerySpec` equivalent are dropped and listed in the view state under `dropped`, so "to code" can say what it left out. Recorded as a decision in Task 9.
- A generated component is saved under `<root>/components/<id>/` with `origin: "generated"`; an id that any library root already holds is refused with 409. Ids match `^[a-z0-9][a-z0-9-]{0,63}$`.
- Stage 5 may ship as two pull requests: Tasks 1 to 7 (kernel, server, CLI, plus Task 2's runtime CSP and Perspective proof, which the server half needs to validate its Arrow transport) and Tasks 8 to 13 (the rest of the runtime, built-ins and host). Each half must leave `main` green.

## Review Focus

1. Perspective mounts inside the `sandbox="allow-scripts"` frame with the amended CSP: its engine worker (a Blob URL module worker) starts, both wasm files load, and a table shows rows. Pinned by the Playwright test in Task 2.
2. A polars frame with String, Date, Datetime (zoned and naive), Decimal, Categorical, Duration and List columns loads in Perspective without an error. Pinned in Task 1 (the cast table) and the Task 2 Playwright test (the viewer reports the row count).
3. "To code" on a DuckDB relation whose result has an INTERVAL column produces Python that runs. Pinned in Task 3 (`relation_projection` test executes the generated source).
4. An exported notebook validates against nbformat 4 and its code cells run top to bottom in a fresh namespace. Pinned in Task 6.
5. SciChart configured with a license key but no install path stays disabled: not mounted, not advertised to the agent, not in `GET /libraries` as enabled, one warning logged. Pinned in Task 7. Saving a component whose id collides with a built-in is refused with 409 and writes nothing. Pinned in Task 5.

---

### Task 1: Arrow transport the viewer can read

**Files:**

- Create: `src/quarry/kernel/arrow.py`
- Modify: `src/quarry/kernel/executor.py` (replace `_arrow_base64`), `tests/kernel/test_executor.py` (two tests read a stream now)
- Test: `tests/kernel/test_arrow.py`

**Interfaces:**

- Produces: `for_viewer(frame: pl.DataFrame) -> pl.DataFrame` (casts), `arrow_ipc(frame: pl.DataFrame) -> bytes` (IPC stream at `CompatLevel.oldest()`, `large_string` narrowed to `string`).
- Consumes: `Executor.query` (`executor.py:164`), `_arrow_base64` (`executor.py:365`).

Perspective's Arrow reader takes the primitive types, `string`, `date32`, `timestamp` (any unit, zoned or not), `bool`, and dictionary-encoded strings. It rejects `large_string`, `decimal`, `duration`, `time`, `binary`, lists, structs, maps, and polars' Int128/UInt128 (pyarrow cannot even read those). Every one of those is cast here.

- [ ] **Step 1: Failing tests**

`tests/kernel/test_arrow.py`:

```python
import io
import json
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from zoneinfo import ZoneInfo

import polars as pl
import pyarrow as pa

from quarry.kernel.arrow import arrow_ipc, for_viewer


def mixed() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "s": ["a", None],
            "d": [date(2024, 1, 2), None],
            "ts": [datetime(2024, 1, 2, 3), None],
            "z": pl.Series(
                [datetime(2024, 1, 2, 3, tzinfo=ZoneInfo("America/New_York")), None]
            ),
            "dec": pl.Series([Decimal("1.50"), None], dtype=pl.Decimal(38, 2)),
            "cat": pl.Series(["x", None], dtype=pl.Categorical),
            "dur": [timedelta(days=1), None],
            "t": [time(9, 30), None],
            "b": [b"\x00\x01", None],
            "l": [[1, 2], None],
            "st": [{"a": 1}, None],
            "big": pl.Series([1, None], dtype=pl.Int128),
            "u": pl.Series([2**63, None], dtype=pl.UInt64),
            "f": [1.5, float("nan")],
        }
    )


def test_for_viewer_casts_every_unsupported_dtype() -> None:
    out = for_viewer(mixed())
    assert out.schema == pl.Schema(
        {
            "s": pl.String,
            "d": pl.Date,
            "ts": pl.Datetime("us"),
            "z": pl.Datetime("us", "America/New_York"),
            "dec": pl.Float64,
            "cat": pl.String,
            "dur": pl.String,
            "t": pl.String,
            "b": pl.String,
            "l": pl.String,
            "st": pl.String,
            "big": pl.Float64,
            "u": pl.UInt64,
            "f": pl.Float64,
        }
    )
    row = out.row(0, named=True)
    assert row["dec"] == 1.5 and row["cat"] == "x" and row["b"] == "AAE="
    assert json.loads(row["l"]) == [1, 2] and json.loads(row["st"]) == {"a": 1}
    assert row["t"] == "09:30:00"
    assert "1d" in row["dur"]
    assert out.row(1, named=True)["l"] is None


def test_arrow_ipc_is_a_stream_with_narrow_strings() -> None:
    data = arrow_ipc(mixed())
    reader = pa.ipc.open_stream(io.BytesIO(data))  # open_file would raise on a stream
    table = reader.read_all()
    assert table.schema.field("s").type == pa.string()
    assert table.schema.field("cat").type == pa.string()
    assert not any(pa.types.is_large_string(f.type) for f in table.schema)
    assert table.num_rows == 2
    back = pl.read_ipc_stream(io.BytesIO(data))
    assert back["s"].to_list() == ["a", None]


def test_arrow_ipc_keeps_non_finite_floats() -> None:
    back = pl.read_ipc_stream(io.BytesIO(arrow_ipc(pl.DataFrame({"f": [float("inf")]}))))
    assert back["f"][0] == float("inf")
```

Before running, print `pl.Series([timedelta(days=1)]).cast(pl.String)[0]` and `pl.Series([time(9, 30)]).cast(pl.String)[0]` with polars 2.0 and adjust the two string literals the test expects; the assertions' shape stays.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/kernel/test_arrow.py -q`
Expected: FAIL with `ModuleNotFoundError: No module named 'quarry.kernel.arrow'`.

- [ ] **Step 3: Implement**

`src/quarry/kernel/arrow.py`:

```python
"""Arrow IPC for the browser: a frame cast to the types Perspective's reader accepts."""

from __future__ import annotations

import json

import polars as pl
import pyarrow as pa


def for_viewer(frame: pl.DataFrame) -> pl.DataFrame:
    """`frame` with every dtype Perspective rejects cast to one it reads.

    Decimal and 128-bit integers become Float64 (lossy past 2**53; Arrow here is a display
    transport). Categorical, Enum, Duration, Time and Binary become String. Nested columns
    become one JSON string per row. Everything else passes through unchanged.
    """
    exprs = [
        expr
        for name, dtype in frame.schema.items()
        if (expr := _viewer_expr(name, dtype)) is not None
    ]
    return frame.with_columns(exprs) if exprs else frame


def arrow_ipc(frame: pl.DataFrame) -> bytes:
    """`for_viewer(frame)` as Arrow IPC stream bytes with `string`, never `large_string`."""
    table = for_viewer(frame).to_arrow(compat_level=pl.CompatLevel.oldest())
    fields = [
        pa.field(f.name, pa.string(), nullable=f.nullable)
        if pa.types.is_large_string(f.type)
        else f
        for f in table.schema
    ]
    narrowed = table.cast(pa.schema(fields))
    sink = pa.BufferOutputStream()
    with pa.ipc.new_stream(sink, narrowed.schema) as writer:
        writer.write_table(narrowed)
    return bytes(sink.getvalue().to_pybytes())


def _viewer_expr(name: str, dtype: pl.DataType) -> pl.Expr | None:
    col = pl.col(name)
    if isinstance(dtype, pl.Decimal | pl.Int128 | pl.UInt128):
        return col.cast(pl.Float64)
    if isinstance(dtype, pl.Categorical | pl.Enum | pl.Duration | pl.Time):
        return col.cast(pl.String)
    if isinstance(dtype, pl.Binary):
        return col.bin.encode("base64")
    if isinstance(dtype, pl.List | pl.Array | pl.Struct | pl.Map | pl.Object):
        return col.map_batches(_json_strings, return_dtype=pl.String)
    return None


def _json_strings(series: pl.Series) -> pl.Series:
    # `default=str` covers dates and decimals inside the nested value.
    values = [None if v is None else json.dumps(v, default=str) for v in series.to_list()]
    return pl.Series(series.name, values, dtype=pl.String)
```

`pl.UInt128` exists in polars 2.0; if `mypy` or the import rejects it on the pinned version, drop it from the isinstance tuple (Int128 stays).

In `executor.py` replace `_arrow_base64` with:

```python
def _arrow_base64(frame: pl.DataFrame) -> str:
    return base64.b64encode(arrow_ipc(frame)).decode("ascii")
```

and add `from quarry.kernel.arrow import arrow_ipc`; drop the `io` import if nothing else in the file uses it. In `tests/kernel/test_executor.py`, the tests at lines 651 and 661 decode with `pl.read_ipc(...)`; change both to `pl.read_ipc_stream(...)`.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/kernel -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: cast arrow query results to the types Perspective reads"
```

---

### Task 2: Runtime CSP, Perspective wrapper, and the Playwright proof

**Files:**

- Modify: `web/runtime.html` (CSP), `docs/superpowers/specs/2026-10-08-quarry-design.md` (sections 9 Iframe runtime and 12 Security), `web/src/runtime/hooks.ts` (`arrow` on success), `web/src/runtime/cache.ts` (decoded buffer per entry), `web/src/runtime/modules.ts` (`@quarry/perspective`), `web/src/runtime/libraries.ts` (`perspective`), `web/package.json`, `web/vite.config.ts` (alias), `src/quarry/agent/context.py` (`CONTRACT` hook line)
- Create: `web/src/runtime/perspective/engine.ts`, `web/src/runtime/perspective/PerspectiveViewer.tsx`, `web/src/runtime/perspective/index.ts`, `web/src/shared/base64.ts`
- Test: `web/src/shared/base64.test.ts`, `web/src/runtime/hooks.test.ts` (extend), `tests/e2e/test_perspective.py`

**Interfaces:**

- Produces: `decodeBase64(text: string): ArrayBuffer`; `useQuery` success gains `arrow: ArrayBuffer | null`; `@quarry/perspective` exporting `PerspectiveViewer` (props `{ arrow: ArrayBuffer; config?: ViewerConfigUpdate; onConfig?: (c: ViewerConfigUpdate) => void; className?: string }`), `ensureEngine(): Promise<Client>` and the `ViewerConfigUpdate` type.
- Consumes: Stage 3 `MODULES`, `RUNTIME_LIBRARIES`, `useQuery`, `RequestCache`; Stage 3 Task 9 Step 2b static CORS middleware (`STATIC_PREFIXES` lists `/assets/`, `/runtime.html`, `/libs/`); if the Stage 3 branch lacks it, add it here exactly as that step describes, with its test; Task 1 stream bytes.

- [ ] **Step 1: CSP and spec amendment**

`web/runtime.html` meta tag content becomes exactly:

```
default-src 'none'; script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'; worker-src blob:; style-src 'self' 'unsafe-inline'; img-src data: blob:; font-src 'self'; connect-src 'self'
```

In the spec, section 9 "Iframe runtime" first paragraph: replace "served with a Content Security Policy that forbids all network access (`default-src 'none'` with `script-src 'self'` and `style-src 'self' 'unsafe-inline'`)" with "served with a Content Security Policy that allows nothing but the Quarry server's own static files (`default-src 'none'`, `script-src 'self' 'unsafe-eval' 'wasm-unsafe-eval'`, `worker-src blob:` for Perspective's engine worker, `connect-src 'self'` for wasm and chunk fetches, `style-src 'self' 'unsafe-inline'`)". Section 12 bullet "Generated TSX runs only in the iframe with a no-network CSP. The bridge is the only path out and has three request types." becomes "Generated TSX runs only in the iframe, whose CSP reaches nothing but the server's own static files; API routes need the bearer token the frame never holds. The bridge is the only path to data and has three request types." Run `npx prettier@3.9.9 --write` on the spec afterwards.

- [ ] **Step 2: Failing tests**

`web/src/shared/base64.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { decodeBase64 } from "./base64";

describe("decodeBase64", () => {
  it("decodes to the original bytes", () => {
    const bytes = new Uint8Array(decodeBase64("AAEC/w=="));
    expect([...bytes]).toEqual([0, 1, 2, 255]);
  });
  it("returns an empty buffer for an empty string", () => {
    expect(decodeBase64("").byteLength).toBe(0);
  });
});
```

Append to `web/src/runtime/hooks.test.ts`, using the file's existing helper that renders `useQuery` inside `RuntimeProvider` over a bridge stub whose `query` returns a promise the test resolves (if Stage 3 named it differently, adapt the two calls below):

```ts
it("exposes arrow bytes for an arrow query", async () => {
  const { result, resolve } = renderQuery({ dataset: "d", format: "arrow" });
  resolve({
    schema: [{ name: "a", dtype: "Int64" }],
    rows: null,
    arrow_base64: "AAEC",
    row_count: 1,
    truncated: false,
  });
  await waitFor(() => expect(result.current.status).toBe("success"));
  const state = result.current;
  if (state.status !== "success") throw new Error("unreachable");
  expect(state.rows).toEqual([]);
  expect([...new Uint8Array(state.arrow ?? new ArrayBuffer(0))]).toEqual([
    0, 1, 2,
  ]);
});
```

- [ ] **Step 3: Implement the hook and base64**

`web/src/shared/base64.ts`:

```ts
export function decodeBase64(text: string): ArrayBuffer {
  const binary = atob(text);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
  return bytes.buffer;
}
```

In `web/src/runtime/cache.ts`, widen the success member of `QueryState` to `{ status: "success"; result: QueryResult; arrow: ArrayBuffer | null }` and fill it where the query resolves: `{ status: "success", result, arrow: result.arrow_base64 === null ? null : decodeBase64(result.arrow_base64) }`. Decoding once per cache entry keeps the buffer stable across renders, which the viewer effect depends on.

In `web/src/runtime/hooks.ts`, the success branch of `QueryHookResult` gains `arrow: ArrayBuffer | null`, and `useQuery` builds its result with `useMemo` keyed on `state`:

```ts
return useMemo<QueryHookResult>(() => {
  if (state.status !== "success") return state;
  const { result } = state;
  return {
    status: "success",
    rows: result.rows ?? [],
    schema: result.schema,
    rowCount: result.row_count,
    truncated: result.truncated,
    arrow: state.arrow,
  };
}, [state]);
```

In `src/quarry/agent/context.py` `CONTRACT`, the `useQuery` line becomes:

```
  useQuery(spec): {status:"loading"} | {status:"success", rows, schema, rowCount, truncated, arrow} | {status:"error", message}
    arrow is an ArrayBuffer of Arrow IPC when spec.format is "arrow" (rows is then []), else null.
```

- [ ] **Step 3b: Report state once after mount**

The Stage 3 plan's `ViewStateStore` posts `stateChanged` only from `set()`, so a view the researcher never touches (every built-in with sensible defaults) records no snapshot: `step.view.snapshots` stays empty, Stage 4's `save_view` writes `queries: []`, and "To code" (Task 12) has nothing to render. Check the real Stage 3 branch first; if `createRuntime` already flushes after mount, skip this step.

Test, appended to `web/src/runtime/mount.test.tsx` (use that file's `post` spy and fake module table):

```tsx
it("reports the mount-time state and queries once, unprompted", async () => {
  vi.useFakeTimers();
  const { runtime, post } = setup();
  runtime.handle({
    type: "mount",
    viewId: "v1",
    source: SOURCE_WITH_ONE_QUERY,
    initialState: { limit: 5 },
    datasets: ["df"],
  });
  await vi.runAllTimersAsync();
  const reported = post.mock.calls
    .map(([m]) => m)
    .filter((m) => m.type === "stateChanged");
  expect(reported).toHaveLength(1);
  expect(reported[0]).toMatchObject({ viewId: "v1", state: { limit: 5 } });
  expect(reported[0].queries).toHaveLength(1);
  vi.useRealTimers();
});
```

`SOURCE_WITH_ONE_QUERY` is a component calling `useQuery({ dataset: "df", limit: 5 })` once; the Stage 3 test file already has one for the query round trip, reuse it.

Implementation: add `flush(): void` to `ViewStateStore`:

```ts
  /** Report the current state now, with the queries issued so far. */
  flush(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.onChange(this.cached);
  }
```

and in `createRuntime`'s `mount`, after `render(mounted, cache, component, message.datasets)`:

```ts
// One report after the first render so an untouched view still records its queries.
setTimeout(() => {
  if (mounted?.store === store) store.flush();
}, 300);
```

The snapshot route (Stage 3 Task 9) treats a repeated identical state as a new snapshot; one extra entry per mount is acceptable and keeps the route simple. The Stage 4 route test asserting `view["queries"] == []` runs without a browser and stays as it is.

- [ ] **Step 4: Perspective wrapper**

```bash
cd web && npm install @finos/perspective@3.8.0 @finos/perspective-viewer@3.8.0 @finos/perspective-viewer-datagrid@3.8.0 @finos/perspective-viewer-d3fc@3.8.0
```

`web/src/runtime/perspective/engine.ts`:

```ts
import perspective from "@finos/perspective";
import type { Client } from "@finos/perspective";
import perspectiveViewer from "@finos/perspective-viewer";
import "@finos/perspective-viewer-datagrid";
import "@finos/perspective-viewer-d3fc";
import serverWasm from "@finos/perspective/dist/wasm/perspective-server.wasm?url";
import clientWasm from "@finos/perspective-viewer/dist/wasm/perspective-viewer.wasm?url";

let engine: Promise<Client> | null = null;

/** One engine worker per runtime frame; the wasm files are fetched from the bundle. */
export function ensureEngine(): Promise<Client> {
  engine ??= (async () => {
    await Promise.all([
      perspective.init_server(fetch(serverWasm)),
      perspectiveViewer.init_client(fetch(clientWasm)),
    ]);
    return perspective.worker();
  })();
  return engine;
}
```

Vite emits `?url` wasm imports as hashed assets under `/assets/`, which the Stage 3 CORS middleware already covers. Perspective creates the engine worker from a Blob URL (hence `worker-src blob:`); `init_server` hands it the wasm bytes, so the worker fetches nothing itself. `vite/client` types `*?url` imports as `string`; `web/src/vite-env.d.ts` from the template references it.

`web/src/runtime/perspective/PerspectiveViewer.tsx`:

```tsx
import { useEffect, useRef } from "react";
import type { Table } from "@finos/perspective";
import type {
  HTMLPerspectiveViewerElement,
  ViewerConfigUpdate,
} from "@finos/perspective-viewer";
import { ensureEngine } from "./engine";

interface PerspectiveViewerProps {
  arrow: ArrayBuffer;
  config?: ViewerConfigUpdate;
  onConfig?: (config: ViewerConfigUpdate) => void;
  className?: string;
}

export function PerspectiveViewer({
  arrow,
  config,
  onConfig,
  className,
}: PerspectiveViewerProps) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<HTMLPerspectiveViewerElement | null>(null);
  const latest = useRef({ config, onConfig });
  latest.current = { config, onConfig };

  // The custom element owns its DOM; React only creates and removes it.
  useEffect(() => {
    const el = host.current;
    if (el === null) return;
    const node = document.createElement(
      "perspective-viewer",
    ) as HTMLPerspectiveViewerElement;
    node.style.height = "100%";
    el.replaceChildren(node);
    viewer.current = node;
    const onUpdate = () => {
      void node.save().then((saved) => latest.current.onConfig?.(saved));
    };
    node.addEventListener("perspective-config-update", onUpdate);
    return () => {
      node.removeEventListener("perspective-config-update", onUpdate);
      void node.delete();
      el.replaceChildren();
      viewer.current = null;
    };
  }, []);

  useEffect(() => {
    const node = viewer.current;
    if (node === null) return;
    let table: Table | null = null;
    let cancelled = false;
    void (async () => {
      const client = await ensureEngine();
      const next = await client.table(arrow);
      if (cancelled) {
        await next.delete();
        return;
      }
      table = next;
      await node.load(next);
      if (latest.current.config !== undefined)
        await node.restore(latest.current.config);
    })();
    return () => {
      cancelled = true;
      void table?.delete();
    };
  }, [arrow]);

  return <div ref={host} className={className ?? "h-full w-full"} />;
}
```

`web/src/runtime/perspective/index.ts`:

```ts
export { ensureEngine } from "./engine";
export { PerspectiveViewer } from "./PerspectiveViewer";
export type { ViewerConfigUpdate } from "@finos/perspective-viewer";
```

Add to `MODULES` in `web/src/runtime/modules.ts`:

```ts
  "@quarry/perspective": () => import("./perspective").then(esm),
```

Add `"perspective"` to `RUNTIME_LIBRARIES` in `web/src/runtime/libraries.ts`. Add to `web/vite.config.ts` and `web/vitest.config.ts` `resolve.alias`: `"@quarry/perspective": path.resolve(root, "./src/runtime/perspective/index.ts")`, and the same `paths` entry in `tsconfig.app.json`, so built-ins type-check their import and tests can mock it.

- [ ] **Step 5: Playwright proof**

`tests/e2e/test_perspective.py`:

```python
from __future__ import annotations

from collections.abc import Callable

from playwright.sync_api import Page, expect

from quarry.agent.types import AssistantTurn
from tests.e2e.conftest import RunningServer
from tests.e2e.test_ui import end, open_session, py, write

MIXED = (
    "from datetime import date, datetime\nfrom decimal import Decimal\n"
    "df = pl.DataFrame({'d': [date(2024, 1, 2), date(2024, 1, 3)], "
    "'ts': [datetime(2024, 1, 2, 9), datetime(2024, 1, 3, 9)], "
    "'px': pl.Series([Decimal('1.50'), Decimal('2.25')], dtype=pl.Decimal(38, 2)), "
    "'sym': pl.Series(['A', 'B'], dtype=pl.Categorical), 's': ['x', 'y']})\n"
)
VIEW = """\
import { useQuery } from "@quarry/hooks";
import { PerspectiveViewer } from "@quarry/perspective";
export default function V({ datasets }: { datasets: string[] }) {
  const q = useQuery({ dataset: datasets[0] ?? "", format: "arrow" });
  if (q.status !== "success" || q.arrow === null) return <p>{q.status}</p>;
  return (
    <div style={{ height: 380 }}>
      <p data-testid="rows">{q.rowCount}</p>
      <PerspectiveViewer arrow={q.arrow} />
    </div>
  );
}
"""


def test_perspective_mounts_in_the_sandbox(
    serve: Callable[[list[AssistantTurn]], RunningServer], page: Page
) -> None:
    server = serve([py("c1", MIXED), write("c2", VIEW), end("pivot it")])
    errors: list[str] = []
    page.on("console", lambda m: errors.append(m.text) if m.type == "error" else None)
    open_session(page, server, "pivot df")
    frame = page.frame_locator("iframe[title='View for step 1']")
    expect(frame.get_by_test_id("rows")).to_have_text("2", timeout=60_000)
    expect(frame.locator("perspective-viewer")).to_be_visible(timeout=60_000)
    # The datagrid plugin renders one header cell per column once the table is loaded.
    header = frame.locator("perspective-viewer regular-table th", has_text="px")
    expect(header).to_be_visible(timeout=60_000)
    blocked = [e for e in errors if "Content Security Policy" in e or "CORS" in e]
    assert not blocked, blocked
```

Playwright's CSS engine pierces open shadow roots, which is where the datagrid plugin renders its `regular-table`. If the header locator never resolves, replace that assertion with a size check through the element's API: `frame.locator("perspective-viewer").evaluate("el => el.getTable().then(t => t.size())")` must equal 2.

Run it with the web build in place:

```bash
cd web && npm run build && cd .. && uv run pytest tests/e2e/test_perspective.py -q
```

If the engine worker is refused, do not widen `script-src`. Serve the worker from the bundle instead: `perspective.worker(Promise.resolve(new Worker(new URL("@finos/perspective/dist/esm/perspective-server.worker.js", import.meta.url), { type: "module" })))`, which Vite emits as a same-origin asset, and drop `worker-src blob:` from the CSP and the spec text. Record whichever shape shipped in "Open items" and in `docs/context/decisions.md` (Task 13).

- [ ] **Step 6: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && npm run build && cd ..
uv run pytest tests/e2e/test_perspective.py tests/agent -q && uv run ruff check src tests && uv run mypy src
git add web src tests docs && git commit -m "feat: mount Perspective over arrow inside the sandboxed runtime"
```

---

### Task 3: `to_source` hardening, kernel `to_code`, and the to-code route

**Files:**

- Modify: `src/quarry/query/source_target.py` (`QueryError`, NFKC, `relation_projection`), `src/quarry/kernel/datasets.py` (`importable_projection`), `src/quarry/kernel/executor.py` (`to_code`, `ToCodeResult`), `src/quarry/kernel/service.py` (dispatch), `src/quarry/kernel/client.py` (`to_code`), `src/quarry/server/service.py` (`to_code`), `src/quarry/server/app.py` (route), `tests/query/test_source_target.py` (three tests expect `QueryError` now)
- Test: `tests/query/test_source_target.py` (extend), `tests/kernel/test_datasets.py` (extend), `tests/kernel/test_executor.py` (extend), `tests/server/test_app.py` (extend)

**Interfaces:**

- Produces: `to_source(spec, backing, *, result_name="result", schema=None, relation_projection: str | None = None) -> str` raising only `QueryError` for spec-caused failures; `importable_projection(rel) -> str | None`; `ToCodeResult(BaseModel){code: str}`; `Executor.to_code(specs: list[QuerySpec]) -> ToCodeResult`; `KernelClient.to_code(specs) -> str`; `SessionService.to_code(session_id, specs) -> str`; `POST /sessions/{id}/to-code` body `{queries: list[QuerySpec]}` → `{code: str}` (400 on `QueryError`/`RpcFailure`, 404 unknown session, 409 busy, 503 dead kernel).
- Consumes: `to_sql`, `relation_view`, `split_for_relation`, `quote_ident` (`sql_target.py`); `importable_relation`, `unique_names`, `_unimportable`, `_importable` (`datasets.py:106-180`); `Executor._dataset`; the `/query` route shape (`app.py`).

- [ ] **Step 1: Failing tests, query layer**

In `tests/query/test_source_target.py` change the three `pytest.raises(ValueError, ...)` at lines 407, 424 and 430 to `pytest.raises(QueryError, ...)` (same `match=`), and add:

```python
def test_errors_are_query_errors_with_the_dataset() -> None:
    with pytest.raises(QueryError) as info:
        to_source(QuerySpec(dataset="class"), "polars")
    assert info.value.dataset == "class" and info.value.column is None


@pytest.mark.parametrize("name", ["ｔrades", "tra­des"])
def test_non_nfkc_identifiers_are_rejected(name: str) -> None:
    # `isidentifier` accepts a fullwidth t, which Python then runs as plain `trades`.
    with pytest.raises(QueryError, match="ASCII letters, digits and underscores"):
        to_source(QuerySpec(dataset=name), "polars")
    with pytest.raises(QueryError, match="ASCII letters, digits and underscores"):
        to_source(QuerySpec(dataset="trades"), "polars", result_name=name)


def test_malformed_literal_with_schema_is_a_query_error() -> None:
    spec = QuerySpec(dataset="trades", filters=[Filter(col="date", op="ge", value="2024-99-99")])
    with pytest.raises(QueryError) as info:
        to_source(spec, "polars", schema=trades().schema)
    assert info.value.column == "date"
    assert "2024-99-99" in str(info.value)


def test_relation_projection_casts_interval_columns_so_the_source_runs() -> None:
    conn = utc_connection()
    namespace: dict[str, object] = {
        "pl": pl,
        "rel": conn.sql("SELECT 1 AS n, INTERVAL 9 DAY AS span, INTERVAL 100 DAY AS span2"),
    }
    projection = '#1 AS "n", CAST(#2 AS VARCHAR) AS "span", CAST(#3 AS VARCHAR) AS "span2"'
    source = to_source(QuerySpec(dataset="rel"), "duckdb", relation_projection=projection)
    assert 'rel.project(' in source and "CAST(#2 AS VARCHAR)" in source
    exec(source, namespace)  # noqa: S102 - the generated source is the thing under test
    result = namespace["result"]
    assert isinstance(result, pl.DataFrame)
    assert result.schema == pl.Schema({"n": pl.Int32, "span": pl.String, "span2": pl.String})
    assert result["span"][0] == "9 days"
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/query/test_source_target.py -q`
Expected: the three changed tests fail with `ValueError` raised instead of `QueryError`; the new ones fail on `TypeError: unexpected keyword 'relation_projection'` or the missing match.

- [ ] **Step 3: Implement the query layer**

In `source_target.py`:

```python
import unicodedata
from quarry.query.spec import ..., QueryError, ...

IDENT_RE: Final = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def to_source(
    spec: QuerySpec,
    backing: Backing,
    *,
    result_name: str = "result",
    schema: Schema | None = None,
    relation_projection: str | None = None,
) -> str:
    """Render `spec` as Python that assigns the polars DataFrame `to_polars` yields.

    `relation_projection`, for a DuckDB relation, is the DuckDB select list the kernel reads
    the relation through (`importable_projection`): it renames repeated columns and casts
    INTERVAL and UNION columns to VARCHAR so `.pl()` can import them. Every failure caused by
    the spec is a QueryError.
    """
    _require_identifier(spec.dataset, "dataset", spec)
    _require_identifier(result_name, "result_name", spec)
    if schema is not None:
        check_columns(spec, set(schema))
    try:
        return _render(spec, backing, result_name, schema, relation_projection)
    except (ValueError, TypeError) as exc:
        # Literal coercion and shape checks raise plain errors; the caller sees one type.
        raise QueryError(str(exc), dataset=spec.dataset, column=_blamed(spec, exc)) from exc
```

Move the body of the old `to_source` after the identifier checks into `_render(spec, backing, result_name, schema, relation_projection)`, with two changes: the two `raise ValueError(...)` lines in it become `raise QueryError(..., dataset=spec.dataset)` (so they are not re-wrapped; add `except QueryError: raise` before the `except (ValueError, TypeError)` clause), and the relation head becomes:

```python
    source_rel = spec.dataset
    if relation_projection is not None:
        source_rel = f"{spec.dataset}.project({py_literal(relation_projection)})"
    head = f"{source_rel}.query({py_literal(view)}, {py_literal(to_sql(sql_part, view))}).pl()"
```

The `finally` block keeps dropping the view through `spec.dataset` (the projection shares its connection). Add:

```python
def _require_identifier(name: str, role: str, spec: QuerySpec) -> None:
    # Both names are pasted into code that will run, so nothing else may get through.
    # Python NFKC-folds identifiers at parse time, so a name that is not ASCII could run as a
    # different name than the one checked here.
    if not IDENT_RE.match(name) or keyword.iskeyword(name):
        raise QueryError(
            f"{role} {name!r} must be a Python identifier of ASCII letters, digits and underscores",
            dataset=spec.dataset,
        )


def _blamed(spec: QuerySpec, exc: BaseException) -> str | None:
    """The filter column whose literal failed to render, when the message names its value."""
    text = str(exc)
    for f in spec.filters:
        if f.value is not None and str(f.value) in text:
            return f.col
    return None
```

`unicodedata` is then unused; the ASCII regex makes NFKC moot (every ASCII identifier is NFKC-stable). Remove the import, and keep the `_require_identifier` comment. Delete the old `_require_identifier` (`isidentifier` version).

In `datasets.py` replace `importable_relation` with:

```python
def importable_relation(rel: duckdb.DuckDBPyRelation) -> duckdb.DuckDBPyRelation:
    """`rel` read through `importable_projection(rel)`, or `rel` itself when it needs none."""
    projection = importable_projection(rel)
    return rel if projection is None else rel.project(projection)


def importable_projection(rel: duckdb.DuckDBPyRelation) -> str | None:
    """The select list `.pl()` needs to import `rel`, or None when `rel` imports as it is.

    Repeated names are made unique as `.pl()` makes them (`unique_names`), and INTERVAL and
    UNION columns, which polars cannot import, are cast to VARCHAR. Columns are projected by
    position (`#n`), so duplicate names cannot pick the wrong column.
    """
    names = unique_names(rel.columns)
    if names == rel.columns and not any(_unimportable(t) for t in rel.types):
        return None
    columns = enumerate(zip(names, rel.types, strict=True), start=1)
    return ", ".join(_importable(n, name, t) for n, (name, t) in columns)
```

and delete `uniquely_named` (its only caller was `importable_relation`; grep `tests/kernel/test_datasets.py` for `uniquely_named` and rewrite that test against `importable_projection`, asserting the projection string for `a, a, A` is `#1 AS "a", #2 AS "a_1", #3 AS "A_2"`).

- [ ] **Step 4: Failing tests, kernel and server**

Append to `tests/kernel/test_executor.py`:

```python
def test_to_code_renders_each_spec_with_the_live_schema() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'ret': [0.5, 1.0], 'sym': ['a', 'b']})")
    ex.execute(f"rel = _conn.sql({PIVOT_ROWS!r})")
    specs = [
        QuerySpec(dataset="df", filters=[Filter(col="ret", op="in", value=[1])]),
        QuerySpec(dataset="rel", sort=[Sort(col="k")], limit=2),
    ]
    code = ex.to_code(specs).code
    # With the schema, the integer literal is coerced to the float column's type.
    assert "is_in([1.0])" in code
    assert "df_1 = (" in code and "rel_2 = " in code
    assert "DROP VIEW" in code
    namespace = dict(ex._ns)  # noqa: SLF001 - the generated code must run in the step namespace
    exec(code, namespace)  # noqa: S102
    assert namespace["df_1"].height == 1 and namespace["rel_2"].height == 2


def test_to_code_rejects_unknown_dataset_and_bad_column() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    with pytest.raises(KeyError):
        ex.to_code([QuerySpec(dataset="nope")])
    with pytest.raises(QueryError) as info:
        ex.to_code([QuerySpec(dataset="df", filters=[Filter(col="b", op="eq", value=1)])])
    assert info.value.column == "b"
```

Append to `tests/server/test_app.py`:

```python
def test_to_code_route_renders_and_rejects(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "df = pl.DataFrame({'a': [1]})"})
        wait_idle(client, sid)
        ok = client.post(f"/sessions/{sid}/to-code", json={"queries": [{"dataset": "df"}]})
        assert ok.status_code == 200 and "df_1 = (" in ok.json()["code"]
        bad = client.post(
            f"/sessions/{sid}/to-code",
            json={"queries": [{"dataset": "df", "filters": [{"col": "x", "op": "eq", "value": 1}]}]},
        )
        assert bad.status_code == 400 and "x" in bad.json()["detail"]
        malformed = client.post(f"/sessions/{sid}/to-code", json={"queries": [{"dataset": "df", "limit": 0}]})
        assert malformed.status_code == 400
        assert client.post("/sessions/nope/to-code", json={"queries": []}).status_code == 404
```

- [ ] **Step 5: Implement kernel and server**

In `executor.py`, after `QueryResult`:

```python
class ToCodeResult(BaseModel):
    code: str
```

and the method, after `query`:

```python
    def to_code(self, specs: list[QuerySpec]) -> ToCodeResult:
        """Each spec as Python assigning `<dataset>_<n>`, rendered with the live schema."""
        blocks: list[str] = []
        for n, spec in enumerate(specs, start=1):
            obj = self._dataset(spec.dataset)
            projection = None
            if isinstance(obj, duckdb.DuckDBPyRelation):
                projection = importable_projection(obj)
                schema = importable_relation(obj).limit(0).pl().schema
            elif isinstance(obj, pl.LazyFrame):
                schema = obj.collect_schema()
            else:
                schema = obj.schema
            blocks.append(
                to_source(
                    spec,
                    backing_of(obj),
                    result_name=f"{spec.dataset}_{n}",
                    schema=schema,
                    relation_projection=projection,
                )
            )
        return ToCodeResult(code="\n".join(blocks))
```

Import `importable_projection` from `quarry.kernel.datasets` and `to_source` from `quarry.query.source_target`. A LazyFrame's `collect_schema()` resolves its plan; that is the same cost `describe` already pays.

In `kernel/service.py` `_dispatch`, add before `case "shutdown"`:

```python
            case "to_code":
                specs = _SPEC_LIST.validate_python(params.get("specs"))
                return self._executor.to_code(specs)
```

with `_SPEC_LIST: Final = TypeAdapter(list[QuerySpec])` at module level (`from typing import Final`, `from pydantic import TypeAdapter`).

In `kernel/client.py`:

```python
    def to_code(self, specs: list[QuerySpec]) -> str:
        params = {"specs": [s.model_dump(mode="json") for s in specs]}
        return ToCodeResult.model_validate(self._call("to_code", params)).code
```

(import `ToCodeResult` beside `QueryResult`). Add one round-trip case to `tests/kernel/test_client.py` mirroring its existing `query` test: execute a frame, call `client.to_code([QuerySpec(dataset=...)])`, assert the string contains `.lazy()`.

In `server/service.py`:

```python
    def to_code(self, session_id: str, specs: builtins.list[QuerySpec]) -> str:
        return self._kernel(session_id).to_code(specs)
```

In `server/app.py`, beside `query`:

```python
    class ToCodeRequest(BaseModel):
        queries: list[dict[str, Json]]

    @api.post("/sessions/{session_id}/to-code")
    def to_code(session_id: str, body: ToCodeRequest) -> dict[str, str]:
        session_or_404(session_id)
        try:
            specs = [QuerySpec.model_validate(q) for q in body.queries]
        except ValidationError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return {"code": service.to_code(session_id, specs)}
        except (QueryError, RpcFailure) as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
```

Define `ToCodeRequest` at module level (import `BaseModel` from pydantic) rather than inside `create_app`. The kernel's `KeyError` for an unknown dataset arrives as `RpcFailure` and maps to 400 like a query would.

- [ ] **Step 6: Verify and commit**

```bash
uv run pytest tests/query tests/kernel tests/server -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: render view queries to Python through the kernel"
```

---

### Task 4: Lineage through SQL strings and attribute mutation; session busy flag

**Files:**

- Modify: `src/quarry/kernel/lineage.py` (`CodeNames.sql_literals`, mutation targets), `src/quarry/kernel/executor.py` (SQL table reads), `src/quarry/server/service.py` (`SessionStatus.busy`), `docs/context/decisions.md` (Lineage section)
- Test: `tests/kernel/test_lineage.py`, `tests/kernel/test_executor.py`, `tests/server/test_app.py`

**Interfaces:**

- Produces: `CodeNames.sql_literals: frozenset[str]` (string literals passed as the first argument to `sql_local(...)` or any `<expr>.sql(...)` call); module-level attribute and subscript assignment targets (`df.columns = ...`, `df[...] = ...`) count their root name as a store; `Executor` adds to `reads` every dataset name DuckDB finds in those literals; `SessionStatus.busy: bool`.
- Consumes: `_ScopeVisitor` (`lineage.py:73`), `_exec` and `_written` (`executor.py:199, 293`), `SessionService.status` and `_restarts` (Stage 2 `service.py:127`, Stage 4 `_busy`).

- [ ] **Step 1: Failing tests**

Append to `tests/kernel/test_lineage.py`:

```python
def test_sql_string_literals_are_collected() -> None:
    names = analyze(
        "a = sql_local('SELECT * FROM recent')\n"
        "b = duckdb.sql(\"SELECT 1 FROM t\")\n"
        "c = _conn.sql('x')\n"
        "d = _conn.sql(query)\n"  # not a literal: nothing to collect
        "e = other('SELECT * FROM ignored')\n"
    )
    assert names.sql_literals == {"SELECT * FROM recent", "SELECT 1 FROM t", "x"}


def test_attribute_and_subscript_mutation_at_module_level_is_a_store() -> None:
    names = analyze("df.columns = ['a']\nother['k'] = 1\nnested.attr.deep = 2\nn += 1")
    assert names.stores == {"df", "other", "nested", "n"}
    assert {"df", "other", "nested", "n"} <= names.loads


def test_mutation_inside_a_function_is_not_a_module_store() -> None:
    names = analyze("def f():\n    df.columns = ['a']\n")
    assert names.stores == {"f"}
    assert "df" in names.loads  # the function reads the module-level df
```

Append to `tests/kernel/test_executor.py`:

```python
def test_sql_local_table_names_are_reads() -> None:
    conn = duckdb.connect()
    ex = make(conn)
    ex.execute("recent = pl.DataFrame({'a': [1, 2]})")
    ex.execute("conn = _conn\nconn.register('recent', recent)")
    result = ex.execute("top = _conn.sql('SELECT * FROM recent LIMIT 1').pl()")
    assert result.reads == ["recent"] and result.writes == ["top"]
    # A literal DuckDB cannot bind (a table function over a missing path) adds no reads and
    # does not fail the step; an unknown plain table name binds to a placeholder and is simply
    # not a dataset.
    glob = "SELECT * FROM read_parquet('/nonexistent/*.parquet')"
    bad = ex.execute(f"y = 1 if True else _conn.sql({glob!r}).pl()")
    assert bad.status == "ok" and bad.reads == []


def test_attribute_mutation_is_a_write() -> None:
    ex = make()
    ex.execute("df = pl.DataFrame({'a': [1]})")
    result = ex.execute("df.columns = ['b']")
    assert result.writes == ["df"] and result.reads == ["df"]
    assert result.datasets[0].schema_[0].name == "b"
```

Append to `tests/server/test_app.py`:

```python
def test_status_reports_busy_while_a_step_runs(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        flag = tmp_path / "flag"
        client.post(f"/sessions/{sid}/steps/manual", json={"code": hang(flag)})
        deadline = time.monotonic() + 10
        while not flag.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert client.get(f"/sessions/{sid}/status").json()["busy"] is True
        client.post(f"/sessions/{sid}/interrupt")
        wait_idle(client, sid)
        assert client.get(f"/sessions/{sid}/status").json()["busy"] is False
```

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/kernel/test_lineage.py tests/kernel/test_executor.py tests/server/test_app.py -q -k "sql or mutation or busy"`
Expected: FAIL (`CodeNames` has no `sql_literals`; `stores` lacks `df`; `KeyError: 'busy'`).

- [ ] **Step 3: Implement**

In `lineage.py`:

```python
@dataclass(slots=True, frozen=True)
class CodeNames:
    stores: frozenset[str]
    loads: frozenset[str]
    defines: frozenset[str]
    # String literals handed to `sql_local(...)` or `<anything>.sql(...)`: DuckDB can name the
    # tables they read, which the executor turns into dataset reads.
    sql_literals: frozenset[str] = frozenset()


def analyze(code: str) -> CodeNames:
    ...
    return CodeNames(
        frozenset(module.bound),
        frozenset(module.loads),
        frozenset(visitor.defines),
        frozenset(visitor.sql_literals),
    )
```

In `_ScopeVisitor.__init__` add `self.sql_literals: set[str] = set()`, and the handlers:

```python
    def visit_Call(self, node: ast.Call) -> None:
        if _is_sql_call(node.func) and node.args:
            first = node.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str):
                self.sql_literals.add(first.value)
        self.generic_visit(node)

    def visit_Assign(self, node: ast.Assign) -> None:
        for target in node.targets:
            self._note_mutation(target)
        self.generic_visit(node)

    def _note_mutation(self, target: ast.expr) -> None:
        # `df.columns = ...` and `df[...] = ...` change the object `df` holds in place. At module
        # level that is a store of `df`; inside a function it is only a read of a free name.
        root = _root_name(target)
        if root is not None and self._scope.kind == "module":
            self._scope.bound.add(root)
```

Extend `visit_AugAssign` and `visit_AnnAssign` to call `self._note_mutation(node.target)` before their existing logic (an `AnnAssign` with `value is None` and a Name target keeps its early return). Add module-level helpers:

```python
def _is_sql_call(func: ast.expr) -> bool:
    if isinstance(func, ast.Name):
        return func.id == "sql_local"
    return isinstance(func, ast.Attribute) and func.attr == "sql"


def _root_name(target: ast.expr) -> str | None:
    """The Name an attribute or subscript chain hangs off, or None for a plain Name or tuple."""
    node = target
    seen = False
    while isinstance(node, ast.Attribute | ast.Subscript):
        node, seen = node.value, True
    return node.id if seen and isinstance(node, ast.Name) else None
```

Tuple targets (`a, b = ...`) are left to `visit_Name`; `(df.x, y) = ...` records `df` only if you walk into `ast.Tuple` elements: do so with a loop over `target.elts` when `isinstance(target, ast.Tuple | ast.List)`.

In `executor.py`, where `execute` computes `reads` (around `dataset_reads(names, before, defined)`), add the SQL names:

```python
        sql_reads = self._sql_table_reads(names.sql_literals, before)
        reads = sorted({*dataset_reads(names, before, defined_earlier), *sql_reads})
```

and the method:

```python
    def _sql_table_reads(self, literals: frozenset[str], before: set[str]) -> set[str]:
        """Dataset names among the tables DuckDB finds in `literals`; a literal DuckDB cannot
        bind (a bad glob, a syntax error, several statements) contributes nothing."""
        found: set[str] = set()
        for sql in literals:
            try:
                found |= set(self._conn.get_table_names(sql))
            except duckdb.Error:
                continue
        return found & before
```

`get_table_names` binds the statement against the kernel connection: a frame registered as a view resolves, an unknown name binds to an empty placeholder and still appears, and only table functions (`read_parquet` on a missing path) raise. Read the real `execute` to find where `before` (the dataset names before the step) is computed; it already exists for `dataset_writes`.

In `server/service.py`:

```python
class SessionStatus(BaseModel):
    session_id: str
    running_step: str | None
    busy: bool
    kernel: KernelStatus
    last_error: str | None
```

and in `status()`: `busy=session_id in self._running or session_id in self._restarts`. Stage 4's `_busy` context manager records a hold in `_restarts`; confirm on the real branch and use whichever set it marks. Add `busy: boolean` to TS `SessionStatus` in `web/src/shared/api-types.ts` (the host uses it in Task 12).

In `docs/context/decisions.md` under "Lineage", add two bullets: SQL string literals reach DuckDB's binder for table names and the executor keeps those that were datasets before the step (a failure to bind drops the literal silently); an attribute or subscript assignment at module level is a store of its root name, inside a function it is not.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/kernel tests/server -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests docs && git commit -m "feat: track SQL string reads and in-place mutation in lineage"
```

---

### Task 5: Save generated components into the researcher's library

**Files:**

- Create: `src/quarry/server/component_routes.py`
- Modify: `src/quarry/components/library.py` (`COMPONENT_ID_RE`, `requirements_for`, `write_component`), `src/quarry/server/app.py` (register)
- Test: `tests/components/test_library.py` (extend), `tests/server/test_component_routes.py`

**Interfaces:**

- Produces: `COMPONENT_ID_RE`; `requirements_for(meta: DatasetMeta) -> list[SchemaRequirement]`; `write_component(root: Path, manifest: ComponentManifest, source: str) -> Path`; `SaveComponentRequest {id, name, description, tags, source, session_id: str | None, dataset: str | None}`; `register_component_routes(api, *, library, researcher_root, transpiler, sessions)` adding `POST /components` (201 → `ComponentManifest`; 400 bad id or transpile error; 404 unknown session or dataset; 409 id exists) and `GET /components` (→ `list[ComponentManifest]`).
- Consumes: `ComponentLibrary.get/entries`, `dtype_class` (`library.py`), `Transpiler.check` (`agent/transpile.py`), `SessionService.datasets`, `write_atomic` (`quarry/projects/files.py`, Stage 4), the Stage 2 `api` router with `authed` dependency.

- [ ] **Step 1: Failing tests**

Append to `tests/components/test_library.py`:

```python
from quarry.components.library import (
    COMPONENT_ID_RE,
    ComponentManifest,
    requirements_for,
    write_component,
)


def test_requirements_for_lists_each_dtype_class_present() -> None:
    reqs = requirements_for(meta([("date", "Date"), ("ret", "Float64"), ("vol", "Int64"), ("f", "Boolean")]))
    assert [(r.role, r.dtype, r.min) for r in reqs] == [
        ("datetime", "datetime", 1),
        ("numeric", "numeric", 2),
    ]
    assert requirements_for(meta([])) == []


def test_write_component_then_library_finds_it(tmp_path: Path) -> None:
    manifest = ComponentManifest(
        id="my-scatter",
        name="My scatter",
        description="",
        tags=["scatter"],
        origin="generated",
        created_at="2026-10-09T00:00:00Z",
    )
    path = write_component(tmp_path, manifest, "export default function V() { return null }")
    assert path == tmp_path / "my-scatter"
    entry = ComponentLibrary([tmp_path]).get("my-scatter")
    assert entry is not None and entry.manifest.origin == "generated"
    assert entry.source_path.read_text().startswith("export default")


def test_component_id_pattern() -> None:
    assert COMPONENT_ID_RE.match("ok-id-9")
    assert COMPONENT_ID_RE.match("Bad") is None and COMPONENT_ID_RE.match("a/b") is None
```

`tests/server/test_component_routes.py`:

```python
from pathlib import Path

from quarry.components.library import builtin_root
from tests.server.test_app import make_client, wait_idle

SOURCE = 'import { useQuery } from "@quarry/hooks";\nexport default function V({ datasets }: { datasets: string[] }) { return <p>{datasets[0]}</p>; }\n'


def test_save_component_writes_manifest_and_lists_it(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        sid = client.post("/sessions", json={}).json()["id"]
        client.post(f"/sessions/{sid}/steps/manual", json={"code": "df = pl.DataFrame({'d': [1.5]})"})
        wait_idle(client, sid)
        body = {
            "id": "my-view",
            "name": "My view",
            "description": "one column",
            "tags": ["custom"],
            "source": SOURCE,
            "session_id": sid,
            "dataset": "df",
        }
        created = client.post("/components", json=body)
        assert created.status_code == 201, created.text
        manifest = created.json()
        assert manifest["origin"] == "generated"
        assert manifest["schema"]["requires"] == [{"role": "numeric", "dtype": "numeric", "min": 1}]
        assert (tmp_path / "components" / "my-view" / "component.tsx").read_text() == SOURCE
        listed = client.get("/components").json()
        assert "my-view" in {m["id"] for m in listed}
        assert client.post("/components", json=body).status_code == 409
        assert client.post("/components", json={**body, "id": "data-table"}).status_code == 409
        assert not (tmp_path / "components" / "data-table").exists()
        assert client.post("/components", json={**body, "id": "Bad Id"}).status_code == 400
        broken = client.post("/components", json={**body, "id": "broken", "source": "export default ("})
        assert broken.status_code == 400 and "transpile" in broken.json()["detail"]
        assert not (tmp_path / "components" / "broken").exists()
        missing = client.post("/components", json={**body, "id": "nods", "dataset": "nope"})
        assert missing.status_code == 404


def test_builtin_root_has_the_ids_the_tests_rely_on() -> None:
    assert (builtin_root() / "data-table" / "manifest.json").exists()
```

`make_client` builds the app with the default static dir; the transpile check needs `transpile-check.mjs` from the web build. If the Stage 2 test suite stubs the transpiler for route tests, reuse that stub here (grep `tests/server/test_app.py` for `transpiler`); otherwise skip the `broken` assertions when `default_transpiler(static).available` is false, matching how Stage 3's Task 9 tests handle it.

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/components tests/server/test_component_routes.py -q`
Expected: FAIL with import errors for the new names.

- [ ] **Step 3: Implement**

In `library.py`:

```python
import re
from quarry.projects.files import write_atomic

COMPONENT_ID_RE: Final = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}$")


def requirements_for(meta: DatasetMeta) -> list[SchemaRequirement]:
    """One requirement per dtype class the dataset has, so the library offers the component
    to datasets shaped like the one it was written against."""
    counts: dict[DtypeClass, int] = {"datetime": 0, "numeric": 0, "string": 0, "other": 0}
    for col in meta.schema_:
        counts[dtype_class(col.dtype)] += 1
    return [
        SchemaRequirement(role=cls, dtype=cls, min=counts[cls])
        for cls in ("datetime", "numeric", "string")
        if counts[cls] > 0
    ]


def write_component(root: Path, manifest: ComponentManifest, source: str) -> Path:
    """Write `manifest` and `source` under `root/<id>/`, returning that directory."""
    target = root / manifest.id
    write_atomic(target / "component.tsx", source)
    write_atomic(target / "manifest.json", manifest.model_dump_json(by_alias=True, indent=2))
    return target
```

(`Final` and `re` imports; `SchemaRequirement.dtype` is `Literal["datetime","numeric","string","any"]`, so the loop tuple is typed `tuple[Literal[...], ...]` or cast each `cls`.)

`src/quarry/server/component_routes.py`:

```python
"""Component library routes: list every library entry, save a generated component."""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from quarry.agent.transpile import Transpiler
from quarry.components.library import (
    COMPONENT_ID_RE,
    ComponentLibrary,
    ComponentManifest,
    ComponentSchema,
    requirements_for,
    write_component,
)
from quarry.server.models import now_iso
from quarry.server.service import SessionService


class SaveComponentRequest(BaseModel):
    id: str
    name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)
    source: str
    # The dataset the view was written against; its dtype classes become the schema requirement.
    session_id: str | None = None
    dataset: str | None = None


def register_component_routes(
    api: APIRouter,
    *,
    library: ComponentLibrary,
    researcher_root: Path,
    transpiler: Transpiler,
    sessions: SessionService,
) -> None:
    @api.get("/components")
    def list_components() -> list[ComponentManifest]:
        return [e.manifest for e in library.entries()]

    @api.post("/components", status_code=201)
    def save_component(body: SaveComponentRequest) -> ComponentManifest:
        if COMPONENT_ID_RE.match(body.id) is None:
            raise HTTPException(status_code=400, detail="ids are lowercase letters, digits and '-'")
        if library.get(body.id) is not None:
            raise HTTPException(status_code=409, detail=f"component {body.id!r} already exists")
        problem = transpiler.check(body.source)
        if problem is not None:
            raise HTTPException(status_code=400, detail=f"transpile error: {problem}")
        requires = []
        if body.session_id is not None and body.dataset is not None:
            try:
                sessions.get(body.session_id)  # KeyError before a kernel is spawned for a bad id
                listed = sessions.datasets(body.session_id)
            except KeyError as exc:
                raise HTTPException(status_code=404, detail="no such session") from exc
            meta = next((d for d in listed if d.name == body.dataset), None)
            if meta is None:
                raise HTTPException(status_code=404, detail=f"no dataset {body.dataset!r}")
            requires = requirements_for(meta)
        manifest = ComponentManifest(
            id=body.id,
            name=body.name,
            description=body.description,
            tags=body.tags,
            schema=ComponentSchema(requires=requires),
            origin="generated",
            created_at=now_iso(),
        )
        write_component(researcher_root, manifest, body.source)
        return manifest
```

In `app.py`, `create_app` keeps `roots`; after the session routes: `register_component_routes(api, library=service_library, researcher_root=config.root / "components", transpiler=transpiler, sessions=service)`, where `service_library` and `transpiler` are the objects already built for `SessionService` (bind them to local names before constructing the service). `SessionBusy` and `KernelDead` raised by `sessions.datasets` are already mapped by the app's exception handlers.

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/components tests/server -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests && git commit -m "feat: save generated views into the researcher's component library"
```

---

### Task 6: Notebook and script export, with CLI project commands

**Files:**

- Create: `src/quarry/projects/export.py`
- Modify: `src/quarry/server/project_routes.py` (two routes), `src/quarry/cli.py` (`projects` subcommands), `pyproject.toml` (`nbformat` dev dependency)
- Test: `tests/projects/test_export.py`, `tests/server/test_project_routes.py` (extend), `tests/test_cli.py` (extend)

**Interfaces:**

- Produces: `notebook(project: Project, store: ProjectStore) -> dict[str, Json]` (nbformat 4.5 document), `notebook_json(project, store) -> str`, `dataset_script(project, store, name) -> str`; `GET /projects/{slug}/export.ipynb` (JSON body, `Content-Disposition: attachment; filename="<slug>.ipynb"`), `GET /projects/{slug}/datasets/{name}/recipe.py` (`text/x-python` attachment, 404 unknown); `quarry projects list [--root]` and `quarry projects export <slug> [--root] [--out PATH]`.
- Consumes: `ProjectStore.get/read_recipe/read_view/parquet_path` (Stage 4 `store.py`), `SavedDatasetMeta`, `SavedViewMeta`, `SavedViewFiles` (Stage 4 `models.py`), `to_source` (Task 3), `_found` (`project_routes.py`), `main`/`run_serve` (`cli.py`).

Spec section 10 "Export": per dataset a markdown cell (name, description) and a code cell (recipe); per view a markdown cell (description), a code cell with the `to_source` rendering of its saved queries, and the TSX in a fenced block. Every dataset is emitted first, so a view never repeats a recipe. The saved queries carry no polars schema, so they render with `schema=None` and a leading comment says what that means.

- [ ] **Step 1: Dev dependency**

```bash
uv add --group dev "nbformat>=5.10"
```

- [ ] **Step 2: Failing tests**

`tests/projects/test_export.py`:

````python
import json
from pathlib import Path

import nbformat
import polars as pl

from quarry.projects.export import dataset_script, notebook, notebook_json
from quarry.projects.models import SavedDatasetMeta, SavedViewMeta
from quarry.projects.store import ProjectStore
from quarry.kernel.datasets import Column

RECIPE = "import polars as pl\nprices = pl.DataFrame({'ts': ['2024-01-02'], 'px': [1.0]})\n"
VIEW_SOURCE = "export default function V() { return null }"


def project_with_saved_items(root: Path) -> ProjectStore:
    store = ProjectStore(root)
    store.create("Momentum", "a study")
    meta = SavedDatasetMeta(
        name="prices",
        description="closing prices",
        backing="polars",
        schema=[Column(name="ts", dtype="String"), Column(name="px", dtype="Float64")],
        rows=1,
        mode="live",
        saved_at="2026-10-09T00:00:00Z",
        source_session="s",
        source_step="t",
        validated=True,
    )
    store.write_dataset("momentum", meta, recipe=RECIPE, raw=RECIPE)
    view = SavedViewMeta(
        name="table",
        description="the table",
        datasets=["prices"],
        component_id="data-table",
        saved_at="2026-10-09T00:00:00Z",
        source_session="s",
        source_step="t",
    )
    store.write_view(
        "momentum",
        view,
        source=VIEW_SOURCE,
        state={"limit": 5},
        queries=[{"dataset": "prices", "sort": [{"col": "ts"}], "limit": 5}, {"dataset": "prices", "limit": 0}],
    )
    return store


def test_notebook_validates_and_runs(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    doc = notebook(store.get("momentum"), store)
    nbformat.validate(nbformat.from_dict(doc))
    cells = [(c["cell_type"], c["source"]) for c in doc["cells"]]
    expected = [
        ("markdown", "# Momentum

a study"),
        ("markdown", "## prices

closing prices"),
        ("code", "import polars as pl"),
        ("markdown", "## View: table

the table"),
        ("code", "# Rendered from"),
        ("markdown", "```tsx
export default"),
    ]
    assert len(cells) == len(expected)
    for (kind, source), (want_kind, prefix) in zip(cells, expected, strict=True):
        assert kind == want_kind and source.startswith(prefix), (kind, source[:40])
    code = doc["cells"][4]["source"]
    assert code.startswith("# Rendered from the saved view's queries without a schema")
    assert "prices_1 = (" in code and "# query 2 could not be rendered:" in code
    namespace: dict[str, object] = {}
    for cell in doc["cells"]:
        if cell["cell_type"] == "code":
            exec(cell["source"], namespace)  # noqa: S102 - exported code must run
    assert isinstance(namespace["prices_1"], pl.DataFrame)
    assert len({c["id"] for c in doc["cells"]}) == len(doc["cells"])
    assert json.loads(notebook_json(store.get("momentum"), store))["nbformat"] == 4


def test_dataset_script_has_a_header_and_the_recipe(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    script = dataset_script(store.get("momentum"), store, "prices")
    assert script.startswith("# prices: closing prices\n# Saved from Quarry project Momentum")
    assert script.endswith(RECIPE)
    namespace: dict[str, object] = {}
    exec(script, namespace)  # noqa: S102
    assert isinstance(namespace["prices"], pl.DataFrame)


def test_pinned_dataset_script_mentions_the_parquet(tmp_path: Path) -> None:
    store = project_with_saved_items(tmp_path)
    saved = store.get("momentum").datasets[0].model_copy(update={"mode": "pinned"})
    store.write_dataset("momentum", saved, recipe=RECIPE, raw=RECIPE)
    script = dataset_script(store.get("momentum"), store, "prices")
    assert "data.parquet" in script and "pl.read_parquet(" in script
````

Append to `tests/server/test_project_routes.py` (reuse that file's `saved_project`-style setup; if it lives in `test_recall.py`, import it from there):

```python
def test_export_routes(tmp_path: Path) -> None:
    client, _ = saved_project(tmp_path, "live")
    nb = client.get("/projects/p/export.ipynb")
    assert nb.status_code == 200
    assert nb.headers["content-disposition"] == 'attachment; filename="p.ipynb"'
    assert nb.json()["nbformat"] == 4 and any(c["cell_type"] == "code" for c in nb.json()["cells"])
    script = client.get("/projects/p/datasets/prices/recipe.py")
    assert script.status_code == 200 and script.headers["content-type"].startswith("text/x-python")
    assert "prices = " in script.text
    assert client.get("/projects/p/datasets/nope/recipe.py").status_code == 404
    assert client.get("/projects/nope/export.ipynb").status_code == 404
```

Append to `tests/test_cli.py`:

```python
def test_projects_list_and_export(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from tests.projects.test_export import project_with_saved_items

    project_with_saved_items(tmp_path)
    assert main(["projects", "list", "--root", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "momentum" in out and "Momentum" in out
    target = tmp_path / "out.ipynb"
    assert main(["projects", "export", "momentum", "--root", str(tmp_path), "--out", str(target)]) == 0
    assert json.loads(target.read_text())["nbformat"] == 4
    assert main(["projects", "export", "nope", "--root", str(tmp_path)]) == 1
    assert "no such project" in capsys.readouterr().err
```

- [ ] **Step 3: Run them to see them fail**

Run: `uv run pytest tests/projects/test_export.py tests/test_cli.py -q`
Expected: FAIL with `ModuleNotFoundError: quarry.projects.export`, then `projects` is not a known command.

- [ ] **Step 4: Implement**

`src/quarry/projects/export.py`:

````python
"""Export a project as a Jupyter notebook, or one saved dataset as a Python script."""

from __future__ import annotations

import json
import uuid

from pydantic import ValidationError

from quarry.projects.models import Project, SavedDatasetMeta, SavedViewMeta
from quarry.projects.store import ProjectStore
from quarry.query.spec import Json, QueryError, QuerySpec
from quarry.query.source_target import to_source

NO_SCHEMA_NOTE = (
    "# Rendered from the saved view's queries without a schema: literals are as the view sent\n"
    "# them, and integer sums are plain, so an Int64 sum can wrap. Run \"To code\" in a session\n"
    "# for a rendering against the live schema.\n"
)


def notebook(project: Project, store: ProjectStore) -> dict[str, Json]:
    """An nbformat 4.5 document: every saved dataset, then every saved view."""
    cells: list[dict[str, Json]] = [
        _markdown(f"# {project.meta.name}\n\n{project.meta.description}".rstrip() + "\n")
    ]
    for dataset in project.datasets:
        cells.append(_markdown(_dataset_heading(dataset)))
        cells.append(_code(store.read_recipe(project.meta.slug, dataset.name)))
    for view in project.views:
        saved = store.read_view(project.meta.slug, view.name)
        cells.append(_markdown(_view_heading(view)))
        cells.append(_code(_queries_source(saved.queries, _backings(project))))
        cells.append(_markdown(f"```tsx\n{saved.source.rstrip()}\n```\n"))
    return {
        "nbformat": 4,
        "nbformat_minor": 5,
        "metadata": {
            "kernelspec": {"name": "python3", "display_name": "Python 3", "language": "python"},
            "language_info": {"name": "python"},
        },
        "cells": cells,
    }


def notebook_json(project: Project, store: ProjectStore) -> str:
    return json.dumps(notebook(project, store), indent=1, ensure_ascii=False) + "\n"


def dataset_script(project: Project, store: ProjectStore, name: str) -> str:
    """The recipe as a standalone script; a pinned dataset also notes its parquet file."""
    saved = next((d for d in project.datasets if d.name == name), None)
    if saved is None:
        raise KeyError(name)
    lines = [f"# {saved.name}: {saved.description}".rstrip(": "), f"# Saved from Quarry project {project.meta.name} on {saved.saved_at}"]
    if saved.mode == "pinned":
        path = store.parquet_path(project.meta.slug, name)
        lines.append(f"# Pinned copy: {name} = pl.read_parquet({str(path)!r})")
    if not saved.validated:
        lines.append(f"# Not validated: {saved.validation_error}")
    return "\n".join(lines) + "\n\n" + store.read_recipe(project.meta.slug, name)


def _queries_source(queries: list[dict[str, Json]], backings: dict[str, str]) -> str:
    blocks = [NO_SCHEMA_NOTE]
    for n, raw in enumerate(queries, start=1):
        try:
            spec = QuerySpec.model_validate(raw)
            backing = backings.get(spec.dataset, "polars")
            blocks.append(to_source(spec, backing, result_name=f"{spec.dataset}_{n}"))  # type: ignore[arg-type]
        except (ValidationError, QueryError) as exc:
            blocks.append(f"# query {n} could not be rendered: {exc}\n")
    return "\n".join(blocks)


def _backings(project: Project) -> dict[str, str]:
    return {d.name: d.backing for d in project.datasets}


def _dataset_heading(d: SavedDatasetMeta) -> str:
    detail = f"{d.description}\n\n" if d.description else ""
    status = "validated" if d.validated else f"not validated: {d.validation_error}"
    return f"## {d.name}\n\n{detail}{d.mode}, {d.rows if d.rows is not None else '?'} rows, {status}\n"


def _view_heading(v: SavedViewMeta) -> str:
    detail = f"{v.description}\n\n" if v.description else ""
    return f"## View: {v.name}\n\n{detail}Component `{v.component_id}` over {', '.join(v.datasets)}.\n"


def _markdown(source: str) -> dict[str, Json]:
    return {"id": uuid.uuid4().hex[:8], "cell_type": "markdown", "metadata": {}, "source": source}


def _code(source: str) -> dict[str, Json]:
    return {
        "id": uuid.uuid4().hex[:8],
        "cell_type": "code",
        "metadata": {},
        "execution_count": None,
        "outputs": [],
        "source": source,
    }
````

Type `_backings` as `dict[str, Backing]` (import `Backing` from `quarry.query.spec`) and drop the `type: ignore`; `SavedDatasetMeta.backing` is already a `Backing`. The ordering guarantee the test checks (`# Momentum`, `## prices`, recipe, `## View: table`, queries, fenced TSX) is the spec's order with the project heading first.

In `project_routes.py` add:

```python
from fastapi.responses import JSONResponse, PlainTextResponse
from quarry.projects.export import dataset_script, notebook

    @api.get("/projects/{slug}/export.ipynb")
    def export_notebook(slug: str) -> JSONResponse:
        project = _found(lambda: projects.get(slug))
        headers = {"Content-Disposition": f'attachment; filename="{slug}.ipynb"'}
        return JSONResponse(notebook(project, projects.store), headers=headers)

    @api.get("/projects/{slug}/datasets/{name}/recipe.py")
    def export_recipe(slug: str, name: str) -> PlainTextResponse:
        project = _found(lambda: projects.get(slug))
        script = _found(lambda: dataset_script(project, projects.store, name))
        headers = {"Content-Disposition": f'attachment; filename="{name}.py"'}
        return PlainTextResponse(script, media_type="text/x-python", headers=headers)
```

`ProjectService` exposes its store as a read-only property `store` (add `@property def store(self) -> ProjectStore: return self._store` in `server/projects.py`).

In `cli.py`, extend `main`:

```python
    projects = sub.add_parser("projects", help="list or export saved projects")
    project_sub = projects.add_subparsers(dest="project_command")
    # On each leaf parser, so `quarry projects list --root X` parses: argparse hands the
    # remaining arguments to the leaf, which must know the option.
    with_root = argparse.ArgumentParser(add_help=False)
    with_root.add_argument("--root", type=Path, default=Path("~/.quarry"))
    project_sub.add_parser("list", parents=[with_root], help="list projects under the root")
    export = project_sub.add_parser(
        "export", parents=[with_root], help="write a project as a Jupyter notebook"
    )
    export.add_argument("slug")
    export.add_argument("--out", type=Path, default=None, help="defaults to <slug>.ipynb here")
    args = parser.parse_args(argv)
    if args.command == "serve":
        return run_serve(port=args.port or free_port(), root=args.root.expanduser(), host_hint=args.host_hint)
    if args.command == "projects" and args.project_command == "list":
        return run_projects_list(root=args.root.expanduser())
    if args.command == "projects" and args.project_command == "export":
        return run_projects_export(root=args.root.expanduser(), slug=args.slug, out=args.out)
    parser.print_usage(sys.stderr)
    return 2
```

Add:

```python
def run_projects_list(*, root: Path) -> int:
    store = ProjectStore(root)
    for meta in store.list():
        print(f"{meta.slug}\t{meta.name}\t{meta.updated_at}")
    return 0


def run_projects_export(*, root: Path, slug: str, out: Path | None) -> int:
    store = ProjectStore(root)
    try:
        project = store.get(slug)
    except KeyError:
        print(f"no such project: {slug}", file=sys.stderr)
        return 1
    target = out if out is not None else Path(f"{slug}.ipynb")
    target.write_text(notebook_json(project, store), encoding="utf-8")
    print(f"wrote {target}")
    return 0
```

with `from quarry.projects.export import notebook_json` and `from quarry.projects.store import ProjectStore`. `ProjectStore(root)` on a root with no `projects/` directory must list nothing rather than raise; check Stage 4's `list()` and guard with `if not dir.exists(): return []` if it does not already.

- [ ] **Step 5: Verify and commit**

```bash
uv run pytest tests/projects tests/server tests/test_cli.py -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add pyproject.toml uv.lock src tests && git commit -m "feat: export projects as notebooks and scripts"
```

---

### Task 7: Opt-in licensed libraries: mounts, status route, startup warning

**Files:**

- Create: `src/quarry/server/libraries.py`
- Modify: `src/quarry/agent/context.py` (`enabled_libraries` uses `licensed_libraries`), `src/quarry/server/app.py` (mounts and route), `web/src/shared/api-types.ts` (`LibraryStatus`)
- Test: `tests/server/test_libraries.py`, `tests/agent/test_context.py` (one case changes)

**Interfaces:**

- Produces: `LibraryStatus(BaseModel){id: Literal["highcharts","scichart"], enabled: bool, reason: str | None, license: str | None, entry: str | None}`; `licensed_libraries(config) -> list[LibraryStatus]`; `mount_licensed(app, config) -> None`; `GET /libraries` → `list[LibraryStatus]`; `enabled_libraries(config, available=None)` adds a licensed id only when its status is enabled.
- Consumes: `LibrariesConfig` (`config.py`), `STATIC_PREFIXES` and the static CORS middleware (Stage 3 Task 9 Step 2b; if absent on the branch, Task 2 added it), `runtime_libraries` (Stage 3 Task 3).

Highcharts ships `highstock.js` (UMD, sets `window.Highcharts`) at its package root; SciChart ships a self-contained ESM bundle `index.min.mjs` and its wasm under `_wasm/`. The runtime (Task 8) loads `/libs/highcharts/highstock.js` as a classic script and `/libs/scichart/index.min.mjs` as a module, and points SciChart's `wasmUrl` at `/libs/scichart/_wasm/scichart.wasm`. The `entry` field tells it which file to load, so the Python side owns the file names.

- [ ] **Step 1: Failing tests**

`tests/server/test_libraries.py`:

```python
import logging
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from quarry.agent.context import enabled_libraries
from quarry.config import LibrariesConfig, QuarryConfig
from quarry.server.libraries import licensed_libraries
from tests.server.test_app import TOKEN, make_client


def config_with(tmp_path: Path, **libraries: str | Path) -> QuarryConfig:
    return QuarryConfig(root=tmp_path, libraries=LibrariesConfig(**libraries))


def fake_package(root: Path, name: str, entry: str) -> Path:
    pkg = root / name
    pkg.mkdir(parents=True)
    (pkg / entry).write_text("// stub")
    return pkg


def test_license_without_path_stays_disabled_with_a_warning(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    config = config_with(tmp_path, scichart_license="abc")
    with caplog.at_level(logging.WARNING, logger="quarry.server.libraries"):
        statuses = licensed_libraries(config)
    scichart = next(s for s in statuses if s.id == "scichart")
    assert scichart.enabled is False and scichart.license is None
    assert scichart.reason == "scichart_path is not set"
    assert "scichart" in caplog.text and "abc" not in caplog.text
    assert "scichart" not in enabled_libraries(config)


def test_missing_path_is_reported_and_disabled(tmp_path: Path) -> None:
    config = config_with(tmp_path, highcharts_license="k", highcharts_path=tmp_path / "nope")
    status = next(s for s in licensed_libraries(config) if s.id == "highcharts")
    assert status.enabled is False and "does not exist" in (status.reason or "")


def test_enabled_library_is_mounted_with_cors_and_listed(tmp_path: Path) -> None:
    hc = fake_package(tmp_path, "highcharts", "highstock.js")
    sc = fake_package(tmp_path, "scichart", "index.min.mjs")
    config = config_with(
        tmp_path, highcharts_license="k1", highcharts_path=hc, scichart_license="k2", scichart_path=sc
    )
    with make_client(tmp_path, [], config=config) as client:
        listed = {s["id"]: s for s in client.get("/libraries").json()}
        assert listed["highcharts"] == {
            "id": "highcharts", "enabled": True, "reason": None, "license": "k1", "entry": "/libs/highcharts/highstock.js",
        }
        assert listed["scichart"]["entry"] == "/libs/scichart/index.min.mjs"
        served = client.get("/libs/highcharts/highstock.js")
        assert served.status_code == 200 and served.headers["access-control-allow-origin"] == "*"
    bare = TestClient(client.app)  # no Authorization header at all
    assert bare.get("/libraries").status_code == 401
    assert enabled_libraries(config) == [*enabled_libraries(QuarryConfig(root=tmp_path)), "highcharts", "scichart"]


def test_unlicensed_library_is_not_mounted(tmp_path: Path) -> None:
    with make_client(tmp_path, []) as client:
        assert client.get("/libs/highcharts/highstock.js").status_code == 404
        assert all(s["enabled"] is False for s in client.get("/libraries").json())
```

`make_client` in `tests/server/test_app.py` already accepts `config=`; `TestClient` merges per-call headers with its defaults, so the 401 check uses a second client built on the same app with no token. Import `TestClient` from `fastapi.testclient`.

In `tests/agent/test_context.py`, `test_enabled_libraries` sets only `highcharts_license` and expects `"highcharts"` in the result; change it to also set `highcharts_path` to an existing temp directory (and assert the license-only config excludes it).

- [ ] **Step 2: Run them to see them fail**

Run: `uv run pytest tests/server/test_libraries.py tests/agent/test_context.py -q`
Expected: FAIL with `ModuleNotFoundError: quarry.server.libraries`.

- [ ] **Step 3: Implement**

`src/quarry/server/libraries.py`:

```python
"""Opt-in licensed chart libraries: which are usable, and how the server serves them."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Final, Literal

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from quarry.config import QuarryConfig

log = logging.getLogger(__name__)

LibraryId = Literal["highcharts", "scichart"]
# The file the runtime loads from the mounted package. Highcharts is a classic UMD script that
# sets window.Highcharts; SciChart is a self-contained ES module with its wasm beside it.
ENTRIES: Final[dict[LibraryId, str]] = {
    "highcharts": "highstock.js",
    "scichart": "index.min.mjs",
}


class LibraryStatus(BaseModel):
    id: LibraryId
    enabled: bool
    reason: str | None = None
    # Sent to the browser, which hands it to the library at load time; never logged.
    license: str | None = None
    entry: str | None = None


def licensed_libraries(config: QuarryConfig) -> list[LibraryStatus]:
    """One status per licensed library; a key without a usable path logs a warning."""
    return [_status("highcharts", config), _status("scichart", config)]


def mount_licensed(app: FastAPI, config: QuarryConfig) -> None:
    """Serve each enabled library's package directory under /libs/<id>/."""
    for status in licensed_libraries(config):
        if status.enabled:
            path = _path(status.id, config)
            app.mount(f"/libs/{status.id}", StaticFiles(directory=str(path)), name=f"lib-{status.id}")


def _status(library: LibraryId, config: QuarryConfig) -> LibraryStatus:
    key = getattr(config.libraries, f"{library}_license")
    if not key:
        return LibraryStatus(id=library, enabled=False, reason=f"{library}_license is not set")
    path = _path(library, config)
    if path is None:
        reason = f"{library}_path is not set"
    elif not (path / ENTRIES[library]).is_file():
        reason = f"{library}_path {path} does not exist or lacks {ENTRIES[library]}"
    else:
        return LibraryStatus(
            id=library, enabled=True, license=key, entry=f"/libs/{library}/{ENTRIES[library]}"
        )
    log.warning("%s has a license key but is disabled: %s", library, reason)
    return LibraryStatus(id=library, enabled=False, reason=reason)


def _path(library: LibraryId, config: QuarryConfig) -> Path | None:
    path: Path | None = getattr(config.libraries, f"{library}_path")
    return path
```

In `agent/context.py`, `enabled_libraries` keeps its signature and replaces the two `if config.libraries.*_license` checks with:

```python
    extra = [s.id for s in licensed_libraries(config) if s.enabled]
```

(import from `quarry.server.libraries`; `agent` importing `server` is a new edge, so if `server.libraries` ever imports `agent`, move `LibraryStatus` and `licensed_libraries` to `quarry/libraries.py` instead and have both import from there. Prefer that location from the start if the import graph check in `tests/test_imports.py` exists on the branch.)

In `app.py`: after the static CORS middleware is installed and before the final static mount, call `mount_licensed(app, config)`, and add:

```python
    @api.get("/libraries")
    def libraries() -> list[LibraryStatus]:
        return licensed_libraries(config)
```

`licensed_libraries` is called once at startup by `enabled_libraries` and once by `mount_licensed`, so a key without a path warns twice; compute `statuses = licensed_libraries(config)` once in `create_app`, pass it to a `mount_licensed(app, config, statuses)` variant and to `enabled_libraries(config, available, statuses=statuses)` if the double warning bothers the reviewer. Either way the route may recompute.

Append to `web/src/shared/api-types.ts`:

```ts
export interface LibraryStatus {
  id: "highcharts" | "scichart";
  enabled: boolean;
  reason: string | null;
  license: string | null;
  entry: string | null;
}
```

- [ ] **Step 4: Verify and commit**

```bash
uv run pytest tests/server tests/agent -q && uv run ruff check src tests && uv run ruff format src tests && uv run mypy src
git add src tests web && git commit -m "feat: serve licensed chart libraries from local installs"
```

---

### Task 8: Runtime module table, licensed loaders, and the library guide

**Files:**

- Modify: `web/package.json`, `web/src/runtime/modules.ts`, `web/src/runtime/libraries.ts`, `web/src/runtime/mount.tsx` (register licensed libraries at mount), `web/src/shared/bridge-types.ts` (`mount.licensed`), `web/src/host/bridge/HostBridge.ts` (`MountSpec.licensed`), `web/src/host/containers/ViewHost.tsx` (pass enabled libraries), `web/src/host/api/client.ts`, `web/src/host/api/keys.ts`, `web/src/host/api/hooks.ts` (`useLibraries`), `src/quarry/agent/guide.md`, `web/vite.config.ts` and `web/tsconfig.app.json` (`@quarry/highcharts` alias)
- Create: `web/src/runtime/libs/registry.ts`, `web/src/runtime/libs/highcharts.ts`, `web/src/runtime/libs/HighchartsReact.tsx`, `web/src/runtime/libs/scichart.ts`
- Test: `web/src/runtime/libs/registry.test.ts`, `web/src/runtime/libs/highcharts.test.ts`, `web/src/runtime/modules.test.ts`, `tests/agent/test_context.py` (guide headings)

**Interfaces:**

- Produces: `LicensedLibrary { id: "highcharts" | "scichart"; entry: string; license: string | null }`; `setLicensed(list)`, `licensed(id): LicensedLibrary | null` (runtime registry); `loadHighstock(): Promise<object>`, `loadScichart(): Promise<object>`; `HighchartsReact` props `{ options: object; constructorType?: "chart" | "stockChart"; className?: string }`; `MODULES` with every spec library; `RUNTIME_LIBRARIES` listing all ten ids; `useLibraries()` (React Query over `GET /libraries`, never refetched).
- Consumes: `MODULES`, `loadComponent` (Stage 3 Task 4), `createRuntime` (Stage 3 Task 6), `HostBridge.mount` (Stage 3 Task 7), `ViewHost` (Stage 4 Task 8), `LibraryStatus` (Task 7), `GUIDE_PATH`/`_guide_for` (`context.py`).

- [ ] **Step 1: Dependencies**

```bash
cd web && npm install plotly.js-dist-min@4.1.2 react-plotly.js@4.1.0 echarts@6.1.0 echarts-for-react@3.0.6 recharts@3.10.1 @tanstack/react-table@9.2.8 d3@7.9.0
npm install -D @types/d3@7.4.3 @types/plotly.js@3.0.15 @types/react-plotly.js@2.6.4
```

- [ ] **Step 2: Failing tests**

`web/src/runtime/libs/registry.test.ts`:

```ts
import { beforeEach, describe, expect, it } from "vitest";
import { licensed, setLicensed } from "./registry";

describe("licensed library registry", () => {
  beforeEach(() => setLicensed([]));

  it("answers null until the host registers a library", () => {
    expect(licensed("highcharts")).toBeNull();
    setLicensed([
      {
        id: "highcharts",
        entry: "/libs/highcharts/highstock.js",
        license: null,
      },
    ]);
    expect(licensed("highcharts")?.entry).toBe("/libs/highcharts/highstock.js");
    expect(licensed("scichart")).toBeNull();
  });
});
```

`web/src/runtime/libs/highcharts.test.ts`:

```ts
import { afterEach, describe, expect, it } from "vitest";
import { loadHighstock } from "./highcharts";
import { setLicensed } from "./registry";

describe("loadHighstock", () => {
  afterEach(() => {
    setLicensed([]);
    delete (window as { Highcharts?: unknown }).Highcharts;
  });

  it("refuses when the library is not enabled", async () => {
    await expect(loadHighstock()).rejects.toThrow(/highcharts is not enabled/);
  });

  it("inserts the entry script once and resolves to the global", async () => {
    setLicensed([
      {
        id: "highcharts",
        entry: "/libs/highcharts/highstock.js",
        license: null,
      },
    ]);
    const pending = loadHighstock();
    const script = document.querySelector<HTMLScriptElement>(
      'script[src="/libs/highcharts/highstock.js"]',
    );
    expect(script).not.toBeNull();
    (window as { Highcharts?: unknown }).Highcharts = {
      stockChart: () => ({}),
    };
    script?.dispatchEvent(new Event("load"));
    const mod = (await pending) as { default: { stockChart: unknown } };
    expect(typeof mod.default.stockChart).toBe("function");
    await loadHighstock();
    expect(document.querySelectorAll("script[src*='highstock']").length).toBe(
      1,
    );
  });
});
```

`web/src/runtime/modules.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { RUNTIME_LIBRARIES } from "./libraries";
import { MODULES } from "./modules";

describe("runtime module table", () => {
  it("resolves every import the library guide names", () => {
    for (const name of [
      "react",
      "@quarry/hooks",
      "@quarry/perspective",
      "@quarry/highcharts",
      "ag-grid-react",
      "lightweight-charts",
      "react-plotly.js",
      "echarts-for-react",
      "echarts",
      "recharts",
      "@tanstack/react-table",
      "d3",
      "highcharts/highstock",
      "scichart",
    ])
      expect(MODULES[name], name).toBeTypeOf("function");
  });

  it("advertises every library id the guide has a section for", () => {
    expect([...RUNTIME_LIBRARIES].sort()).toEqual(
      [
        "ag-grid",
        "d3",
        "echarts",
        "highcharts",
        "lightweight-charts",
        "perspective",
        "plotly",
        "recharts",
        "scichart",
        "tanstack-table",
      ].sort(),
    );
  });
});
```

- [ ] **Step 3: Implement the registry and loaders**

`web/src/runtime/libs/registry.ts`:

```ts
import type { LicensedLibrary } from "@/shared/api-types";

let registered: LicensedLibrary[] = [];

/** The host passes the enabled licensed libraries with every mount. */
export function setLicensed(list: LicensedLibrary[]): void {
  registered = list;
}

export function licensed(id: LicensedLibrary["id"]): LicensedLibrary | null {
  return registered.find((l) => l.id === id) ?? null;
}

export function notEnabled(id: LicensedLibrary["id"]): Error {
  return new Error(
    `${id} is not enabled on this server; set libraries.${id}_license and libraries.${id}_path in config.toml`,
  );
}
```

`web/src/runtime/libs/highcharts.ts`:

```ts
import { licensed, notEnabled } from "./registry";

declare global {
  interface Window {
    Highcharts?: object;
  }
}

let loading: Promise<object> | null = null;

/** Highstock is a classic UMD script; a module import would pull hundreds of ESM files. */
export function loadHighstock(): Promise<object> {
  const lib = licensed("highcharts");
  if (lib === null) return Promise.reject(notEnabled("highcharts"));
  loading ??= new Promise<object>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = lib.entry;
    script.onload = () => {
      const global = window.Highcharts;
      if (global === undefined) {
        reject(
          new Error(`${lib.entry} loaded but defined no Highcharts global`),
        );
        return;
      }
      resolve({ __esModule: true, default: global, ...global });
    };
    script.onerror = () => reject(new Error(`could not load ${lib.entry}`));
    document.head.append(script);
  });
  return loading;
}
```

`web/src/runtime/libs/HighchartsReact.tsx` (replaces `highcharts-react-official`, which would need Highcharts as a bundled peer):

```tsx
import { useEffect, useRef } from "react";
import { loadHighstock } from "./highcharts";

interface ChartLike {
  update(options: object, redraw?: boolean): void;
  destroy(): void;
}

interface HighchartsLike {
  chart(el: HTMLElement, options: object): ChartLike;
  stockChart(el: HTMLElement, options: object): ChartLike;
}

interface HighchartsReactProps {
  options: object;
  constructorType?: "chart" | "stockChart";
  className?: string;
}

export function HighchartsReact({
  options,
  constructorType = "stockChart",
  className,
}: HighchartsReactProps) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<ChartLike | null>(null);

  useEffect(() => {
    const el = host.current;
    if (el === null) return;
    let cancelled = false;
    void loadHighstock().then((mod) => {
      if (cancelled) return;
      const hc = (mod as { default: HighchartsLike }).default;
      chart.current = hc[constructorType](el, options);
    });
    return () => {
      cancelled = true;
      chart.current?.destroy();
      chart.current = null;
    };
    // Options changes update in place below; recreating is only for the constructor type.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [constructorType]);

  useEffect(() => {
    chart.current?.update(options, true);
  }, [options]);

  return <div ref={host} className={className ?? "h-full w-full"} />;
}
```

`web/src/runtime/libs/scichart.ts`:

```ts
import { licensed, notEnabled } from "./registry";

interface SciChartLike {
  SciChartSurface: {
    configure(config: { wasmUrl: string }): void;
    setRuntimeLicenseKey(key: string): void;
  };
}

let loading: Promise<object> | null = null;

/** SciChart's single-file ES module, served from the researcher's install under /libs/. */
export function loadScichart(): Promise<object> {
  const lib = licensed("scichart");
  if (lib === null) return Promise.reject(notEnabled("scichart"));
  loading ??= import(/* @vite-ignore */ lib.entry).then((mod: unknown) => {
    const sc = mod as SciChartLike;
    const base = lib.entry.slice(0, lib.entry.lastIndexOf("/") + 1);
    sc.SciChartSurface.configure({ wasmUrl: `${base}_wasm/scichart.wasm` });
    if (lib.license !== null)
      sc.SciChartSurface.setRuntimeLicenseKey(lib.license);
    return { __esModule: true, ...(mod as object) };
  });
  return loading;
}
```

SciChart 6.0.6 types `setRuntimeLicenseKey` and `configure` as statics on `SciChartSurface`; the local interface keeps the runtime free of the package.

Replace `MODULES` in `web/src/runtime/modules.ts` with:

```ts
import type { ModuleTable } from "./loader";
import { loadHighstock } from "./libs/highcharts";
import { loadScichart } from "./libs/scichart";

// Sucrase's interop reads `__esModule`; spreading the namespace gives it a plain object.
const esm = (ns: object): object => ({ __esModule: true, ...ns });

const plotly = async (): Promise<object> => {
  const [factory, lib] = await Promise.all([
    import("react-plotly.js/factory"),
    import("plotly.js-dist-min"),
  ]);
  return esm({ default: factory.default(lib.default) });
};

export const MODULES: ModuleTable = {
  react: () => import("react").then(esm),
  "react/jsx-runtime": () => import("react/jsx-runtime").then(esm),
  "@quarry/hooks": () => import("./hooks").then(esm),
  "@quarry/perspective": () => import("./perspective").then(esm),
  "@quarry/highcharts": () => import("./libs/HighchartsReact").then(esm),
  "@/components/ui/button": () => import("@/components/ui/button").then(esm),
  "@/components/ui/badge": () => import("@/components/ui/badge").then(esm),
  "@/components/ui/input": () => import("@/components/ui/input").then(esm),
  "@/components/ui/select": () => import("@/components/ui/select").then(esm),
  "@/components/ui/separator": () =>
    import("@/components/ui/separator").then(esm),
  "@/components/ui/tabs": () => import("@/components/ui/tabs").then(esm),
  "@/components/ui/tooltip": () => import("@/components/ui/tooltip").then(esm),
  "ag-grid-react": () => import("ag-grid-react").then(esm),
  "ag-grid-community": () => import("ag-grid-community").then(esm),
  "lightweight-charts": () => import("lightweight-charts").then(esm),
  "react-plotly.js": plotly,
  "echarts-for-react": () => import("echarts-for-react").then(esm),
  echarts: () => import("echarts").then(esm),
  recharts: () => import("recharts").then(esm),
  "@tanstack/react-table": () => import("@tanstack/react-table").then(esm),
  d3: () => import("d3").then(esm),
  "highcharts/highstock": loadHighstock,
  scichart: loadScichart,
};
```

`plotly.js-dist-min` has no types of its own; add `web/src/types/plotly-dist-min.d.ts` with `declare module "plotly.js-dist-min" { const plotly: object; export default plotly; }` and include `src/types` in `tsconfig.app.json`. `react-plotly.js/factory` is typed by `@types/react-plotly.js` as `(plotly: object) => ComponentType<PlotParams>`.

`web/src/runtime/libraries.ts`:

```ts
export const RUNTIME_LIBRARIES = [
  "ag-grid",
  "lightweight-charts",
  "perspective",
  "plotly",
  "echarts",
  "recharts",
  "tanstack-table",
  "d3",
  "highcharts",
  "scichart",
] as const;
export type RuntimeLibrary = (typeof RUNTIME_LIBRARIES)[number];
```

Vite config: add `"@quarry/highcharts": path.resolve(root, "./src/runtime/libs/HighchartsReact.tsx")` to the aliases (vite and vitest configs) and `tsconfig.app.json` `paths`.

- [ ] **Step 4: Carry the enabled libraries through the bridge**

Add to `web/src/shared/api-types.ts` (the registry imports it from there, so `shared/` never imports `runtime/`):

```ts
export interface LicensedLibrary {
  id: "highcharts" | "scichart";
  entry: string;
  license: string | null;
}
```

`web/src/shared/bridge-types.ts`: the `mount` member gains `licensed?: LicensedLibrary[]`.

`HostBridge.MountSpec` gains `licensed?: LicensedLibrary[]`, passed through in `flushMount`. In `createRuntime` (`mount.tsx`), the `mount` handler calls `setLicensed(message.licensed ?? [])` before `loadComponent`.

Host: `ApiClient.libraries(): Promise<LibraryStatus[]>` (`GET /libraries`), `keys.libraries()`, and:

```ts
export function useLibraries() {
  const api = useApi();
  return useQuery({
    queryKey: keys.libraries(),
    queryFn: () => api.libraries(),
    staleTime: Infinity,
  });
}
```

`ViewHost` calls `useLibraries()` and passes `licensed: enabled` to `bridge.mount`, where `enabled` is memoised from the query: `libraries.data?.filter((l) => l.enabled).map((l) => ({ id: l.id, entry: l.entry ?? "", license: l.license }))`. Mount waits for neither: an undefined list mounts with no licensed libraries, and `useLibraries` resolves before any view imports one in practice; to make it deterministic, include `enabled` in the mount effect's dependency list so a late answer remounts once. Add one `client.test.ts` case for `libraries()` (GET `/libraries`).

- [ ] **Step 5: Library guide**

Replace the import sentences in `src/quarry/agent/guide.md` so each matches the module table:

```markdown
## lightweight-charts

Price and return series, OHLC. Use when speed and a clean look matter more than annotations. Import `createChart`, `LineSeries`, `CandlestickSeries` from "lightweight-charts". Keep the attribution logo enabled.

## plotly

Scatter, heatmap, 3D, statistical plots, anything general. `import Plot from "react-plotly.js"`; pass `data`, `layout` and `useResizeHandler` with a sized container.

## echarts

Series with more than about 100k points, calendar and sankey. `import ReactECharts from "echarts-for-react"`; pass `option` and `style={{ height: "100%" }}`.

## recharts

Small aggregated bar and line charts inside shadcn layouts. Import `ResponsiveContainer`, `BarChart`, `LineChart`, `Bar`, `Line`, `XAxis`, `YAxis`, `Tooltip` from "recharts".

## perspective

When the researcher should drive pivots and filters directly. Import `PerspectiveViewer` from "@quarry/perspective". Query with `format: "arrow"` and pass the result's `arrow` buffer; read the viewer's config through `onConfig`.

## ag-grid

Tables with column filters and resizing. Import `AgGridReact` from "ag-grid-react" and `AllCommunityModule`, `ModuleRegistry`, `themeQuartz` from "ag-grid-community".

## tanstack-table

Tables that need custom cell rendering inside shadcn styling. TanStack Table v9: import `useTable`, `tableFeatures`, `rowSortingFeature`, `createColumnHelper` from "@tanstack/react-table"; render cells with `<table.FlexRender cell={cell} />`.

## d3

Only when nothing above fits. `import * as d3 from "d3"` and draw into a ref inside an effect.

## highcharts

Full stock charts: navigator, range selector, indicators, annotations. Import `HighchartsReact` from "@quarry/highcharts" and pass `options`; `import Highcharts from "highcharts/highstock"` only for static helpers.

## scichart

Very large series and realtime rendering. Import `SciChartSurface`, `NumericAxis`, `FastLineRenderableSeries`, `XyDataSeries` from "scichart" and create the surface in an effect; the runtime has already configured the wasm path and license.
```

Keep the `## <id>` headings exactly; `_guide_for` filters by them and the `tests/agent/test_context.py` guide tests check the filtered output. Add one assertion there that `_guide_for(["perspective"])` mentions `@quarry/perspective`.

- [ ] **Step 6: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && npm run build && cd ..
uv run pytest tests/agent -q
git add web src && git commit -m "feat: resolve every chart library the guide names in the runtime"
```

---

### Task 9: Perspective config to query spec, and the pivot built-in

**Files:**

- Create: `web/src/runtime/perspective/toSpec.ts`, `src/quarry/components/builtin/pivot/manifest.json`, `src/quarry/components/builtin/pivot/component.tsx`
- Modify: `web/src/runtime/perspective/index.ts` (export `perspectiveToSpec`), `web/src/runtime/perspective/PerspectiveViewer.tsx` (restore on `config` change), `docs/context/decisions.md`
- Test: `web/src/runtime/perspective/toSpec.test.ts`, `web/src/builtins/pivot.test.tsx`, `tests/components/test_builtin.py` (extend)

**Interfaces:**

- Produces: `perspectiveToSpec(dataset: string, config: ViewerConfigUpdate): { spec: QuerySpec; dropped: string[] }`; built-in `pivot` with view state keys `perspective` (the saved config), `dropped` (strings).
- Consumes: `PerspectiveViewer`, `ensureEngine` (Task 2), `useQuery` with `arrow` (Task 2), `QuerySpec`, `Filter`, `Agg`, `Pivot` (`api-types.ts`).

Mapping, deterministic and recorded here as the decision:

| Perspective                                                        | QuerySpec                                                                                                                    |
| ------------------------------------------------------------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| `filter [col, op, term]` with `==` `!=` `<` `<=` `>` `>=`          | `eq ne lt le gt ge`                                                                                                          |
| `in`, `not in` (array term)                                        | `in`, `not_in`                                                                                                               |
| `contains`, `begins with`                                          | `contains`, `starts_with`                                                                                                    |
| `is null`, `is not null`                                           | `is_null`, `not_null`                                                                                                        |
| any other op (`ends with`, `is true`, ...)                         | dropped                                                                                                                      |
| `sort [col, "asc"                                                  | "desc"]`                                                                                                                     | `sort`; `col asc`, `desc abs`, `none` and the rest dropped |
| `group_by` with `aggregates` on `columns`                          | `group_by` + one `Agg` per column: `sum avg→mean min max count median first last` and `stddev→std`; other aggregates dropped |
| exactly one `split_by` and exactly one aggregated column           | `pivot {index: group_by, columns: split_by[0], values: col, agg}`                                                            |
| two or more `split_by`, or several aggregated columns with a split | `split_by` dropped, group_by kept                                                                                            |
| `columns` without `group_by`                                       | `select` (nulls and expression names skipped)                                                                                |
| `expressions`                                                      | dropped                                                                                                                      |

- [ ] **Step 1: Failing tests**

`web/src/runtime/perspective/toSpec.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { perspectiveToSpec } from "./toSpec";

describe("perspectiveToSpec", () => {
  it("maps columns, filters and sorts for a flat view", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      columns: ["a", "b", null],
      filter: [
        ["a", ">", 1],
        ["b", "in", ["x", "y"]],
        ["b", "begins with", "x"],
        ["b", "ends with", "y"],
        ["a", "is null", null],
      ],
      sort: [
        ["a", "desc"],
        ["b", "col asc"],
      ],
    });
    expect(spec).toEqual({
      dataset: "t",
      select: ["a", "b"],
      filters: [
        { col: "a", op: "gt", value: 1 },
        { col: "b", op: "in", value: ["x", "y"] },
        { col: "b", op: "starts_with", value: "x" },
        { col: "a", op: "is_null" },
      ],
      sort: [{ col: "a", desc: true }],
    });
    expect(dropped).toEqual(['filter b "ends with"', 'sort b "col asc"']);
  });

  it("maps group_by with aggregates, and one split_by to a pivot", () => {
    const grouped = perspectiveToSpec("t", {
      group_by: ["k"],
      columns: ["v", "w"],
      aggregates: { v: "sum", w: "avg" },
    });
    expect(grouped.spec).toEqual({
      dataset: "t",
      group_by: ["k"],
      aggs: [
        { col: "v", fn: "sum" },
        { col: "w", fn: "mean" },
      ],
    });
    const pivot = perspectiveToSpec("t", {
      group_by: ["k"],
      split_by: ["c"],
      columns: ["v"],
      aggregates: { v: "sum" },
    });
    expect(pivot.spec).toEqual({
      dataset: "t",
      pivot: { index: ["k"], columns: "c", values: "v", agg: "sum" },
    });
    expect(pivot.dropped).toEqual([]);
  });

  it("drops what the spec cannot express and says so", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      group_by: ["k"],
      split_by: ["c", "d"],
      columns: ["v", "w"],
      aggregates: { v: "distinct count", w: "sum" },
      expressions: { e: '"v" * 2' },
    });
    expect(spec).toEqual({
      dataset: "t",
      group_by: ["k"],
      aggs: [{ col: "w", fn: "sum" }],
    });
    expect(dropped).toEqual([
      "expression e",
      'aggregate v "distinct count"',
      "split_by c, d",
    ]);
  });

  it("defaults the aggregate to count when none is set", () => {
    const { spec } = perspectiveToSpec("t", {
      group_by: ["k"],
      columns: ["v"],
    });
    expect(spec.aggs).toEqual([{ col: "v", fn: "count" }]);
  });
});
```

`web/src/builtins/pivot.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const state = new Map<string, unknown>();
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    (state.get(key) as T | undefined) ?? initial,
    (next: T) => state.set(key, next),
  ],
  useDatasetSchema: () => null,
}));
vi.mock("@quarry/perspective", async () => ({
  PerspectiveViewer: () => <div data-testid="viewer" />,
  perspectiveToSpec: (await import("@/runtime/perspective/toSpec"))
    .perspectiveToSpec,
}));

import Pivot from "@builtin/pivot/component";

const success: QueryHookResult = {
  status: "success",
  rows: [],
  schema: [{ name: "a", dtype: "Int64" }],
  rowCount: 3,
  truncated: false,
  arrow: new ArrayBuffer(8),
};

describe("pivot built-in", () => {
  it("loads the dataset as arrow and records the mapped spec as a probe query", () => {
    state.set("perspective", {
      group_by: ["a"],
      columns: ["a", "b"],
      aggregates: { b: "sum" },
    });
    query.mockReturnValue(success);
    render(<Pivot datasets={["df"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "df",
      format: "arrow",
      limit: 50000,
    });
    expect(query).toHaveBeenCalledWith({
      dataset: "df",
      group_by: ["a"],
      aggs: [{ col: "b", fn: "sum" }],
      limit: 1,
    });
    expect(screen.getByTestId("viewer")).toBeTruthy();
  });

  it("lists what to code will leave out", () => {
    state.set("perspective", { expressions: { e: "1" } });
    query.mockReturnValue(success);
    render(<Pivot datasets={["df"]} />);
    expect(
      screen.getByText(/to code will leave out: expression e/i),
    ).toBeTruthy();
  });
});
```

Extend `tests/components/test_builtin.py` so the id set includes `"pivot"`.

- [ ] **Step 2: Run them to see them fail**

Run: `cd web && npx vitest run src/runtime/perspective src/builtins/pivot.test.tsx`
Expected: FAIL, `toSpec` and the built-in do not exist.

- [ ] **Step 3: Implement the mapping**

`web/src/runtime/perspective/toSpec.ts`:

```ts
import type { ViewerConfigUpdate } from "@finos/perspective-viewer";
import type { Agg, Filter, QuerySpec, Sort } from "@/shared/api-types";
import type { Json } from "@/shared/json";

const OPS: Record<string, Filter["op"]> = {
  "==": "eq",
  "!=": "ne",
  "<": "lt",
  "<=": "le",
  ">": "gt",
  ">=": "ge",
  in: "in",
  "not in": "not_in",
  contains: "contains",
  "begins with": "starts_with",
  "is null": "is_null",
  "is not null": "not_null",
};

const AGGS: Record<string, Agg["fn"]> = {
  sum: "sum",
  avg: "mean",
  min: "min",
  max: "max",
  count: "count",
  median: "median",
  stddev: "std",
  first: "first",
  last: "last",
};

export interface MappedSpec {
  spec: QuerySpec;
  dropped: string[];
}

/** Perspective's saved config as a query spec; what the spec cannot say is listed in `dropped`. */
export function perspectiveToSpec(
  dataset: string,
  config: ViewerConfigUpdate,
): MappedSpec {
  const dropped: string[] = [];
  const expressions = new Set(Object.keys(config.expressions ?? {}));
  for (const name of expressions) dropped.push(`expression ${name}`);
  const columns = (config.columns ?? []).filter(
    (c): c is string => c !== null && !expressions.has(c),
  );
  const filters: Filter[] = [];
  for (const [col, op, term] of config.filter ?? []) {
    const mapped = OPS[op];
    if (mapped === undefined || expressions.has(col)) {
      dropped.push(`filter ${col} "${op}"`);
      continue;
    }
    if (mapped === "is_null" || mapped === "not_null")
      filters.push({ col, op: mapped });
    else filters.push({ col, op: mapped, value: term as Json });
  }
  const sort: Sort[] = [];
  for (const [col, dir] of config.sort ?? []) {
    if ((dir === "asc" || dir === "desc") && !expressions.has(col))
      sort.push(dir === "desc" ? { col, desc: true } : { col });
    else dropped.push(`sort ${col} "${dir}"`);
  }
  const spec: QuerySpec = { dataset };
  if (filters.length > 0) spec.filters = filters;
  if (sort.length > 0) spec.sort = sort;
  const groupBy = config.group_by ?? [];
  if (groupBy.length === 0) {
    if (columns.length > 0) spec.select = columns;
    return { spec, dropped };
  }
  const aggs: Agg[] = [];
  for (const col of columns) {
    if (groupBy.includes(col)) continue;
    const raw = config.aggregates?.[col] ?? "count";
    const name = typeof raw === "string" ? raw : raw[0];
    const fn = AGGS[name];
    if (fn === undefined) dropped.push(`aggregate ${col} "${name}"`);
    else aggs.push({ col, fn });
  }
  const splitBy = config.split_by ?? [];
  const single = splitBy[0];
  const first = aggs[0];
  if (
    splitBy.length === 1 &&
    single !== undefined &&
    aggs.length === 1 &&
    first !== undefined
  ) {
    spec.pivot = {
      index: groupBy,
      columns: single,
      values: first.col,
      agg: first.fn,
    };
    return { spec, dropped };
  }
  if (splitBy.length > 0) dropped.push(`split_by ${splitBy.join(", ")}`);
  spec.group_by = groupBy;
  spec.aggs = aggs.length > 0 ? aggs : [{ col: groupBy[0] ?? "", fn: "count" }];
  return { spec, dropped };
}
```

The last line keeps the spec valid (`group_by` requires an agg) when every column is a group key; `count` of the first key is the least surprising stand-in. Add `export { perspectiveToSpec } from "./toSpec"; export type { MappedSpec } from "./toSpec";` to `perspective/index.ts`.

In `PerspectiveViewer.tsx`, add an effect that restores a changed `config` after load, ignoring echoes of its own `save()`:

```tsx
const applied = useRef<string>("");
useEffect(() => {
  const node = viewer.current;
  if (node === null || config === undefined) return;
  const key = JSON.stringify(config);
  if (key === applied.current) return;
  applied.current = key;
  void node.restore(config);
}, [config]);
```

and set `applied.current = JSON.stringify(saved)` inside `onUpdate` before calling `onConfig`.

- [ ] **Step 4: The pivot built-in**

`src/quarry/components/builtin/pivot/manifest.json`:

```json
{
  "id": "pivot",
  "name": "Pivot",
  "description": "Perspective viewer: drag columns to group, split, filter and sort; the result maps to a query spec for to code.",
  "tags": ["pivot", "explore", "group", "filter", "perspective"],
  "contract_version": 1,
  "schema": { "requires": [] },
  "origin": "builtin",
  "created_at": "2026-10-09T00:00:00Z"
}
```

`src/quarry/components/builtin/pivot/component.tsx`:

```tsx
import { useMemo } from "react";
import { useQuery, useViewState } from "@quarry/hooks";
import {
  PerspectiveViewer,
  perspectiveToSpec,
  type ViewerConfigUpdate,
} from "@quarry/perspective";

interface Props {
  datasets: string[];
}

const ROWS = 50000;

export default function Pivot({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const [config, setConfig] = useViewState<ViewerConfigUpdate | null>(
    "perspective",
    null,
  );
  const [dropped, setDropped] = useViewState<string[]>("dropped", []);
  const data = useQuery({ dataset, format: "arrow", limit: ROWS });
  const mapped = useMemo(
    () => perspectiveToSpec(dataset, config ?? {}),
    [dataset, config],
  );
  // One-row probe: the kernel validates the mapped spec and it is recorded for "to code".
  const probe = useQuery({ ...mapped.spec, limit: 1 });

  if (data.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (data.status === "error" || data.arrow === null)
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {data.status === "error" ? data.message : "no arrow data"}
      </pre>
    );

  const onConfig = (next: ViewerConfigUpdate) => {
    setConfig(next);
    const nextDropped = perspectiveToSpec(dataset, next).dropped;
    if (nextDropped.join("\n") !== dropped.join("\n")) setDropped(nextDropped);
  };

  return (
    <div className="flex h-full flex-col">
      {(data.truncated ||
        mapped.dropped.length > 0 ||
        probe.status === "error") && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          {data.truncated &&
            `Showing the first ${ROWS.toLocaleString()} of ${data.rowCount.toLocaleString()} rows. `}
          {mapped.dropped.length > 0 &&
            `To code will leave out: ${mapped.dropped.join(", ")}. `}
          {probe.status === "error" &&
            `This layout cannot run as a query: ${probe.message}`}
        </p>
      )}
      <PerspectiveViewer
        arrow={data.arrow}
        config={config ?? undefined}
        onConfig={onConfig}
        className="min-h-0 flex-1"
      />
    </div>
  );
}
```

`dropped` lives in view state so the host's "To code" drawer (Task 12) can show it without re-running the mapping. The `useQuery` type must accept `ViewerConfigUpdate | null` through `useViewState`'s `Json` bound: `ViewerConfigUpdate` is a plain JSON-shaped type, but if `tsc` rejects it, store `config` as `JsonObject | null` and cast at the `perspectiveToSpec` call.

In `docs/context/decisions.md` add a "Perspective" subsection under a new "Views" heading with the mapping table above, in prose form, and the sentence: Perspective shows up to 50,000 rows; the probe query with `limit: 1` is how the mapped spec reaches lineage and to code.

- [ ] **Step 5: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && cd ..
uv run pytest tests/components -q
git add web src docs && git commit -m "feat: add the Perspective pivot built-in with a query spec mapping"
```

---

### Task 10: Built-ins: TanStack data table and OHLC

**Files:**

- Create: `src/quarry/components/builtin/data-table-tanstack/{manifest.json,component.tsx}`, `src/quarry/components/builtin/ohlc/{manifest.json,component.tsx}`, `src/quarry/components/builtin/_shared/columns.ts`
- Modify: `src/quarry/components/builtin/time-series/component.tsx` (use the shared column helpers), `web/vite.config.ts`, `web/vitest.config.ts`, `web/tsconfig.app.json` (`@builtin/_shared` already covered by the `@builtin/*` alias)
- Test: `web/src/builtins/data-table-tanstack.test.tsx`, `web/src/builtins/ohlc.test.tsx`, `tests/components/test_builtin.py` (extend)

**Interfaces:**

- Produces: `isTime(dtype)`, `isNumeric(dtype)`, `firstOf(schema, predicate)` in `_shared/columns.ts`; built-ins `data-table-tanstack` (state `sort`, `limit`) and `ohlc` (state `columns: {time, open, high, low, close}`).
- Consumes: `useQuery`, `useViewState`, `useDatasetSchema` (`@quarry/hooks`), `@tanstack/react-table` v9, `lightweight-charts` 5 `CandlestickSeries`.

`_shared/` has no manifest, so `ComponentLibrary.entries()` skips it (it globs `*/manifest.json`). Built-ins import it as `@builtin/_shared/columns`, which the runtime cannot resolve: the loader sees `require("@builtin/_shared/columns")`. So the shared file is for type-checked source only, and the built-ins must inline what they use. Keep `_shared/columns.ts` out of Stage 5: inline the three one-line helpers in each component as the Stage 3 time series does. Delete the `_shared` entries above from this task's file list when executing; they are left here so the reviewer sees the decision.

- [ ] **Step 1: Manifests**

`src/quarry/components/builtin/data-table-tanstack/manifest.json`:

```json
{
  "id": "data-table-tanstack",
  "name": "Data table (TanStack)",
  "description": "Plain sortable table in the design system's styling, for custom cell rendering.",
  "tags": ["table", "rows", "inspect", "tanstack"],
  "contract_version": 1,
  "schema": { "requires": [] },
  "origin": "builtin",
  "created_at": "2026-10-09T00:00:00Z"
}
```

`src/quarry/components/builtin/ohlc/manifest.json`:

```json
{
  "id": "ohlc",
  "name": "OHLC",
  "description": "Candlestick chart of open, high, low and close columns over a date or datetime column.",
  "tags": ["ohlc", "candlestick", "price", "bars", "time"],
  "contract_version": 1,
  "schema": {
    "requires": [
      { "role": "time", "dtype": "datetime", "min": 1 },
      { "role": "price", "dtype": "numeric", "min": 4 }
    ]
  },
  "origin": "builtin",
  "created_at": "2026-10-09T00:00:00Z"
}
```

- [ ] **Step 2: Failing tests**

`web/src/builtins/data-table-tanstack.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const setSort = vi.fn();
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    initial,
    key === "sort" ? setSort : () => undefined,
  ],
  useDatasetSchema: () => null,
}));

import DataTableTanstack from "@builtin/data-table-tanstack/component";

describe("data-table-tanstack built-in", () => {
  it("renders header cells and rows, and pushes a header click into the sort state", () => {
    query.mockReturnValue({
      status: "success",
      rows: [
        { sym: "A", px: 1.5 },
        { sym: "B", px: 2 },
      ],
      schema: [
        { name: "sym", dtype: "String" },
        { name: "px", dtype: "Float64" },
      ],
      rowCount: 2,
      truncated: false,
      arrow: null,
    });
    render(<DataTableTanstack datasets={["df"]} />);
    expect(query).toHaveBeenCalledWith(
      expect.objectContaining({ dataset: "df", limit: 500 }),
    );
    expect(screen.getByRole("columnheader", { name: /px/ })).toBeTruthy();
    expect(screen.getByText("1.5")).toBeTruthy();
    fireEvent.click(screen.getByRole("columnheader", { name: /px/ }));
    expect(setSort).toHaveBeenCalledWith({ col: "px", desc: false });
  });

  it("shows query errors in place", () => {
    query.mockReturnValue({ status: "error", message: "unknown column" });
    render(<DataTableTanstack datasets={["df"]} />);
    expect(screen.getByText("unknown column")).toBeTruthy();
  });
});
```

`web/src/builtins/ohlc.test.tsx`:

```tsx
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const setData = vi.fn();
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(_key: string, initial: T) => [initial, () => undefined],
  useDatasetSchema: () => [
    { name: "ts", dtype: "Date" },
    { name: "open", dtype: "Float64" },
    { name: "high", dtype: "Float64" },
    { name: "low", dtype: "Float64" },
    { name: "close", dtype: "Float64" },
    { name: "volume", dtype: "Int64" },
  ],
}));
vi.mock("lightweight-charts", () => ({
  CandlestickSeries: {},
  createChart: () => ({
    addSeries: () => ({ setData }),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  }),
}));

import Ohlc from "@builtin/ohlc/component";

describe("ohlc built-in", () => {
  it("guesses the price columns by name, sorts by time, and feeds candles", () => {
    query.mockReturnValue({
      status: "success",
      rows: [{ ts: "2024-01-02", open: 1, high: 2, low: 0.5, close: 1.5 }],
      schema: [],
      rowCount: 1,
      truncated: false,
      arrow: null,
    });
    render(<Ohlc datasets={["bars"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "bars",
      select: ["ts", "open", "high", "low", "close"],
      sort: [{ col: "ts" }],
      limit: 50000,
    });
    expect(setData).toHaveBeenCalledWith([
      { time: 1704153600, open: 1, high: 2, low: 0.5, close: 1.5 },
    ]);
    expect(screen.getByLabelText("Close")).toBeTruthy();
  });
});
```

Extend `tests/components/test_builtin.py` so the expected id set includes `"data-table-tanstack"` and `"ohlc"`.

- [ ] **Step 3: Implement the TanStack table**

`src/quarry/components/builtin/data-table-tanstack/component.tsx`:

```tsx
import { useMemo } from "react";
import {
  createColumnHelper,
  rowSortingFeature,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useQuery, useViewState } from "@quarry/hooks";
import type { Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

interface SortState {
  col: string;
  desc: boolean;
}

const features = tableFeatures({ rowSortingFeature });
const helper = createColumnHelper<typeof features, Row>();
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);

export default function DataTableTanstack({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const [sort, setSort] = useViewState<SortState | null>("sort", null);
  const [limit] = useViewState<number>("limit", 500);
  const result = useQuery({
    dataset,
    limit,
    ...(sort === null ? {} : { sort: [{ col: sort.col, desc: sort.desc }] }),
  });
  const rows = result.status === "success" ? result.rows : [];
  const schema = result.status === "success" ? result.schema : [];
  // Stable inputs: v9 rebuilds the table when `columns` or `data` change identity.
  const columns = useMemo(
    () =>
      helper.columns(
        schema.map((c) =>
          helper.accessor((row) => row[c.name], {
            id: c.name,
            header: c.name,
            cell: (info) => format(info.getValue()),
            meta: { numeric: isNumeric(c.dtype) },
          }),
        ),
      ),
    [schema],
  );
  const table = useTable({
    features,
    columns,
    data: rows,
    enableSorting: false,
  });

  if (result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

  const onHeader = (col: string) =>
    setSort(
      sort?.col === col
        ? sort.desc
          ? null
          : { col, desc: true }
        : { col, desc: false },
    );

  return (
    <div className="flex h-full flex-col">
      {result.truncated && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          Showing {rows.length.toLocaleString()} of{" "}
          {result.rowCount.toLocaleString()} rows.
        </p>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-card">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => (
                  <th
                    key={header.id}
                    role="columnheader"
                    className="cursor-pointer border-b border-border px-2 py-1 text-left font-medium"
                    onClick={() => onHeader(header.column.id)}
                  >
                    <table.FlexRender header={header} />
                    {sort?.col === header.column.id &&
                      (sort.desc ? " ▼" : " ▲")}
                  </th>
                ))}
              </tr>
            ))}
          </thead>
          <tbody>
            {table.getRowModel().rows.map((row) => (
              <tr key={row.id} className="border-b border-border/60">
                {row.getAllCells().map((cell) => (
                  <td
                    key={cell.id}
                    className={
                      (
                        cell.column.columnDef.meta as
                          { numeric?: boolean } | undefined
                      )?.numeric
                        ? "px-2 py-1 text-right font-mono"
                        : "px-2 py-1"
                    }
                  >
                    <table.FlexRender cell={cell} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function format(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
```

Sorting is pushed into the query spec, as the AG Grid table does; TanStack's own sorting feature is registered only so `header.column` carries the v9 column API. Drop `enableSorting: false` if v9's `TableOptions` rejects it; nothing calls `toggleSorting`. If `meta` on a column def needs a declaration merge in v9, declare `interface ColumnMeta { numeric?: boolean }` in a `declare module "@tanstack/react-table"` block inside the component file instead of the cast. If `role="columnheader"` on a `<th>` is flagged redundant by the test's accessibility query, drop the attribute; `<th>` already has that role.

- [ ] **Step 4: Implement OHLC**

`src/quarry/components/builtin/ohlc/component.tsx`:

```tsx
import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  createChart,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Column, Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

type Role = "time" | "open" | "high" | "low" | "close";
type Columns = Record<Role, string | null>;

const EMPTY: Columns = {
  time: null,
  open: null,
  high: null,
  low: null,
  close: null,
};
const isTime = (dtype: string) =>
  dtype === "Date" || dtype.startsWith("Datetime");
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);

export default function Ohlc({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [chosen, setChosen] = useViewState<Columns>("columns", EMPTY);
  const columns = resolve(chosen, schema ?? []);
  const ready = Object.values(columns).every((c) => c !== null);
  const select = ready ? (Object.values(columns) as string[]) : [];
  const result = useQuery(
    ready && columns.time !== null
      ? { dataset, select, sort: [{ col: columns.time }], limit: 50000 }
      : { dataset, limit: 1 },
  );
  const container = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = container.current;
    if (el === null || !ready || result.status !== "success") return;
    const chart: IChartApi = createChart(el, {
      autoSize: true,
      layout: {
        attributionLogo: true,
        fontFamily: "IBM Plex Sans, sans-serif",
      },
    });
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#1e6e63",
      downColor: "#9a3b2e",
      wickUpColor: "#1e6e63",
      wickDownColor: "#9a3b2e",
      borderVisible: false,
    });
    series.setData(result.rows.map((row) => candle(row, columns)));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [ready, result, columns]);

  if (schema === null)
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs a date column and open, high, low and close columns.
      </p>
    );
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

  const numeric = schema.filter((c) => isNumeric(c.dtype)).map((c) => c.name);
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        <Picker
          label="Time"
          value={columns.time ?? ""}
          options={schema.filter((c) => isTime(c.dtype)).map((c) => c.name)}
          onChange={(v) => setChosen({ ...columns, time: v })}
        />
        {(["open", "high", "low", "close"] as const).map((role) => (
          <Picker
            key={role}
            label={role[0]?.toUpperCase() + role.slice(1)}
            value={columns[role] ?? ""}
            options={numeric}
            onChange={(v) => setChosen({ ...columns, [role]: v })}
          />
        ))}
      </div>
      <div ref={container} className="min-h-0 flex-1" />
    </div>
  );
}

/** Chosen columns first; otherwise a column named like the role, otherwise the next numeric one. */
function resolve(chosen: Columns, schema: Column[]): Columns {
  const numeric = schema.filter((c) => isNumeric(c.dtype)).map((c) => c.name);
  const taken = new Set<string>();
  const pick = (role: Exclude<Role, "time">): string | null => {
    const named =
      chosen[role] ??
      numeric.find((n) => n.toLowerCase().startsWith(role)) ??
      null;
    const value = named ?? numeric.find((n) => !taken.has(n)) ?? null;
    if (value !== null) taken.add(value);
    return value;
  };
  return {
    time: chosen.time ?? schema.find((c) => isTime(c.dtype))?.name ?? null,
    open: pick("open"),
    high: pick("high"),
    low: pick("low"),
    close: pick("close"),
  };
}

function candle(row: Row, columns: Columns) {
  const raw = row[columns.time ?? ""];
  const ms =
    typeof raw === "string"
      ? Date.parse(raw)
      : typeof raw === "number"
        ? raw
        : NaN;
  const num = (role: Exclude<Role, "time">) => {
    const v = row[columns[role] ?? ""];
    return typeof v === "number" ? v : Number(v);
  };
  return {
    time: Math.floor(ms / 1000) as UTCTimestamp,
    open: num("open"),
    high: num("high"),
    low: num("low"),
    close: num("close"),
  };
}

interface PickerProps {
  label: string;
  value: string;
  options: string[];
  onChange: (next: string) => void;
}

function Picker({ label, value, options, onChange }: PickerProps) {
  return (
    <label className="flex items-center gap-1 text-muted-foreground">
      {label}
      <select
        aria-label={label}
        className="bg-transparent text-foreground"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
```

Decimal columns arrive as JSON strings (Stage 1's exact-decimal rule), so `num` converts with `Number`; a test row with plain numbers passes either way. If this file passes 250 lines after prettier, move `resolve`, `candle` and `Picker` into `ohlc/columns.tsx` beside it: the runtime loads `component.tsx` only, so a sibling file would not resolve at runtime. Shorten instead: drop the `Picker` label computation to a lookup table.

- [ ] **Step 5: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && cd ..
uv run pytest tests/components -q
git add web src && git commit -m "feat: add TanStack table and OHLC built-ins"
```

---

### Task 11: Built-ins: Recharts bar and line, Plotly scatter and heatmap, ECharts large series

**Files:**

- Create: `src/quarry/components/builtin/bar-line/{manifest.json,component.tsx}`, `src/quarry/components/builtin/scatter/{manifest.json,component.tsx}`, `src/quarry/components/builtin/heatmap/{manifest.json,component.tsx}`, `src/quarry/components/builtin/large-series/{manifest.json,component.tsx}`
- Test: `web/src/builtins/bar-line.test.tsx`, `web/src/builtins/scatter.test.tsx`, `web/src/builtins/heatmap.test.tsx`, `web/src/builtins/large-series.test.tsx`, `tests/components/test_builtin.py` (extend to all nine ids)

**Interfaces:**

- Produces: `bar-line` (state `kind: "bar" | "line"`, `category`, `value`, `agg`; query `group_by` + `aggs`), `scatter` (state `x`, `y`, `color`; query `select` + `limit`), `heatmap` (state `row`, `column`, `value`, `agg`; query `pivot`), `large-series` (state `time`, `value`; query `select` + `sort` with `limit: 500000` and ECharts `large: true`).
- Consumes: `@quarry/hooks`, `recharts`, `react-plotly.js` (the runtime's factory-built default export), `echarts-for-react`.

Every one of these pushes its grouping and aggregation into the query spec, so "to code" renders the same computation in polars. `large-series` is the one built-in that asks for more rows than the default cap; the server still truncates at `row_cap`, and the banner says so.

- [ ] **Step 1: Manifests**

`bar-line/manifest.json`:

```json
{
  "id": "bar-line",
  "name": "Bar and line",
  "description": "Aggregate one numeric column by one category column and show it as bars or a line.",
  "tags": ["bar", "line", "aggregate", "group", "category"],
  "contract_version": 1,
  "schema": {
    "requires": [
      { "role": "category", "dtype": "any", "min": 1 },
      { "role": "value", "dtype": "numeric", "min": 1 }
    ]
  },
  "origin": "builtin",
  "created_at": "2026-10-09T00:00:00Z"
}
```

`scatter/manifest.json`:

```json
{
  "id": "scatter",
  "name": "Scatter",
  "description": "Plotly scatter of two numeric columns, optionally colored by a third column.",
  "tags": ["scatter", "points", "correlation", "plotly"],
  "contract_version": 1,
  "schema": { "requires": [{ "role": "xy", "dtype": "numeric", "min": 2 }] },
  "origin": "builtin",
  "created_at": "2026-10-09T00:00:00Z"
}
```

`heatmap/manifest.json`:

```json
{
  "id": "heatmap",
  "name": "Heatmap",
  "description": "Plotly heatmap of an aggregated value pivoted by a row column and a column column.",
  "tags": ["heatmap", "pivot", "matrix", "plotly"],
  "contract_version": 1,
  "schema": {
    "requires": [
      { "role": "keys", "dtype": "any", "min": 2 },
      { "role": "value", "dtype": "numeric", "min": 1 }
    ]
  },
  "origin": "builtin",
  "created_at": "2026-10-09T00:00:00Z"
}
```

`large-series/manifest.json`:

```json
{
  "id": "large-series",
  "name": "Large series",
  "description": "ECharts line for series of hundreds of thousands of points, with zoom.",
  "tags": ["line", "large", "time", "series", "zoom", "echarts"],
  "contract_version": 1,
  "schema": {
    "requires": [
      { "role": "time", "dtype": "datetime", "min": 1 },
      { "role": "value", "dtype": "numeric", "min": 1 }
    ]
  },
  "origin": "builtin",
  "created_at": "2026-10-09T00:00:00Z"
}
```

- [ ] **Step 2: Failing tests**

The four tests share one shape; `bar-line.test.tsx` in full, the others differ only in the mock and the expected spec:

```tsx
import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(_key: string, initial: T) => [initial, () => undefined],
  useDatasetSchema: () => [
    { name: "sector", dtype: "String" },
    { name: "ret", dtype: "Float64" },
  ],
}));
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div data-testid="chart">{children}</div>
  ),
  BarChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  LineChart: ({ children }: { children: ReactNode }) => <div>{children}</div>,
  Bar: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
}));

import BarLine from "@builtin/bar-line/component";

describe("bar-line built-in", () => {
  it("groups by the first string column and sums the first numeric one", () => {
    query.mockReturnValue({
      status: "success",
      rows: [{ sector: "tech", ret_sum: "0.5" }],
      schema: [],
      rowCount: 1,
      truncated: false,
      arrow: null,
    });
    render(<BarLine datasets={["trades"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "trades",
      group_by: ["sector"],
      aggs: [{ col: "ret", fn: "sum" }],
      sort: [{ col: "sector" }],
      limit: 500,
    });
    expect(screen.getByTestId("chart")).toBeTruthy();
  });
});
```

`scatter.test.tsx`: schema `x: Float64, y: Float64, sym: String`; mock `react-plotly.js` with `default: (props) => <div data-testid="plot" data-traces={JSON.stringify(props.data.length)} />`; expect the spec `{ dataset, select: ["x", "y"], limit: 20000 }` and one trace. `heatmap.test.tsx`: schema `date: Date, ticker: String, ret: Float64`; mock `react-plotly.js` the same way; expect `{ dataset, pivot: { index: ["date"], columns: "ticker", values: "ret", agg: "mean" }, sort: [{ col: "date" }], limit: 500 }`. `large-series.test.tsx`: schema `ts: Datetime(time_unit='us', time_zone=None), px: Float64`; mock `echarts-for-react` with `default: (props) => <div data-testid="echarts" data-large={String(props.option.series[0].large)} />`; expect `{ dataset, select: ["ts", "px"], sort: [{ col: "ts" }], limit: 500000 }` and `data-large="true"`.

Extend `tests/components/test_builtin.py`:

```python
BUILTIN_IDS = {
    "data-table", "data-table-tanstack", "time-series", "ohlc", "bar-line",
    "scatter", "heatmap", "large-series", "pivot",
}


def test_builtin_library_lists_every_spec_component() -> None:
    library = ComponentLibrary([builtin_root()])
    assert {e.manifest.id for e in library.entries()} == BUILTIN_IDS
    for entry in library.entries():
        assert "export default" in entry.source_path.read_text()
```

- [ ] **Step 3: Implement bar-line**

`src/quarry/components/builtin/bar-line/component.tsx`:

```tsx
import {
  Bar,
  BarChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Agg } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

const AGGS: Agg["fn"][] = ["sum", "mean", "count", "min", "max", "median"];
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);

export default function BarLine({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [kind, setKind] = useViewState<"bar" | "line">("kind", "bar");
  const [agg, setAgg] = useViewState<Agg["fn"]>("agg", "sum");
  const [chosen, setChosen] = useViewState<{
    category: string | null;
    value: string | null;
  }>("columns", { category: null, value: null });
  const category =
    chosen.category ?? schema?.find((c) => !isNumeric(c.dtype))?.name ?? null;
  const value =
    chosen.value ?? schema?.find((c) => isNumeric(c.dtype))?.name ?? null;
  const ready = category !== null && value !== null;
  const result = useQuery(
    ready
      ? {
          dataset,
          group_by: [category],
          aggs: [{ col: value, fn: agg }],
          sort: [{ col: category }],
          limit: 500,
        }
      : { dataset, limit: 1 },
  );

  if (schema === null || result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs a category column and a numeric column.
      </p>
    );
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

  const key = `${value}_${agg}`;
  // Sums over integer columns arrive as exact decimal strings; charts want numbers.
  const data = result.rows.map((row) => ({ ...row, [key]: Number(row[key]) }));
  const Chart = kind === "bar" ? BarChart : LineChart;
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        <Select
          label="Chart"
          value={kind}
          options={["bar", "line"]}
          onChange={(v) => setKind(v as "bar" | "line")}
        />
        <Select
          label="Category"
          value={category}
          options={schema.map((c) => c.name)}
          onChange={(v) => setChosen({ category: v, value })}
        />
        <Select
          label="Value"
          value={value}
          options={schema.filter((c) => isNumeric(c.dtype)).map((c) => c.name)}
          onChange={(v) => setChosen({ category, value: v })}
        />
        <Select
          label="Aggregate"
          value={agg}
          options={AGGS}
          onChange={(v) => setAgg(v as Agg["fn"])}
        />
      </div>
      <div className="min-h-0 flex-1 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <Chart data={data}>
            <XAxis dataKey={category} />
            <YAxis />
            <Tooltip />
            {kind === "bar" ? (
              <Bar dataKey={key} fill="#1e6e63" />
            ) : (
              <Line dataKey={key} stroke="#1e6e63" dot={false} />
            )}
          </Chart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

interface SelectProps {
  label: string;
  value: string;
  options: string[];
  onChange: (next: string) => void;
}

function Select({ label, value, options, onChange }: SelectProps) {
  return (
    <label className="flex items-center gap-1 text-muted-foreground">
      {label}
      <select
        aria-label={label}
        className="bg-transparent text-foreground"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}
```

Prettier reflows the long JSX lines; that is expected.

- [ ] **Step 4: Implement scatter and heatmap**

`src/quarry/components/builtin/scatter/component.tsx`:

```tsx
import Plot from "react-plotly.js";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";

interface Props {
  datasets: string[];
}

const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);
const LIMIT = 20000;

export default function Scatter({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const numeric = (schema ?? [])
    .filter((c) => isNumeric(c.dtype))
    .map((c) => c.name);
  const [chosen, setChosen] = useViewState<{
    x: string | null;
    y: string | null;
    color: string | null;
  }>("columns", { x: null, y: null, color: null });
  const x = chosen.x ?? numeric[0] ?? null;
  const y = chosen.y ?? numeric.find((n) => n !== x) ?? null;
  const color = chosen.color;
  const ready = x !== null && y !== null;
  const select = ready
    ? [x, y, ...(color !== null && color !== x && color !== y ? [color] : [])]
    : [];
  const result = useQuery(
    ready ? { dataset, select, limit: LIMIT } : { dataset, limit: 1 },
  );

  if (schema === null || result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs two numeric columns.
      </p>
    );
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

  const traces = tracesFor(result.rows, x, y, color);
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        <Select
          label="X"
          value={x}
          options={numeric}
          onChange={(v) => setChosen({ ...chosen, x: v })}
        />
        <Select
          label="Y"
          value={y}
          options={numeric}
          onChange={(v) => setChosen({ ...chosen, y: v })}
        />
        <Select
          label="Color"
          value={color ?? ""}
          options={["", ...schema.map((c) => c.name)]}
          onChange={(v) => setChosen({ ...chosen, color: v === "" ? null : v })}
        />
        {result.truncated && (
          <span className="text-muted-foreground">
            First {LIMIT.toLocaleString()} of {result.rowCount.toLocaleString()}{" "}
            rows.
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1">
        <Plot
          data={traces}
          layout={{
            autosize: true,
            margin: { t: 16, r: 16, b: 40, l: 48 },
            xaxis: { title: { text: x } },
            yaxis: { title: { text: y } },
            font: { family: "IBM Plex Sans, sans-serif" },
          }}
          useResizeHandler
          style={{ width: "100%", height: "100%" }}
          config={{ displaylogo: false }}
        />
      </div>
    </div>
  );
}
```

plus the same `Select` helper as `bar-line` (copied; built-ins cannot share files at runtime) and the trace builder, one trace without a color column and one per distinct value with it:

```tsx
import type { Data } from "plotly.js";

function tracesFor(
  rows: Row[],
  x: string,
  y: string,
  color: string | null,
): Data[] {
  const groups = new Map<string, { x: number[]; y: number[] }>();
  for (const row of rows) {
    const key = color === null ? "" : String(row[color]);
    const group = groups.get(key) ?? { x: [], y: [] };
    group.x.push(Number(row[x]));
    group.y.push(Number(row[y]));
    groups.set(key, group);
  }
  return [...groups.entries()].map(([name, points]) => ({
    type: "scattergl",
    mode: "markers",
    name,
    x: points.x,
    y: points.y,
    marker: { size: 5, ...(color === null ? { color: "#1e6e63" } : {}) },
  }));
}
```

(`Row` from `@/shared/api-types`; `Data` is the trace union `@types/plotly.js` exports, which `react-plotly.js` accepts for `data`.)

`src/quarry/components/builtin/heatmap/component.tsx`:

```tsx
import Plot from "react-plotly.js";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Agg } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

interface Keys {
  row: string | null;
  column: string | null;
  value: string | null;
}

const AGGS: Agg["fn"][] = ["mean", "sum", "count", "min", "max", "median"];
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);

export default function Heatmap({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const names = (schema ?? []).map((c) => c.name);
  const keys = (schema ?? [])
    .filter((c) => !isNumeric(c.dtype))
    .map((c) => c.name);
  const [agg, setAgg] = useViewState<Agg["fn"]>("agg", "mean");
  const [chosen, setChosen] = useViewState<Keys>("columns", {
    row: null,
    column: null,
    value: null,
  });
  const row = chosen.row ?? keys[0] ?? null;
  const column =
    chosen.column ?? names.find((n) => n !== row && keys.includes(n)) ?? null;
  const value =
    chosen.value ??
    (schema ?? []).find((c) => isNumeric(c.dtype))?.name ??
    null;
  const ready = row !== null && column !== null && value !== null;
  const result = useQuery(
    ready
      ? {
          dataset,
          pivot: { index: [row], columns: column, values: value, agg },
          sort: [{ col: row }],
          limit: 500,
        }
      : { dataset, limit: 1 },
  );

  if (schema === null || result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs two key columns and a numeric column.
      </p>
    );
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

  // The pivoted frame is the row key plus one column per distinct `column` value.
  const cols = result.schema.map((c) => c.name).filter((n) => n !== row);
  const z = result.rows.map((r) =>
    cols.map((c) => (r[c] === null ? NaN : Number(r[c]))),
  );
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        <Select
          label="Row"
          value={row}
          options={names}
          onChange={(v) => setChosen({ ...chosen, row: v })}
        />
        <Select
          label="Column"
          value={column}
          options={names}
          onChange={(v) => setChosen({ ...chosen, column: v })}
        />
        <Select
          label="Value"
          value={value}
          options={names.filter((n) => !keys.includes(n))}
          onChange={(v) => setChosen({ ...chosen, value: v })}
        />
        <Select
          label="Aggregate"
          value={agg}
          options={AGGS}
          onChange={(v) => setAgg(v as Agg["fn"])}
        />
      </div>
      <div className="min-h-0 flex-1">
        <Plot
          data={[
            {
              type: "heatmap",
              z,
              x: cols,
              y: result.rows.map((r) => String(r[row])),
              colorscale: "Viridis",
            },
          ]}
          layout={{
            autosize: true,
            margin: { t: 16, r: 16, b: 60, l: 80 },
            font: { family: "IBM Plex Sans, sans-serif" },
          }}
          useResizeHandler
          style={{ width: "100%", height: "100%" }}
          config={{ displaylogo: false }}
        />
      </div>
    </div>
  );
}
```

plus the `Select` helper. Nulls in the pivot become `NaN`, which Plotly leaves blank. `cols` reads the result schema rather than the rows so an empty result still renders an empty grid.

- [ ] **Step 5: Implement large-series**

`src/quarry/components/builtin/large-series/component.tsx`:

```tsx
import ReactECharts from "echarts-for-react";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";

interface Props {
  datasets: string[];
}

const isTime = (dtype: string) =>
  dtype === "Date" || dtype.startsWith("Datetime");
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);
const LIMIT = 500000;

export default function LargeSeries({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [chosen, setChosen] = useViewState<{
    time: string | null;
    value: string | null;
  }>("columns", { time: null, value: null });
  const time =
    chosen.time ?? schema?.find((c) => isTime(c.dtype))?.name ?? null;
  const value =
    chosen.value ?? schema?.find((c) => isNumeric(c.dtype))?.name ?? null;
  const ready = time !== null && value !== null;
  const result = useQuery(
    ready
      ? { dataset, select: [time, value], sort: [{ col: time }], limit: LIMIT }
      : { dataset, limit: 1 },
  );

  if (schema === null || result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs a date column and a numeric column.
      </p>
    );
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

  const points = result.rows.map((r) => [String(r[time]), Number(r[value])]);
  const option = {
    animation: false,
    grid: { top: 16, right: 16, bottom: 48, left: 56 },
    xAxis: { type: "time" },
    yAxis: { type: "value", scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider" }],
    tooltip: { trigger: "axis" },
    series: [
      {
        type: "line",
        showSymbol: false,
        large: true,
        largeThreshold: 2000,
        sampling: "lttb",
        data: points,
        lineStyle: { color: "#1e6e63", width: 1 },
      },
    ],
  };
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        <Select
          label="Time"
          value={time}
          options={schema.filter((c) => isTime(c.dtype)).map((c) => c.name)}
          onChange={(v) => setChosen({ time: v, value })}
        />
        <Select
          label="Value"
          value={value}
          options={schema.filter((c) => isNumeric(c.dtype)).map((c) => c.name)}
          onChange={(v) => setChosen({ time, value: v })}
        />
        {result.truncated && (
          <span className="text-muted-foreground">
            Showing the first {result.rows.length.toLocaleString()} of{" "}
            {result.rowCount.toLocaleString()} rows (server row cap).
          </span>
        )}
      </div>
      <div className="min-h-0 flex-1">
        <ReactECharts
          option={option}
          notMerge
          style={{ height: "100%", width: "100%" }}
        />
      </div>
    </div>
  );
}
```

plus the `Select` helper. `echarts-for-react` types `option` as `any`; the object literal above is accepted as is. Keep `notMerge` so a column change replaces the series.

- [ ] **Step 6: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && npm run build && cd ..
uv run pytest tests/components -q
git add web src && git commit -m "feat: add Recharts, Plotly and ECharts built-ins"
```

---

### Task 12: Host actions: to code, save to library, export downloads, busy state

**Files:**

- Modify: `web/src/shared/api-types.ts` (`ComponentManifest`, `SaveComponentRequest`, `ToCodeResponse`), `web/src/host/api/client.ts`, `web/src/host/api/keys.ts`, `web/src/host/api/hooks.ts`, `web/src/host/containers/StepActions.tsx` (two buttons), `web/src/host/containers/SessionPage.tsx` (busy from status), `web/src/host/containers/ProjectPage.tsx` (export button), `web/src/host/components/SavedItems.tsx` (recipe download per dataset)
- Create: `web/src/host/components/ToCodeDrawer.tsx`, `web/src/host/components/SaveComponentDialog.tsx`, `web/src/host/api/download.ts`
- Test: `web/src/host/components/ToCodeDrawer.test.tsx`, `web/src/host/components/SaveComponentDialog.test.tsx`, `web/src/host/api/client.test.ts` (extend), `web/src/host/api/download.test.ts`

**Interfaces:**

- Produces: `ApiClient.toCode(sessionId, queries) -> {code}`, `ApiClient.listComponents()`, `ApiClient.saveComponent(body)`, `ApiClient.downloadUrl(path)` is not a thing: downloads go through `downloadFile(api, path, filename)` which fetches with the token and saves a blob; hooks `useToCode(sessionId)`, `useSaveComponent()`, `useComponents()`; `ToCodeDrawer {open, code, dropped, pending, error, onChange, onRun, onClose}`; `SaveComponentDialog {open, defaultId, onClose, onSave({id, name, description, tags})}`; `StepActions` renders "To code" for a step with a view and snapshots, and "Save to library" for a step whose view is `inline`.
- Consumes: Stage 4 `StepActions`, `SaveDialog` (its layout and button conventions), `useSessionStatus`, `PromptBox`, `ProjectPage`, `SavedItems`; Task 3 route, Task 5 routes, Task 6 routes, Task 4 `busy`.

- [ ] **Step 1: Types, client, hooks, download helper**

Append to `api-types.ts`:

```ts
export interface SchemaRequirement {
  role: string;
  dtype: "datetime" | "numeric" | "string" | "any";
  min: number;
}

export interface ComponentManifest {
  id: string;
  name: string;
  description: string;
  tags: string[];
  contract_version: 1;
  schema: { requires: SchemaRequirement[] };
  origin: "builtin" | "generated" | "imported";
  created_at: string;
}

export interface SaveComponentRequest {
  id: string;
  name: string;
  description: string;
  tags: string[];
  source: string;
  session_id: string | null;
  dataset: string | null;
}

export interface ToCodeResponse {
  code: string;
}
```

Client methods:

```ts
  toCode(sessionId: string, queries: QuerySpec[]): Promise<ToCodeResponse> {
    return this.request("POST", `/sessions/${sessionId}/to-code`, { queries });
  }

  listComponents(): Promise<ComponentManifest[]> {
    return this.request("GET", "/components");
  }

  saveComponent(body: SaveComponentRequest): Promise<ComponentManifest> {
    return this.request("POST", "/components", body);
  }

  libraries(): Promise<LibraryStatus[]> {
    return this.request("GET", "/libraries");
  }

  /** Raw GET with the token, for file downloads. */
  fetchBlob(path: string): Promise<Blob> {
    return this.fetchImpl(path, {
      headers: { authorization: `Bearer ${this.token}` },
    }).then(async (response) => {
      if (!response.ok) throw new ApiError(response.status, await readDetail(response));
      return response.blob();
    });
  }
```

(`libraries()` was added in Task 8; keep one copy.) `web/src/host/api/download.ts`:

```ts
import type { ApiClient } from "./client";

/** Fetch with the bearer token and hand the bytes to the browser as a download. */
export async function downloadFile(
  api: ApiClient,
  path: string,
  filename: string,
  save: (url: string, filename: string) => void = saveViaAnchor,
): Promise<void> {
  const blob = await api.fetchBlob(path);
  const url = URL.createObjectURL(blob);
  save(url, filename);
  // Revoking right after click() can cancel the download; the browser needs a moment.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function saveViaAnchor(url: string, filename: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}
```

A plain link to `/projects/<slug>/export.ipynb` would not carry the token, so every download goes through `fetchBlob`. `web/src/host/api/download.test.ts` stubs `URL.createObjectURL`/`revokeObjectURL` (jsdom lacks them), uses fake timers, and asserts `save` is called with the filename and the URL is revoked only after the timer runs.

Hooks:

```ts
export function useToCode(sessionId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: (queries: QuerySpec[]) => api.toCode(sessionId, queries),
  });
}

export function useComponents() {
  const api = useApi();
  return useQuery({
    queryKey: keys.components(),
    queryFn: () => api.listComponents(),
  });
}

export function useSaveComponent() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SaveComponentRequest) => api.saveComponent(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.components() }),
  });
}
```

with `keys.components: () => ["components"] as const`. Add client tests for `toCode` (POST body `{queries}`), `saveComponent` (POST `/components`) and `fetchBlob` (sends the token, rejects on 404).

- [ ] **Step 2: Failing component tests**

`web/src/host/components/ToCodeDrawer.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToCodeDrawer } from "./ToCodeDrawer";

describe("ToCodeDrawer", () => {
  it("shows the code, what was left out, and runs the edited text", () => {
    const onRun = vi.fn();
    const onChange = vi.fn();
    render(
      <ToCodeDrawer
        open
        code="result = df.lazy().collect()"
        dropped={["expression e"]}
        pending={false}
        error={null}
        onChange={onChange}
        onRun={onRun}
        onClose={() => undefined}
      />,
    );
    expect(screen.getByText(/left out: expression e/i)).toBeTruthy();
    const box = screen.getByRole("textbox", { name: "Python" });
    expect((box as HTMLTextAreaElement).value).toContain("df.lazy()");
    fireEvent.change(box, { target: { value: "x = 1" } });
    expect(onChange).toHaveBeenCalledWith("x = 1");
    fireEvent.click(screen.getByRole("button", { name: "Run as step" }));
    expect(onRun).toHaveBeenCalled();
  });

  it("disables run while pending and shows an error", () => {
    render(
      <ToCodeDrawer
        open
        code=""
        dropped={[]}
        pending
        error="kernel is dead"
        onChange={() => undefined}
        onRun={() => undefined}
        onClose={() => undefined}
      />,
    );
    expect(
      (screen.getByRole("button", { name: "Run as step" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText("kernel is dead")).toBeTruthy();
  });
});
```

`web/src/host/components/SaveComponentDialog.test.tsx`:

```tsx
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SaveComponentDialog } from "./SaveComponentDialog";

describe("SaveComponentDialog", () => {
  it("normalises the id and splits tags", () => {
    const onSave = vi.fn();
    render(
      <SaveComponentDialog
        open
        defaultId="step-3-view"
        onClose={() => undefined}
        onSave={onSave}
      />,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(screen.getByLabelText("Id"), {
      target: { value: "My Scatter!" },
    });
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "My scatter" },
    });
    fireEvent.change(screen.getByLabelText("Tags"), {
      target: { value: "scatter, returns ,, " },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save to library" }));
    expect(onSave).toHaveBeenCalledWith({
      id: "my-scatter",
      name: "My scatter",
      description: "",
      tags: ["scatter", "returns"],
    });
    expect(dialog).toBeTruthy();
  });

  it("keeps the save button disabled until the id is valid", () => {
    render(
      <SaveComponentDialog
        open
        defaultId=""
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Save to library",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });
});
```

- [ ] **Step 3: Implement the components**

`web/src/host/components/ToCodeDrawer.tsx`:

```tsx
import { Button } from "@/components/ui/button";

interface ToCodeDrawerProps {
  open: boolean;
  code: string;
  dropped: string[];
  pending: boolean;
  error: string | null;
  onChange: (code: string) => void;
  onRun: () => void;
  onClose: () => void;
}

export function ToCodeDrawer({
  open,
  code,
  dropped,
  pending,
  error,
  onChange,
  onRun,
  onClose,
}: ToCodeDrawerProps) {
  if (!open) return null;
  return (
    <section
      aria-label="To code"
      className="flex flex-col gap-2 rounded-md border border-border bg-card p-3"
    >
      <p className="text-sm text-muted-foreground">
        Python for this view's queries. Edit it, then run it as a step; its
        outputs join the lineage.
      </p>
      {dropped.length > 0 && (
        <p className="text-sm text-muted-foreground">
          Left out: {dropped.join(", ")}.
        </p>
      )}
      <textarea
        aria-label="Python"
        className="min-h-48 w-full rounded-md bg-muted p-3 font-mono text-xs leading-relaxed"
        value={code}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
      {error !== null && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={pending || code.trim() === ""}
          onClick={onRun}
        >
          Run as step
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    </section>
  );
}
```

`web/src/host/components/SaveComponentDialog.tsx` follows Stage 4's `SaveDialog` layout (same overlay, `role="dialog"`, labelled inputs) with fields Id (pre-filled from `defaultId`, normalised on save with `value.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "")`), Name, Description, Tags (comma separated; trimmed, empties dropped); the primary button "Save to library" is disabled until the normalised id matches `/^[a-z0-9][a-z0-9-]{0,63}$/` and the name is non-empty. Show the normalised id under the field as "Saved as `my-scatter`" when it differs from what was typed.

- [ ] **Step 4: Wire the actions**

In `StepActions` (Stage 4), add state `toCode: { code: string; dropped: string[] } | null` and `savingComponent: boolean`, the hooks `useToCode(sessionId)`, `useSaveComponent()`, `useSubmitManual(sessionId)` (new in `hooks.ts`: a mutation over `api.postManualStep` that invalidates the session), and two buttons beside "Save view":

```tsx
{
  step.view !== null && dataset === undefined && (
    <Button
      variant="ghost"
      size="xs"
      disabled={latestQueries.length === 0 || toCodeRequest.isPending}
      onClick={() =>
        toCodeRequest.mutate(latestQueries, {
          onSuccess: ({ code }) => setToCode({ code, dropped }),
        })
      }
    >
      To code
    </Button>
  );
}
{
  step.view?.component_id === "inline" && dataset === undefined && (
    <Button variant="ghost" size="xs" onClick={() => setSavingComponent(true)}>
      Save to library
    </Button>
  );
}
```

where `latestQueries = step.view?.snapshots.at(-1)?.queries ?? []` (typed `QuerySpec[]`: `Snapshot.queries` is `JsonObject[]` in Stage 3's types; cast through `unknown` or change the type to `QuerySpec[]`, which the server guarantees) and `dropped` is `latestState["dropped"]` when it is an array of strings (the pivot built-in's key), else `[]`. The "To code" button stays disabled until the view has reported a state, which the runtime now does once after mount (Task 2 Step 3b).

Render `<ToCodeDrawer>` under the buttons when `toCode !== null`, with `onRun` submitting `toCode.code` through `useSubmitManual` and closing on success, and `error` from either mutation's `error?.message`. Render `<SaveComponentDialog>` when `savingComponent`, `defaultId` = `` `step-${step.index + 1}-view` ``, `onSave` calling `saveComponent.mutate({ ...choice, source: step.view.source, session_id: sessionId, dataset: step.view.datasets[0] ?? null })` and reporting `onDone(\`Saved ${manifest.id} to your library\`)`or the error detail (409 reads "component 'x' already exists" from the server). The`StepCard` `actions`slot already renders`StepActions`; the drawer appears inside the step, under the view.

In `SessionPage.tsx` `SessionColumn`, `running` becomes `steps.at(-1)?.status === "running" || submit.isPending || status.data?.busy === true`, so the prompt box disables during a save or restart hold rather than submitting into a 409.

In `ProjectPage.tsx` add an "Export notebook" button in the header calling `downloadFile(api, \`/projects/${slug}/export.ipynb\`, \`${slug}.ipynb\`)`, and in `SavedItems`a "Download recipe" button per dataset calling`downloadFile(api, \`/projects/${slug}/datasets/${name}/recipe.py\`, \`${name}.py\`)`; `SavedItems`gains a`slug`prop (or takes`project.meta.slug`). Both show the error message inline if the download rejects.

- [ ] **Step 5: Verify and commit**

```bash
cd web && npm run format && npm run check && npm test && npm run build && cd ..
git add web && git commit -m "feat: add to code, save to library and export actions to the host"
```

---

### Task 13: End-to-end coverage, docs, CI housekeeping

**Files:**

- Create: `tests/e2e/test_breadth.py`
- Modify: `.github/workflows/ci.yml`, `pyproject.toml` (`mypy` on tests), `docs/working-state.md`, `docs/context/code-map.md`, `docs/context/decisions.md`, `docs/context/glossary.md`, `docs/open-items.md`, `README.md`

**Interfaces:**

- Consumes: the Stage 3 `serve` fixture and `tests/e2e/test_ui.py` helpers; Task 2's `test_perspective.py`.

- [ ] **Step 1: Playwright test**

`tests/e2e/test_breadth.py`:

```python
from __future__ import annotations

import re
from collections.abc import Callable

from playwright.sync_api import Page, expect

from quarry.agent.types import AssistantTurn
from tests.e2e.conftest import RunningServer
from tests.e2e.test_ui import end, open_session, py, render, write

TRADES = (
    "df = pl.DataFrame({'ts': ['2024-01-02', '2024-01-03', '2024-01-04'], "
    "'sector': ['tech', 'tech', 'energy'], 'ret': [0.5, 1.0, -0.25]})"
)
CUSTOM = 'import { useQuery } from "@quarry/hooks";\nexport default function V({ datasets }: { datasets: string[] }) {\n  const q = useQuery({ dataset: datasets[0] ?? "", limit: 2 });\n  return <p>{q.status}</p>;\n}\n'


def test_bar_line_to_code_runs_as_a_step(
    serve: Callable[[list[AssistantTurn]], RunningServer], page: Page
) -> None:
    server = serve([py("c1", TRADES), render("c2", "bar-line"), end("bars")])
    open_session(page, server, "bar chart")
    expect(page.get_by_text("bars", exact=True)).to_be_visible(timeout=30_000)
    frame = page.frame_locator("iframe[title='View for step 1']")
    expect(frame.get_by_label("Aggregate")).to_be_visible(timeout=30_000)
    to_code = page.get_by_role("button", name="To code")
    expect(to_code).to_be_enabled(timeout=30_000)
    to_code.click()
    box = page.get_by_role("textbox", name="Python")
    expect(box).to_have_value(re.compile("group_by"), timeout=30_000)
    page.get_by_role("button", name="Run as step").click()
    expect(page.get_by_label("Step 2")).to_be_visible(timeout=30_000)
    expect(page.get_by_label("Step 2").get_by_text("Done")).to_be_visible(timeout=30_000)
    expect(page.get_by_label("Step 2").get_by_text("df_1")).to_be_visible()


def test_save_custom_view_to_library(
    serve: Callable[[list[AssistantTurn]], RunningServer], page: Page
) -> None:
    server = serve([py("c1", TRADES), write("c2", CUSTOM), end("custom")])
    open_session(page, server, "custom view")
    expect(page.get_by_text("custom", exact=True)).to_be_visible(timeout=30_000)
    page.get_by_role("button", name="Save to library").click()
    page.get_by_label("Id").fill("my-status")
    page.get_by_label("Name").fill("My status")
    page.get_by_role("button", name="Save to library", exact=True).last.click()
    expect(page.get_by_text("Saved my-status to your library")).to_be_visible(timeout=30_000)
```

The second test's "Save to library" name is shared by the step button and the dialog's primary button; `.last` picks the dialog's. If the dataset chips render a "df_1" chip for the manual step, the `Step 2` assertion holds; otherwise assert the code drawer contains `df_1`.

- [ ] **Step 2: CI housekeeping**

In `.github/workflows/ci.yml`: add `permissions:\n  contents: read` at the top level; pin `actions/checkout@v5`, `actions/setup-node@v5`, `astral-sh/setup-uv@v6` (check each action's current major on GitHub before pinning; use the latest major that exists on 2026-10-09 and record it in the commit message); change `uv run mypy src` to `uv run mypy src tests`. In `pyproject.toml` `[tool.mypy]`, `packages = ["quarry"]` becomes `files = ["src", "tests"]`, and add `[[tool.mypy.overrides]] module = ["nbformat", "playwright.*"] ignore_missing_imports = true` if those packages ship no types. Fix whatever `mypy tests` reports; it is the first time the suite is checked, so expect a handful of `-> None` annotations and `Any` returns from `json()` to need narrowing.

- [ ] **Step 3: Docs**

- `docs/working-state.md`: Stage 5 row "In progress" with the branch and PR; next actions updated.
- `docs/context/code-map.md`: `quarry/kernel/arrow.py`, `quarry/projects/export.py`, `quarry/server/{component_routes,libraries}.py`, `web/src/runtime/{perspective,libs}/`, the nine built-ins.
- `docs/context/decisions.md`: the CSP amendment and why `connect-src 'self'` is safe; Arrow as a lossy display transport; Perspective mapping (Task 9); ASCII-only identifiers in generated source; licensed libraries served from local installs with the key sent to the browser; `nbformat` validation only in tests.
- `docs/context/glossary.md`: licensed library, probe query, generated component.
- `docs/open-items.md`: remove every Stage 5 item this plan closed; move what it deferred (listed under "Open items" below) to "Any time" with the reason.
- `README.md`: a "Libraries" section showing the `[libraries]` config block with `highcharts_path = "/path/to/node_modules/highcharts"` and `scichart_path = "/path/to/node_modules/scichart"`, the `quarry projects` commands, and the export buttons.

Format with `npx prettier@3.9.9 --prose-wrap always --write` for `docs/working-state.md`, `docs/context/*.md`, `docs/open-items.md`, `README.md`.

- [ ] **Step 4: Verify and commit**

```bash
cd web && npm run build && cd ..
uv run pytest -q && uv run ruff check src tests && uv run ruff format --check src tests && uv run mypy src tests
git add .github pyproject.toml tests docs README.md && git commit -m "docs: record Stage 5 decisions and tighten CI"
```

Then open the pull request (or the second of two) against the base branch with the Stage 5 summary, Auto-fix on, and request a review.

---

## Open items

Addressed by this plan: Stage 5 list in `docs/open-items.md` (to-code `schema=` through the kernel; INTERVAL via `relation_projection`; `QueryError` from `to_source`; ASCII identifiers, which subsumes the NFKC check; Arrow compat level and casts); Stage 4 deferrals (lineage through SQL strings and attribute mutation, `SessionStatus.busy`); "Any time" (`permissions: contents: read`, pinned action versions, `mypy` on tests).

Deferred, with the reason:

- **Export renders saved queries without a schema.** Only dtype strings are on disk; mapping them back to polars dtypes is a parser nobody needs yet. The notebook says so in a comment, and "To code" in a session renders against the live schema.
- **Attribute mutation inside functions and `del`.** A helper that mutates a module-level frame in place is still invisible to lineage. Rare in step code; revisit if a recipe misses a step for that reason.
- **Lineage for SQL strings built at runtime** (f-strings, concatenation). Only literals reach the binder. The researcher sees the missing read in the recipe and can add a `# reads: name` comment, which is a Stage 6 idea, not a Stage 5 one.
- **AG Grid column filters stay client side.** Moving them into `filters` is a refinement of the Stage 3 built-in; the TanStack table has no client-side filters at all.
- **Perspective shows at most 50,000 rows** (the built-in's limit, under the server cap). Server-side pivoting through the mapped spec is what "to code" gives; the viewer itself stays a client-side explorer.
- **Perspective server mode and Arrow for every view** remain deferred per spec section 16.
- **Highcharts modules** (indicators, annotations) are not loaded; only `highstock.js`. A later `entry` list per library can add them.
- **SciChart 3D and the no-SIMD wasm fallback** are not configured; `wasmUrl` points at the SIMD build.
- **`quarry projects export` of a single view, and import of a `.ipynb`.** Not in the spec.
- **`UInt64` values above 2**63 in Arrow** reach Perspective as uint64; if its reader rejects them in practice, cast to Float64 in `for_viewer` (one line, with a test).
- Remaining "Any time" items (version in one place, byte-counted tails, `frozenset[FilterOp]`, TIMETZ offsets, test tightening) stay open.

## Done when

- `uv run pytest -q`, `uv run ruff check src tests`, `uv run ruff format --check src tests` and `uv run mypy src tests` pass; `npm run check`, `npm test` and `npm run build` pass in `web/`; CI is green on the pull request(s).
- The Playwright suite proves: Perspective mounts in the sandbox over Arrow; a bar-line view turns into a manual step through "To code" that runs; a custom view saves to the library and `search_components` can find it in a later step (covered by the route test and `ComponentLibrary` reading disk on every call).
- `GET /libraries` reports both licensed libraries disabled on a default config; with a key and a real install path, the library is served under `/libs/` with the CORS header and the agent's guide lists it.
- An exported notebook validates with `nbformat` and runs; `quarry projects list` and `quarry projects export` work against a root with no server running.
- Every built-in in spec section 9 exists under `src/quarry/components/builtin/` with a manifest, a vitest test, and pushes its grouping, filtering and sorting into its query spec.
- `docs/open-items.md` no longer lists the Stage 5 section, and every deferral above is recorded there with its reason.
