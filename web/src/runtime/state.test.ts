import { describe, expect, it, vi } from "vitest";
import { ViewStateStore } from "./state";

describe("ViewStateStore", () => {
  it("debounces onChange and reports the whole state", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const store = new ViewStateStore({ a: 1 }, onChange, 300);
    store.set("b", 2);
    store.set("b", 3);
    expect(onChange).not.toHaveBeenCalled();
    vi.advanceTimersByTime(300);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ a: 1, b: 3 });
    vi.useRealTimers();
  });

  it("replace notifies subscribers without reporting a change", () => {
    const onChange = vi.fn();
    const store = new ViewStateStore({}, onChange, 0);
    const listener = vi.fn();
    store.subscribe(listener);
    store.replace({ x: "y" });
    expect(listener).toHaveBeenCalled();
    expect(store.get("x")).toBe("y");
    expect(onChange).not.toHaveBeenCalled();
  });

  it("reports changed queries, except those a restored state brings", () => {
    vi.useFakeTimers();
    const onChange = vi.fn();
    const store = new ViewStateStore({ a: 1 }, onChange, 300);
    store.queriesChanged();
    vi.advanceTimersByTime(300);
    expect(onChange).toHaveBeenCalledWith({ a: 1 });
    store.replace({ a: 2 });
    store.queriesChanged();
    vi.advanceTimersByTime(300);
    expect(onChange).toHaveBeenCalledTimes(1);
    store.set("a", 3);
    store.queriesChanged();
    vi.advanceTimersByTime(300);
    expect(onChange).toHaveBeenCalledTimes(2);
    expect(onChange).toHaveBeenLastCalledWith({ a: 3 });
    vi.useRealTimers();
  });
});
