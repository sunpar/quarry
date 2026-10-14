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
  const ready = () => {
    const connection = posted.findLast((m) => m.type === "connect");
    if (connection?.type !== "connect") throw new Error("not connected");
    send({ type: "ready", id: connection.id });
  };
  return { bridge, posted, send, ready, onQuery, onStateChanged, onError };
}

describe("HostBridge", () => {
  it("holds the latest restore for the new mount, with later linked changes overlaid", () => {
    const { bridge, posted, ready } = setup();
    bridge.connect();
    bridge.mount({ source: "first", initialState: {}, datasets: [] });
    ready();
    posted.length = 0;
    bridge.connect();
    bridge.restore({ n: 1 });
    bridge.merge({ "shared:k": "before" });
    bridge.restore({ n: 2, "shared:k": "restored" });
    bridge.merge({ "shared:k": "after" });
    expect(posted.map((m) => m.type)).toEqual(["connect"]);
    ready();
    expect(posted.map((m) => m.type)).toEqual([
      "connect",
      "mount",
      "restore",
      "merge",
    ]);
    expect(posted[2]).toMatchObject({
      state: { n: 2, "shared:k": "restored" },
    });
    expect(posted[3]).toMatchObject({ state: { "shared:k": "after" } });
  });

  it("queues changed content and linked state until a reloaded frame acknowledges connect", () => {
    const { bridge, posted, ready } = setup();
    bridge.connect();
    bridge.mount({ source: "first", initialState: {}, datasets: [] });
    ready();
    posted.length = 0;
    bridge.connect();
    bridge.mount({ source: "next", initialState: {}, datasets: [] });
    bridge.merge({ "shared:k": 2 });
    expect(posted).toEqual([
      expect.objectContaining({ type: "connect", viewId: "v1" }),
    ]);
    ready();
    expect(posted.map((m) => m.type)).toEqual(["connect", "mount", "merge"]);
    expect(posted[1]).toMatchObject({ source: "next" });
    expect(posted[2]).toMatchObject({ state: { "shared:k": 2 } });
  });

  it("detaches pending reply subscriptions when its listener stops", async () => {
    const posted: HostToRuntime[] = [];
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const bridge = new HostBridge({
      viewId: "v1",
      frame: { postMessage: (m) => posted.push(m) },
      isFrame: () => true,
      onQuery: async () => {
        await gate;
        return {
          schema: [],
          rows: [],
          arrow_base64: null,
          row_count: 0,
          truncated: false,
        };
      },
      onSchema: async () => {
        await gate;
        return [];
      },
      onStateChanged: () => undefined,
      onError: () => undefined,
    });
    const stop = bridge.listen(window);
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "query", viewId: "v1", id: "q", spec: { dataset: "df" } },
      }),
    );
    window.dispatchEvent(
      new MessageEvent("message", {
        data: { type: "schema", viewId: "v1", id: "s", dataset: "df" },
      }),
    );
    stop();
    release();
    await gate;
    await Promise.resolve();
    expect(posted).toHaveLength(0);
  });

  it("mounts after ready and answers queries", async () => {
    const { bridge, posted, send, ready, onQuery } = setup();
    const licensed: LicensedLibrary[] = [
      { id: "highcharts", entry: "/libs/h.js", license: null },
    ];
    bridge.mount({ source: "x", initialState: {}, datasets: ["df"], licensed });
    expect(posted).toHaveLength(0);
    bridge.connect();
    ready();
    expect(posted[1]).toMatchObject({
      type: "mount",
      viewId: "v1",
      datasets: ["df"],
      licensed,
    });
    send({ type: "query", viewId: "v1", id: "q1", spec: { dataset: "df" } });
    await vi.waitFor(() => expect(posted).toHaveLength(3));
    expect(onQuery).toHaveBeenCalledWith({ dataset: "df" });
    expect(posted[2]).toMatchObject({
      type: "queryResult",
      id: "q1",
      ok: true,
    });
  });

  it("connects before mounting, then waits for the acknowledgment", () => {
    const { bridge, posted, ready } = setup();
    bridge.mount({ source: "x", initialState: {}, datasets: ["df"] });
    bridge.connect();
    expect(posted).toEqual([
      expect.objectContaining({ type: "connect", viewId: "v1" }),
    ]);
    ready();
    expect(posted[1]).toMatchObject({ type: "mount", viewId: "v1" });
  });

  it("holds linked keys that arrive before the view mounts", () => {
    const { bridge, posted, ready } = setup();
    bridge.merge({ "shared:k": 1 });
    bridge.merge({ "shared:j": 2 });
    bridge.connect();
    ready();
    expect(posted).toHaveLength(1); // ready, but nothing mounted to merge into
    bridge.mount({ source: "x", initialState: {}, datasets: [] });
    expect(posted.map((m) => m.type)).toEqual(["connect", "mount", "merge"]);
    expect(posted[2]).toMatchObject({
      state: { "shared:k": 1, "shared:j": 2 },
    });
    bridge.merge({ "shared:k": 3 });
    expect(posted[3]).toMatchObject({
      type: "merge",
      state: { "shared:k": 3 },
    });
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

  it("consumes only the current connection's acknowledgment once", () => {
    const { bridge, posted, send } = setup();
    bridge.mount({ source: "x", initialState: {}, datasets: ["df"] });
    bridge.connect();
    const first = posted[0];
    bridge.connect();
    const second = posted[1];
    if (first?.type !== "connect" || second?.type !== "connect")
      throw new Error("not connected");
    expect(first.id).not.toBe(second.id);
    send({ type: "ready" });
    send({ type: "ready", id: "other" });
    send({ type: "ready", id: first.id });
    expect(posted).toHaveLength(2);
    send({ type: "ready", id: second.id });
    send({ type: "ready", id: second.id });
    expect(posted).toHaveLength(3);
    expect(posted[2]).toMatchObject({ type: "mount" });
  });

  it("cancels an acknowledgment subscription when its listener stops", () => {
    const { bridge, posted, ready } = setup();
    const stop = bridge.listen(window);
    bridge.mount({ source: "x", initialState: {}, datasets: [] });
    bridge.connect();
    stop();
    ready();
    expect(posted).toHaveLength(1);
  });

  it("queues a restore after ready until there is a mount", () => {
    const { bridge, posted, ready } = setup();
    bridge.connect();
    ready();
    bridge.restore({ n: 7 });
    expect(posted).toHaveLength(1);
    bridge.mount({ source: "x", initialState: { n: 1 }, datasets: [] });
    expect(posted.map((m) => m.type)).toEqual(["connect", "mount", "restore"]);
    expect(posted[1]).toMatchObject({ initialState: { n: 1 } });
    expect(posted[2]).toMatchObject({ state: { n: 7 } });
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
