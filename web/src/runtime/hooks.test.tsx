import { act, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import type { RuntimeToHost } from "@/shared/bridge-types";
import { RuntimeBridge } from "./bridge";
import { RequestCache } from "./cache";
import { RuntimeProvider } from "./context";
import { useDatasetSchema, useQuery, useViewState } from "./hooks";
import { ViewStateStore } from "./state";

function harness() {
  const sent: RuntimeToHost[] = [];
  const bridge = new RuntimeBridge("v1", (m) => sent.push(m));
  const store = new ViewStateStore({ limit: 10 }, () => undefined, 0);
  const cache = new RequestCache(bridge);
  const wrap = (ui: ReactNode) => (
    <RuntimeProvider value={{ bridge, store, cache }}>{ui}</RuntimeProvider>
  );
  return { bridge, store, cache, sent, wrap };
}

function Probe() {
  const [limit, setLimit] = useViewState<number>("limit", 5);
  const q = useQuery({ dataset: "df", limit });
  const schema = useDatasetSchema("df");
  return (
    <div>
      <span data-testid="status">{q.status}</span>
      <span data-testid="limit">{limit}</span>
      <span data-testid="schema">
        {schema === null ? "none" : schema.length}
      </span>
      <button onClick={() => setLimit(limit + 1)}>more</button>
    </div>
  );
}

function ArrowProbe() {
  const q = useQuery({ dataset: "df", format: "arrow" });
  if (q.status !== "success")
    return <span data-testid="status">{q.status}</span>;
  return (
    <div>
      <span data-testid="status">{q.status}</span>
      <span data-testid="rows">{q.rows.length}</span>
      <span data-testid="arrow">
        {q.arrow === null ? "none" : [...new Uint8Array(q.arrow)].join(",")}
      </span>
    </div>
  );
}

describe("hooks", () => {
  it("useQuery goes loading -> success and dedupes identical specs", async () => {
    const { bridge, sent, wrap } = harness();
    render(wrap(<Probe />));
    expect(screen.getByTestId("status").textContent).toBe("loading");
    const queries = sent.filter((m) => m.type === "query");
    expect(queries).toHaveLength(1);
    const msg = queries[0];
    if (msg?.type !== "query") throw new Error("expected query");
    await act(async () => {
      bridge.handle({
        type: "queryResult",
        viewId: "v1",
        id: msg.id,
        ok: true,
        result: {
          schema: [],
          rows: [],
          arrow_base64: null,
          row_count: 0,
          truncated: false,
        },
      });
    });
    expect(screen.getByTestId("status").textContent).toBe("success");
  });

  it("exposes arrow bytes for an arrow query", async () => {
    const { bridge, sent, wrap } = harness();
    render(wrap(<ArrowProbe />));
    const msg = sent.find((m) => m.type === "query");
    if (msg?.type !== "query") throw new Error("expected query");
    expect(msg.spec).toEqual({ dataset: "df", format: "arrow" });
    await act(async () => {
      bridge.handle({
        type: "queryResult",
        viewId: "v1",
        id: msg.id,
        ok: true,
        result: {
          schema: [{ name: "a", dtype: "Int64" }],
          rows: null,
          arrow_base64: "AAEC",
          row_count: 1,
          truncated: false,
        },
      });
    });
    expect(screen.getByTestId("status").textContent).toBe("success");
    expect(screen.getByTestId("rows").textContent).toBe("0");
    expect(screen.getByTestId("arrow").textContent).toBe("0,1,2");
  });

  it("a snapshot carries the specs its mounted hooks hold", () => {
    const { bridge, sent, wrap } = harness();
    const Held = ({ dataset }: { dataset: string }) => {
      useQuery({ dataset });
      return null;
    };
    const { rerender } = render(
      wrap(
        <>
          <Held key="a1" dataset="a" />
          <Held key="a2" dataset="a" />
          <Held key="b" dataset="b" />
        </>,
      ),
    );
    bridge.stateChanged({});
    // Held, not merely rendered: a report with no render between still carries both.
    bridge.stateChanged({});
    // One of the two hooks holding `a` unmounts; the other still holds it.
    rerender(
      wrap(
        <>
          <Held key="a1" dataset="a" />
          <Held key="b" dataset="b" />
        </>,
      ),
    );
    bridge.stateChanged({});
    rerender(wrap(<Held key="b" dataset="b" />));
    bridge.stateChanged({});
    const changes = sent.filter((m) => m.type === "stateChanged");
    expect(
      changes.map((m) => (m.type === "stateChanged" ? m.queries : [])),
    ).toEqual([
      [{ dataset: "a" }, { dataset: "b" }],
      [{ dataset: "a" }, { dataset: "b" }],
      [{ dataset: "a" }, { dataset: "b" }],
      [{ dataset: "b" }],
    ]);
  });

  it("refresh refetches every cached answer and keeps it shown meanwhile", async () => {
    const { bridge, cache, sent } = harness();
    const spec = { dataset: "df" };
    const answer = (id: string, rowCount: number) =>
      bridge.handle({
        type: "queryResult",
        viewId: "v1",
        id,
        ok: true,
        result: {
          schema: [],
          rows: [],
          arrow_base64: null,
          row_count: rowCount,
          truncated: false,
        },
      });
    const lastQueryId = () => {
      const msg = sent.filter((m) => m.type === "query").at(-1);
      if (msg?.type !== "query") throw new Error("expected query");
      return msg.id;
    };
    cache.ensureQuery(spec);
    answer(lastQueryId(), 1);
    await Promise.resolve();
    const before = cache.ensureQuery(spec);
    expect(sent.filter((m) => m.type === "query")).toHaveLength(1);
    cache.refresh();
    expect(cache.ensureQuery(spec)).toBe(before);
    expect(cache.ensureQuery(spec)).toBe(before);
    expect(sent.filter((m) => m.type === "query")).toHaveLength(2);
    answer(lastQueryId(), 2);
    await Promise.resolve();
    const after = cache.ensureQuery(spec);
    expect(after.status === "success" && after.result.row_count).toBe(2);
  });

  it("drops an answer that a refresh superseded, even when it arrives last", async () => {
    const { bridge, cache, sent } = harness();
    const spec = { dataset: "df" };
    const ids = () => sent.flatMap((m) => (m.type === "query" ? [m.id] : []));
    const answer = (id: string | undefined, rowCount: number) =>
      bridge.handle({
        type: "queryResult",
        viewId: "v1",
        id: id ?? "",
        ok: true,
        result: {
          schema: [],
          rows: [],
          arrow_base64: null,
          row_count: rowCount,
          truncated: false,
        },
      });
    cache.ensureQuery(spec);
    cache.refresh();
    cache.ensureQuery(spec);
    const [first, second] = ids();
    answer(second, 2);
    answer(first, 1);
    await Promise.resolve();
    const state = cache.ensureQuery(spec);
    expect(state.status === "success" && state.result.row_count).toBe(2);
  });

  it("useViewState reads the mounted state and re-queries on change", async () => {
    const { sent, wrap } = harness();
    render(wrap(<Probe />));
    expect(screen.getByTestId("limit").textContent).toBe("10");
    await act(async () => {
      screen.getByText("more").click();
    });
    expect(screen.getByTestId("limit").textContent).toBe("11");
    const specs = sent
      .filter((m) => m.type === "query")
      .map((m) => (m.type === "query" ? m.spec : null));
    expect(specs).toEqual([
      { dataset: "df", limit: 10 },
      { dataset: "df", limit: 11 },
    ]);
  });

  it("useDatasetSchema resolves through the bridge", async () => {
    const { bridge, sent, wrap } = harness();
    render(wrap(<Probe />));
    const msg = sent.find((m) => m.type === "schema");
    if (msg?.type !== "schema") throw new Error("expected schema request");
    await act(async () => {
      bridge.handle({
        type: "schemaResult",
        viewId: "v1",
        id: msg.id,
        ok: true,
        schema: [{ name: "a", dtype: "Int64" }],
      });
    });
    expect(screen.getByTestId("schema").textContent).toBe("1");
  });
});
