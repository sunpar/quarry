import { describe, expect, it, vi } from "vitest";
import { SharedStateHub, sharedKeys } from "./SharedStateHub";

describe("SharedStateHub", () => {
  it("extracts shared keys", () => {
    expect(sharedKeys({ "shared:ticker": "AAPL", limit: 5 })).toEqual({
      "shared:ticker": "AAPL",
    });
  });

  it("fans a shared change out to every other card merged with its own state", () => {
    const hub = new SharedStateHub();
    const a = vi.fn();
    const b = vi.fn();
    hub.register("a", { "shared:ticker": "AAPL", limit: 5 }, a);
    hub.register("b", { "shared:ticker": "MSFT", sort: null }, b);
    expect(a).not.toHaveBeenCalled();
    expect(b).not.toHaveBeenCalled();
    hub.report("a", { "shared:ticker": "NVDA", limit: 9 });
    expect(a).not.toHaveBeenCalled();
    expect(b).toHaveBeenCalledWith({ "shared:ticker": "NVDA", sort: null });
  });

  it("uses the latest reported state as the merge base and stops after unregister", () => {
    const hub = new SharedStateHub();
    const b = vi.fn();
    hub.register("a", {}, () => undefined);
    const off = hub.register("b", { x: 1 }, b);
    hub.report("b", { x: 2 });
    hub.report("a", { "shared:k": true });
    expect(b).toHaveBeenLastCalledWith({ x: 2, "shared:k": true });
    off();
    hub.report("a", { "shared:k": false });
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("does nothing when the change carries no shared keys", () => {
    const hub = new SharedStateHub();
    const b = vi.fn();
    hub.register("a", {}, () => undefined);
    hub.register("b", {}, b);
    hub.report("a", { limit: 3 });
    expect(b).not.toHaveBeenCalled();
  });
});
