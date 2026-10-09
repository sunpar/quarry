import { act, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
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

function setup() {
  const sent: RuntimeToHost[] = [];
  const root = document.createElement("div");
  document.body.appendChild(root);
  const runtime = createRuntime((m) => sent.push(m), root, table);
  return { runtime, sent };
}

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
      });
    });
    await waitFor(() => expect(screen.getByText("df:1")).toBeTruthy());
    await act(async () => {
      runtime.handle({ type: "restore", viewId: "v1", state: { n: 7 } });
    });
    await waitFor(() => expect(screen.getByText("df:7")).toBeTruthy());
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
});
