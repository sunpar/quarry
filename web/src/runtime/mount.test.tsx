import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { RuntimeToHost } from "@/shared/bridge-types";
import { licensed } from "./libs/registry";
import type { ModuleTable } from "./loader";
import { createRuntime } from "./mount";

const table = {
  react: () => import("react").then((m) => ({ __esModule: true, ...m })),
  "react/jsx-runtime": () =>
    import("react/jsx-runtime").then((m) => ({ __esModule: true, ...m })),
  "@quarry/hooks": () =>
    import("./hooks").then((m) => ({ __esModule: true, ...m })),
} satisfies ModuleTable;

function setup() {
  const sent: RuntimeToHost[] = [];
  const root = document.createElement("div");
  document.body.appendChild(root);
  const runtime = createRuntime((m) => sent.push(m), root, table);
  return { runtime, sent };
}

const QUERY_VIEW = `
  import { useQuery, useViewState } from "@quarry/hooks";
  export default function V() {
    const [n, setN] = useViewState("n", 1);
    useQuery({ dataset: "df", limit: n });
    return <button onClick={() => setN(n + 1)}>more</button>;
  }`;

describe("runtime mount", () => {
  it("posts ready, mounts a component with datasets, and restores state", async () => {
    const { runtime, sent } = setup();
    expect(sent[0]).toEqual({ type: "ready" });
    const source = `
      import { useViewState } from "@quarry/hooks";
      export default function V({ datasets }) {
        const [n] = useViewState("n", 0);
        return <p>{datasets.join(",")}:{n}</p>;
      }`;
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v1",
        source,
        initialState: { n: 1 },
        datasets: ["df"],
        licensed: [{ id: "highcharts", entry: "/libs/h.js", license: null }],
      });
    });
    await waitFor(() => expect(screen.getByText("df:1")).toBeTruthy());
    expect(licensed("highcharts")?.entry).toBe("/libs/h.js");
    await act(async () => {
      runtime.handle({ type: "restore", viewId: "v1", state: { n: 7 } });
    });
    await waitFor(() => expect(screen.getByText("df:7")).toBeTruthy());
  });

  it("snapshots carry only the queries of the state they record", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const { runtime, sent } = setup();
      await act(async () => {
        runtime.handle({
          type: "mount",
          viewId: "v9",
          source: QUERY_VIEW,
          initialState: {},
          datasets: ["df"],
        });
      });
      await vi.waitFor(() => expect(screen.getByText("more")).toBeTruthy());
      await act(async () => {
        screen.getByText("more").click();
      });
      await act(async () => {
        vi.runAllTimers();
      });
      const change = sent.find((m) => m.type === "stateChanged");
      expect(change).toMatchObject({
        state: { n: 2 },
        queries: [{ dataset: "df", limit: 2 }],
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("reports the mount-time state and queries once, unprompted", async () => {
    vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
    try {
      const { runtime, sent } = setup();
      await act(async () => {
        runtime.handle({
          type: "mount",
          viewId: "v1",
          source: QUERY_VIEW,
          initialState: { n: 5 },
          datasets: ["df"],
        });
      });
      // The view has rendered once it has asked for its data.
      await vi.waitFor(() =>
        expect(sent.some((m) => m.type === "query")).toBe(true),
      );
      await act(async () => {
        vi.runAllTimers();
      });
      const reported = sent.filter((m) => m.type === "stateChanged");
      expect(reported).toHaveLength(1);
      expect(reported[0]).toMatchObject({
        viewId: "v1",
        state: { n: 5 },
        queries: [{ dataset: "df", limit: 5 }],
      });
    } finally {
      vi.useRealTimers();
    }
  });

  it("posts error when the component throws during render", async () => {
    const { runtime, sent } = setup();
    const source = `export default function V() { throw new Error("boom"); }`;
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v2",
        source,
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() =>
      expect(
        sent.some((m) => m.type === "error" && m.message.includes("boom")),
      ).toBe(true),
    );
  });

  it("posts error when an import is refused", async () => {
    const { runtime, sent } = setup();
    const source = `import d3 from "d3"; export default () => null;`;
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v3",
        source,
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() =>
      expect(
        sent.some(
          (m) => m.type === "error" && m.message.includes("not available"),
        ),
      ).toBe(true),
    );
  });

  it("forwards a late error to the mounted view's host", async () => {
    const { runtime, sent } = setup();
    runtime.reportError(new Error("before mount"));
    expect(sent.some((m) => m.type === "error")).toBe(false);
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v4",
        source: `export default () => <p>late-view</p>;`,
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() => expect(screen.getByText("late-view")).toBeTruthy());
    runtime.reportError(new Error("late"));
    expect(sent).toContainEqual(
      expect.objectContaining({ type: "error", viewId: "v4", message: "late" }),
    );
  });

  it("ignores a stale mount once a newer mount arrives", async () => {
    let release: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    let calls = 0;
    const slowTable = {
      ...table,
      "@quarry/hooks": async () => {
        if (calls++ === 0) await gate;
        return { __esModule: true, ...(await import("./hooks")) };
      },
    } satisfies ModuleTable;
    const root = document.createElement("div");
    document.body.appendChild(root);
    const runtime = createRuntime(() => {}, root, slowTable);
    const view = (label: string) => `
      import { useViewState } from "@quarry/hooks";
      export default function V() {
        useViewState("n", 0);
        return <p>${label}</p>;
      }`;
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "a",
        source: view("first-view"),
        initialState: {},
        datasets: [],
      });
      runtime.handle({
        type: "mount",
        viewId: "b",
        source: view("second-view"),
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() => expect(screen.getByText("second-view")).toBeTruthy());
    await act(async () => {
      release();
    });
    expect(screen.queryByText("first-view")).toBeNull();
    expect(screen.getByText("second-view")).toBeTruthy();
  });
});
