import { describe, expect, it, vi } from "vitest";
import { SharedStateHub, sharedKeys } from "./SharedStateHub";

describe("SharedStateHub", () => {
  it("extracts shared keys", () => {
    expect(sharedKeys({ "shared:ticker": "AAPL", limit: 5 })).toEqual({
      "shared:ticker": "AAPL",
    });
  });

  it("sends every other card only the shared keys a change touched", () => {
    const hub = new SharedStateHub();
    const a = vi.fn();
    const b = vi.fn();
    hub.register("a", { "shared:ticker": "AAPL", "shared:range": "1y" }, a);
    hub.register("b", { "shared:ticker": "AAPL", "shared:range": "1y" }, b);
    hub.report("a", { "shared:ticker": "NVDA", "shared:range": "1y", n: 9 });
    expect(a).not.toHaveBeenCalled();
    // b merges the ticker alone, so a range it has just set and not yet reported stays.
    expect(b).toHaveBeenCalledWith({ "shared:ticker": "NVDA" });
    hub.report("b", { "shared:ticker": "NVDA", "shared:range": "5y" });
    expect(a).toHaveBeenCalledWith({ "shared:range": "5y" });
  });

  it("stops after unregister", () => {
    const hub = new SharedStateHub();
    const b = vi.fn();
    hub.register("a", {}, () => undefined);
    const off = hub.register("b", {}, b);
    hub.report("a", { "shared:k": true });
    off();
    hub.report("a", { "shared:k": false });
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("does nothing when no shared key changed", () => {
    const hub = new SharedStateHub();
    const b = vi.fn();
    hub.register("a", { "shared:k": 1 }, () => undefined);
    hub.register("b", {}, b);
    hub.report("a", { "shared:k": 1, limit: 3 });
    expect(b).not.toHaveBeenCalled();
  });
});
