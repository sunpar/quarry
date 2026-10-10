import { act, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { QuerySpec } from "@/shared/api-types";
import type { RuntimeToHost } from "@/shared/bridge-types";
import type { ModuleTable } from "./loader";
import { createRuntime } from "./mount";

const table = {
  react: () => import("react").then((m) => ({ __esModule: true, ...m })),
  "react/jsx-runtime": () =>
    import("react/jsx-runtime").then((m) => ({ __esModule: true, ...m })),
  "@quarry/hooks": () =>
    import("./hooks").then((m) => ({ __esModule: true, ...m })),
} satisfies ModuleTable;

const QUERY_VIEW = `
  import { useQuery, useViewState } from "@quarry/hooks";
  export default function V() {
    const [n, setN] = useViewState("n", 1);
    useQuery({ dataset: "df", limit: n });
    return <button onClick={() => setN(n + 1)}>more</button>;
  }`;

// Asks for one row until the schema names a key, as the chart built-ins do.
const LATE_SCHEMA_VIEW = `
  import { useDatasetSchema, useQuery } from "@quarry/hooks";
  export default function V() {
    const schema = useDatasetSchema("df");
    const key = schema === null ? null : schema[0].name;
    useQuery(key === null ? { dataset: "df", limit: 1 } : { dataset: "df", group_by: [key], aggs: [{ col: key, fn: "count" }] });
    return <p>{key ?? "waiting"}</p>;
  }`;
const FINAL: QuerySpec = {
  dataset: "df",
  group_by: ["sector"],
  aggs: [{ col: "sector", fn: "count" }],
};

beforeEach(() => vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] }));
afterEach(() => vi.useRealTimers());

// Roots stay in the document between tests, so each test looks only inside its own.
async function mount(source: string, initialState = {}, viewId = "v1") {
  const sent: RuntimeToHost[] = [];
  const root = document.createElement("div");
  document.body.appendChild(root);
  const runtime = createRuntime((m) => sent.push(m), root, table);
  await act(async () => {
    runtime.handle({
      type: "mount",
      viewId,
      source,
      initialState,
      datasets: ["df"],
    });
  });
  const reports = () => sent.filter((m) => m.type === "stateChanged");
  const runTimers = () => act(async () => void vi.runAllTimers());
  return { runtime, sent, view: within(root), reports, runTimers };
}

async function answerSchema(m: Awaited<ReturnType<typeof mount>>) {
  await vi.waitFor(() =>
    expect(m.sent.some((s) => s.type === "schema")).toBe(true),
  );
  const asked = m.sent.find((s) => s.type === "schema");
  if (asked?.type !== "schema") throw new Error("expected a schema request");
  await act(async () => {
    m.runtime.handle({
      type: "schemaResult",
      viewId: "v1",
      id: asked.id,
      ok: true,
      schema: [{ name: "sector", dtype: "String" }],
    });
  });
  await vi.waitFor(() => expect(m.view.getByText("sector")).toBeTruthy());
}

describe("runtime query reports", () => {
  it("reports a mounted view's state and queries once, unprompted", async () => {
    const m = await mount(QUERY_VIEW, { n: 5 });
    await vi.waitFor(() => expect(m.view.getByText("more")).toBeTruthy());
    await m.runTimers();
    expect(m.reports()).toHaveLength(1);
    expect(m.reports()[0]).toMatchObject({
      viewId: "v1",
      state: { n: 5 },
      queries: [{ dataset: "df", limit: 5 }],
    });
  });

  it("snapshots carry only the queries of the state they record", async () => {
    const m = await mount(QUERY_VIEW);
    await vi.waitFor(() => expect(m.view.getByText("more")).toBeTruthy());
    await act(async () => m.view.getByText("more").click());
    await m.runTimers();
    expect(m.reports().at(-1)).toMatchObject({
      state: { n: 2 },
      queries: [{ dataset: "df", limit: 2 }],
    });
  });

  it("drops a placeholder the schema replaced before the first report", async () => {
    const m = await mount(LATE_SCHEMA_VIEW);
    await answerSchema(m);
    await m.runTimers();
    expect(m.reports()).toHaveLength(1);
    expect(m.reports()[0]).toMatchObject({ queries: [FINAL] });
  });

  it("reports the final query when the schema comes after the first report", async () => {
    const m = await mount(LATE_SCHEMA_VIEW);
    await m.runTimers();
    expect(m.reports().at(-1)).toMatchObject({
      queries: [{ dataset: "df", limit: 1 }],
    });
    await answerSchema(m);
    await m.runTimers();
    expect(m.reports()).toHaveLength(2);
    expect(m.reports().at(-1)).toMatchObject({ queries: [FINAL] });
  });

  it("reports nothing for the queries a restored state brings", async () => {
    const m = await mount(QUERY_VIEW, { n: 5 });
    await m.runTimers();
    await act(async () => {
      m.runtime.handle({ type: "restore", viewId: "v1", state: { n: 9 } });
    });
    await vi.waitFor(() =>
      expect(m.sent).toContainEqual(
        expect.objectContaining({ spec: { dataset: "df", limit: 9 } }),
      ),
    );
    await m.runTimers();
    expect(m.reports()).toHaveLength(1);
  });

  it("a replaced view reports nothing as its hooks let go", async () => {
    const m = await mount(QUERY_VIEW, { n: 5 });
    await m.runTimers();
    await act(async () => {
      m.runtime.handle({
        type: "mount",
        viewId: "v1",
        source: `export default () => <p>next-view</p>;`,
        initialState: {},
        datasets: [],
      });
    });
    await vi.waitFor(() => expect(m.view.getByText("next-view")).toBeTruthy());
    await m.runTimers();
    expect(m.reports()).toHaveLength(1);
  });

  it("a view replaced within the debounce reports only its successor", async () => {
    const m = await mount(QUERY_VIEW, { n: 5 });
    await vi.waitFor(() => expect(m.view.getByText("more")).toBeTruthy());
    await act(async () => {
      m.runtime.handle({
        type: "mount",
        viewId: "v1",
        source: QUERY_VIEW,
        initialState: { n: 7 },
        datasets: ["df"],
      });
    });
    await m.runTimers();
    expect(m.reports()).toEqual([
      expect.objectContaining({ queries: [{ dataset: "df", limit: 7 }] }),
    ]);
  });
});
