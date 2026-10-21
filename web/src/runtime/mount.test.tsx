import { act, screen, waitFor, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { HostBridge } from "@/host/bridge/HostBridge";
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
  return { runtime, sent, root };
}

describe("runtime mount", () => {
  it("restores during component loading before query registration without reporting a new snapshot", async () => {
    let release: () => void = () => undefined;
    const loading = new Promise<void>((resolve) => (release = resolve));
    const sent: RuntimeToHost[] = [];
    const root = document.createElement("div");
    document.body.appendChild(root);
    const runtime = createRuntime((m) => sent.push(m), root, {
      ...table,
      "@quarry/hooks": async () => {
        await loading;
        return { __esModule: true, ...(await import("./hooks")) };
      },
    });
    const bridge = new HostBridge({
      viewId: "restored",
      frame: { postMessage: (m) => runtime.handle(m) },
      isFrame: () => true,
      onQuery: async () => ({
        schema: [],
        rows: [],
        arrow_base64: null,
        row_count: 0,
        truncated: false,
      }),
      onSchema: async () => [],
      onStateChanged: () => undefined,
      onError: () => undefined,
    });
    await act(async () => {
      bridge.mount(() => ({
        source: `
        import { useQuery, useViewState } from "@quarry/hooks";
        export default function V() {
          const [n] = useViewState("n", 0);
          useQuery({ dataset: "df", limit: n });
          return <p>restored:{n}</p>;
        }`,
        initialState: { n: 1 },
        datasets: [],
      }));
      bridge.connect();
      bridge.restore({ n: 7 });
      bridge.handleEvent({ data: sent[0], source: null });
    });
    expect(sent.map((m) => m.type)).toEqual(["ready"]);
    await act(async () => release());
    await waitFor(() => expect(screen.getByText("restored:7")).toBeTruthy());
    expect(sent).toContainEqual(
      expect.objectContaining({
        type: "query",
        spec: { dataset: "df", limit: 7 },
      }),
    );
    await act(() => new Promise((resolve) => setTimeout(resolve, 400)));
    expect(sent.some((m) => m.type === "stateChanged")).toBe(false);
  });

  it("acknowledges connect, mounts a component with datasets, and restores state", async () => {
    const { runtime, sent } = setup();
    expect(sent).toHaveLength(0);
    runtime.handle({ type: "connect", viewId: "v1", id: "c1" });
    expect(sent[0]).toEqual({ type: "ready", id: "c1" });
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
    await act(async () => {
      runtime.handle({ type: "merge", viewId: "v1", state: { n: 8 } });
    });
    await waitFor(() => expect(screen.getByText("df:8")).toBeTruthy());
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

  it("drops a render error when the same view id mounts again", async () => {
    const { runtime, sent, root } = setup();
    const frame = within(root);
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v5",
        source: `export default function V() { throw new Error("broken-view"); }`,
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() => expect(frame.getByText("broken-view")).toBeTruthy());
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v5",
        source: `export default () => <p>repaired-view</p>;`,
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() => expect(frame.getByText("repaired-view")).toBeTruthy());
    expect(frame.queryByText("broken-view")).toBeNull();
    const errors = sent.filter((m) => m.type === "error");
    expect(errors).toHaveLength(1);
    expect(errors[0]).toEqual(
      expect.objectContaining({ viewId: "v5", message: "broken-view" }),
    );
  });

  it("catches an error the outgoing view throws as the same view id remounts", async () => {
    const { runtime, sent, root } = setup();
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v6",
        source: `
          import { useEffect } from "react";
          export default function V() {
            useEffect(() => () => { throw new Error("cleanup-boom"); }, []);
            return <p>outgoing-view</p>;
          }`,
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() =>
      expect(within(root).getByText("outgoing-view")).toBeTruthy(),
    );
    await act(async () => {
      runtime.handle({
        type: "mount",
        viewId: "v6",
        source: `export default () => <p>incoming-view</p>;`,
        initialState: {},
        datasets: [],
      });
    });
    await waitFor(() =>
      expect(sent).toContainEqual(
        expect.objectContaining({
          type: "error",
          viewId: "v6",
          message: expect.stringContaining("cleanup-boom"),
        }),
      ),
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
