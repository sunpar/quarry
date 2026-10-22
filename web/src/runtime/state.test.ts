import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ViewStateStore } from "./state";

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("ViewStateStore", () => {
  it("debounces onChange and reports the whole state", () => {
    const onChange = vi.fn();
    const store = new ViewStateStore({ a: 1 }, onChange, 300);
    store.set("b", 2);
    store.set("b", 3);
    expect(onChange).not.toHaveBeenCalled();
    vi.advanceTimersByTime(300);
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ a: 1, b: 3 });
  });

  it("replace notifies subscribers without reporting a change", () => {
    const onChange = vi.fn();
    const store = new ViewStateStore({}, onChange, 0);
    const listener = vi.fn();
    store.subscribe(listener);
    store.replace({ x: "y" });
    expect(listener).toHaveBeenCalled();
    expect(store.get("x")).toBe("y");
    vi.runAllTimers();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("merge sets the given keys, keeps the rest and reports nothing", () => {
    const onChange = vi.fn();
    const store = new ViewStateStore(
      { "shared:k": 1, limit: 5 },
      onChange,
      300,
    );
    store.set("limit", 9); // not yet reported when another card's key arrives
    store.merge({ "shared:k": 2 });
    expect(store.current()).toEqual({ "shared:k": 2, limit: 9 });
    store.queriesChanged();
    vi.advanceTimersByTime(300);
    // The pending edit still reports, now with the merged key.
    expect(onChange).toHaveBeenCalledTimes(1);
    expect(onChange).toHaveBeenCalledWith({ "shared:k": 2, limit: 9 });
  });

  it("a restore cancels a report still waiting", () => {
    const onChange = vi.fn();
    const store = new ViewStateStore({ a: 1 }, onChange, 300);
    store.queriesChanged(); // as a view's queries do when it mounts
    store.replace({ a: 2 });
    vi.advanceTimersByTime(300);
    store.set("a", 3);
    store.replace({ a: 4 });
    vi.advanceTimersByTime(300);
    expect(onChange).not.toHaveBeenCalled();
  });

  it("reports changed queries, except those a restored state brings", () => {
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
  });
});
