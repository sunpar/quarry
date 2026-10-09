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

  it("useQuery reports an Arrow result as an error", async () => {
    const { bridge, sent, wrap } = harness();
    render(wrap(<Probe />));
    const msg = sent.find((m) => m.type === "query");
    if (msg?.type !== "query") throw new Error("expected query");
    await act(async () => {
      bridge.handle({
        type: "queryResult",
        viewId: "v1",
        id: msg.id,
        ok: true,
        result: {
          schema: [],
          rows: null,
          arrow_base64: "QVJST1cx",
          row_count: 1,
          truncated: false,
        },
      });
    });
    expect(screen.getByTestId("status").textContent).toBe("error");
  });

  it("records a query served from cache for the next state change", async () => {
    const { bridge, cache, sent } = harness();
    const spec = { dataset: "df" };
    cache.ensureQuery(spec);
    const msg = sent.find((m) => m.type === "query");
    if (msg?.type !== "query") throw new Error("expected query");
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
    await Promise.resolve();
    bridge.stateChanged({});
    expect(cache.ensureQuery(spec).status).toBe("success");
    bridge.stateChanged({});
    const changes = sent.filter((m) => m.type === "stateChanged");
    expect(changes.at(-1)).toMatchObject({ queries: [spec] });
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
