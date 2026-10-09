import { describe, expect, it, vi } from "vitest";
import type { RuntimeToHost } from "@/shared/bridge-types";
import { RuntimeBridge } from "./bridge";

function setup() {
  const sent: RuntimeToHost[] = [];
  const bridge = new RuntimeBridge("v1", (m) => sent.push(m));
  return { bridge, sent };
}

describe("RuntimeBridge", () => {
  it("resolves a query with the matching id", async () => {
    const { bridge, sent } = setup();
    const promise = bridge.query({ dataset: "df" });
    const msg = sent[0];
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
    await expect(promise).resolves.toMatchObject({ row_count: 0 });
  });

  it("rejects on error results and ignores foreign ids", async () => {
    const { bridge, sent } = setup();
    const promise = bridge.query({ dataset: "df" });
    bridge.handle({
      type: "queryResult",
      viewId: "v1",
      id: "nope",
      ok: false,
      error: "x",
    });
    const msg = sent[0];
    if (msg?.type !== "query") throw new Error("expected query");
    bridge.handle({
      type: "queryResult",
      viewId: "v1",
      id: msg.id,
      ok: false,
      error: "bad",
    });
    await expect(promise).rejects.toThrow("bad");
  });

  it("stateChanged carries the specs used since the last change, once each", () => {
    const { bridge, sent } = setup();
    bridge.useQuery({ dataset: "a" });
    bridge.useQuery({ dataset: "a" });
    bridge.stateChanged({ k: 1 });
    bridge.useQuery({ dataset: "b" });
    bridge.stateChanged({ k: 2 });
    const changes = sent.filter((m) => m.type === "stateChanged");
    expect(
      changes.map((m) => (m.type === "stateChanged" ? m.queries : [])),
    ).toEqual([[{ dataset: "a" }], [{ dataset: "b" }]]);
  });

  it("ignores messages for other views", () => {
    const { bridge } = setup();
    const spy = vi.fn();
    bridge.handle({ type: "restore", viewId: "other", state: {} }, spy);
    expect(spy).not.toHaveBeenCalled();
  });
});
