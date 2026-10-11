import { describe, expect, it, vi } from "vitest";
import { SharedStateHub, sharedKeys } from "./SharedStateHub";

describe("SharedStateHub", () => {
  it("extracts shared keys", () => {
    expect(sharedKeys({ "shared:ticker": "AAPL", limit: 5 })).toEqual({
      "shared:ticker": "AAPL",
    });
  });

  it("sends every other card only the shared keys of a change", () => {
    const hub = new SharedStateHub();
    const a = vi.fn();
    const b = vi.fn();
    hub.register("a", a);
    hub.register("b", b);
    hub.report("a", { "shared:ticker": "NVDA", limit: 9 });
    expect(a).not.toHaveBeenCalled();
    // b merges the key into its own state, so a setting it has not reported yet stays.
    expect(b).toHaveBeenCalledWith({ "shared:ticker": "NVDA" });
  });

  it("stops after unregister", () => {
    const hub = new SharedStateHub();
    const b = vi.fn();
    hub.register("a", () => undefined);
    const off = hub.register("b", b);
    hub.report("a", { "shared:k": true });
    off();
    hub.report("a", { "shared:k": false });
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("does nothing when the change carries no shared keys", () => {
    const hub = new SharedStateHub();
    const b = vi.fn();
    hub.register("a", () => undefined);
    hub.register("b", b);
    hub.report("a", { limit: 3 });
    expect(b).not.toHaveBeenCalled();
  });
});
