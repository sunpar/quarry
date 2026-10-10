import { describe, expect, it, vi } from "vitest";
import type { HostToRuntime } from "@/shared/bridge-types";
import type { LicensedLibrary } from "@/shared/library-types";
import { HostBridge } from "./HostBridge";

function setup() {
  const posted: HostToRuntime[] = [];
  const frameWindow = { postMessage: (m: HostToRuntime) => posted.push(m) };
  const onQuery = vi.fn(async () => ({
    schema: [],
    rows: [{ a: 1 }],
    arrow_base64: null,
    row_count: 1,
    truncated: false,
  }));
  const onStateChanged = vi.fn();
  const onError = vi.fn();
  const bridge = new HostBridge({
    viewId: "v1",
    frame: frameWindow,
    isFrame: (source) => source === frameWindow,
    onQuery,
    onSchema: async () => [],
    onStateChanged,
    onError,
  });
  // jsdom rejects a plain object as MessageEvent.source, so tests feed handleEvent directly.
  const send = (data: unknown, source: unknown = frameWindow) =>
    bridge.handleEvent({ data, source });
  return { bridge, posted, send, onQuery, onStateChanged, onError };
}

describe("HostBridge", () => {
  it("mounts after ready and answers queries", async () => {
    const { bridge, posted, send, onQuery } = setup();
    const licensed: LicensedLibrary[] = [
      { id: "highcharts", entry: "/libs/h.js", license: null },
    ];
    bridge.mount({ source: "x", initialState: {}, datasets: ["df"], licensed });
    expect(posted).toHaveLength(0);
    send({ type: "ready" });
    expect(posted[0]).toMatchObject({
      type: "mount",
      viewId: "v1",
      datasets: ["df"],
      licensed,
    });
    send({ type: "query", viewId: "v1", id: "q1", spec: { dataset: "df" } });
    await vi.waitFor(() => expect(posted).toHaveLength(2));
    expect(onQuery).toHaveBeenCalledWith({ dataset: "df" });
    expect(posted[1]).toMatchObject({
      type: "queryResult",
      id: "q1",
      ok: true,
    });
  });

  it("mounts on the frame's load when ready was missed, once", () => {
    const { bridge, posted, send } = setup();
    bridge.mount({ source: "x", initialState: {}, datasets: ["df"] });
    bridge.frameLoaded();
    bridge.frameLoaded();
    expect(posted).toHaveLength(1);
    expect(posted[0]).toMatchObject({ type: "mount", viewId: "v1" });
    send({ type: "ready" });
    bridge.frameLoaded();
    expect(posted).toHaveLength(2);
  });

  it("drops runtime messages whose fields have the wrong shape", () => {
    const { send, onQuery, onError, onStateChanged } = setup();
    send({ type: "error", viewId: "v1", message: { not: "text" } });
    send({ type: "query", viewId: "v1", spec: { dataset: "df" } });
    send({ type: "stateChanged", viewId: "v1", state: {}, queries: "all" });
    send({ type: "unknown", viewId: "v1" });
    expect(onError).not.toHaveBeenCalled();
    expect(onQuery).not.toHaveBeenCalled();
    expect(onStateChanged).not.toHaveBeenCalled();
  });

  it("resends the mount on every ready", () => {
    const { bridge, posted, send } = setup();
    bridge.mount({ source: "x", initialState: {}, datasets: ["df"] });
    send({ type: "ready" });
    send({ type: "ready" });
    expect(posted).toHaveLength(2);
    expect(posted[1]).toEqual(posted[0]);
  });

  it("ignores messages from other sources", () => {
    const { posted, send, onStateChanged } = setup();
    send(
      { type: "stateChanged", viewId: "v1", state: {}, queries: [] },
      window,
    );
    expect(onStateChanged).not.toHaveBeenCalled();
    expect(posted).toHaveLength(0);
  });

  it("forwards stateChanged and error", () => {
    const { send, onStateChanged, onError } = setup();
    send({
      type: "stateChanged",
      viewId: "v1",
      state: { k: 1 },
      queries: [{ dataset: "df" }],
    });
    expect(onStateChanged).toHaveBeenCalledWith({ k: 1 }, [{ dataset: "df" }]);
    send({ type: "error", viewId: "v1", message: "boom" });
    expect(onError).toHaveBeenCalledWith("boom", undefined);
  });

  it("reports query failures as error results", async () => {
    const posted: HostToRuntime[] = [];
    const failing = new HostBridge({
      viewId: "v2",
      frame: { postMessage: (m) => posted.push(m) },
      isFrame: () => true,
      onQuery: async () => {
        throw new Error("400: bad spec");
      },
      onSchema: async () => [],
      onStateChanged: () => undefined,
      onError: () => undefined,
    });
    failing.handleEvent({
      data: { type: "query", viewId: "v2", id: "q9", spec: { dataset: "df" } },
      source: null,
    });
    await vi.waitFor(() =>
      expect(posted.at(-1)).toMatchObject({
        type: "queryResult",
        id: "q9",
        ok: false,
        error: "400: bad spec",
      }),
    );
  });

  it("listen wires window messages through handleEvent", () => {
    const { bridge } = setup();
    const spy = vi.spyOn(bridge, "handleEvent");
    const stop = bridge.listen(window);
    window.dispatchEvent(
      new MessageEvent("message", { data: { type: "ready" } }),
    );
    expect(spy).toHaveBeenCalled();
    stop();
  });
});
