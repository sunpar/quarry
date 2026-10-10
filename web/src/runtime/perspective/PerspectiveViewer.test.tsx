import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ViewerConfigUpdate } from "@finos/perspective-viewer";
import { PerspectiveViewer } from "./PerspectiveViewer";

vi.mock("./engine", () => ({
  ensureEngine: async () => ({
    table: async () => ({ delete: async () => undefined }),
  }),
}));

function deferred() {
  let resolve = () => {};
  const promise = new Promise<void>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

// Each test opens a new gate; `load` stays pending until the test resolves it.
let gate = deferred();

// The real element needs the wasm engine; this one records what the wrapper asks of it.
class FakeViewer extends HTMLElement {
  load = vi.fn(() => gate.promise);
  restore = vi.fn(async (_config: ViewerConfigUpdate) => undefined);
  save = vi.fn(async (): Promise<ViewerConfigUpdate> => ({}));
  delete = vi.fn(async () => undefined);
}
customElements.define("perspective-viewer", FakeViewer);

const arrow = new ArrayBuffer(8);

function viewerIn(container: HTMLElement): FakeViewer {
  const node = container.querySelector("perspective-viewer");
  if (!(node instanceof FakeViewer)) throw new Error("no viewer element");
  return node;
}

describe("PerspectiveViewer", () => {
  it("restores the config only after the table has loaded", async () => {
    gate = deferred();
    const config = { group_by: ["a"] };
    const { container } = render(
      <PerspectiveViewer arrow={arrow} config={config} />,
    );
    const node = viewerIn(container);
    await vi.waitFor(() => expect(node.load).toHaveBeenCalledTimes(1));
    expect(node.restore).not.toHaveBeenCalled();
    gate.resolve();
    await vi.waitFor(() => expect(node.restore).toHaveBeenCalledTimes(1));
    expect(node.restore).toHaveBeenCalledWith(config);
  });

  it("restores a changed config once, and an equal one not at all", async () => {
    gate = deferred();
    gate.resolve();
    const config = { group_by: ["a"] };
    const { container, rerender } = render(
      <PerspectiveViewer arrow={arrow} config={config} />,
    );
    const node = viewerIn(container);
    await vi.waitFor(() => expect(node.restore).toHaveBeenCalledTimes(1));
    rerender(<PerspectiveViewer arrow={arrow} config={{ group_by: ["a"] }} />);
    const next = { group_by: ["b"] };
    rerender(<PerspectiveViewer arrow={arrow} config={next} />);
    rerender(<PerspectiveViewer arrow={arrow} config={{ group_by: ["b"] }} />);
    await vi.waitFor(() => expect(node.restore).toHaveBeenCalledTimes(2));
    expect(node.restore).toHaveBeenLastCalledWith(next);
  });

  it("does not restore the config the viewer itself just saved", async () => {
    gate = deferred();
    gate.resolve();
    const onConfig = vi.fn();
    const { container, rerender } = render(
      <PerspectiveViewer arrow={arrow} config={{}} onConfig={onConfig} />,
    );
    const node = viewerIn(container);
    await vi.waitFor(() => expect(node.restore).toHaveBeenCalledTimes(1));
    const saved = { group_by: ["a"], plugin: "Datagrid" };
    node.save.mockResolvedValue(saved);
    node.dispatchEvent(new Event("perspective-config-update"));
    await vi.waitFor(() => expect(onConfig).toHaveBeenCalledWith(saved));
    rerender(
      <PerspectiveViewer arrow={arrow} config={saved} onConfig={onConfig} />,
    );
    expect(node.restore).toHaveBeenCalledTimes(1);
  });

  it("does not restore into a viewer unmounted while loading", async () => {
    gate = deferred();
    const { container, unmount } = render(
      <PerspectiveViewer arrow={arrow} config={{ group_by: ["a"] }} />,
    );
    const node = viewerIn(container);
    await vi.waitFor(() => expect(node.load).toHaveBeenCalledTimes(1));
    unmount();
    gate.resolve();
    await gate.promise;
    await Promise.resolve();
    expect(node.restore).not.toHaveBeenCalled();
  });
});
