import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const state = new Map<string, unknown>();
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    (state.get(key) as T | undefined) ?? initial,
    (next: T) => state.set(key, next),
  ],
}));
// The stub saves one layout when clicked, as the real viewer does after a drag.
const saved = { group_by: ["a"], columns: ["b"], expressions: { e: "1" } };
vi.mock("@quarry/perspective", async () => ({
  PerspectiveViewer: ({ onConfig }: { onConfig: (next: object) => void }) => (
    <button data-testid="viewer" onClick={() => onConfig(saved)} />
  ),
  perspectiveToSpec: (await import("@/runtime/perspective/toSpec"))
    .perspectiveToSpec,
}));

import Pivot from "@builtin/pivot/component";

const source = { dataset: "df", format: "arrow", limit: 50000 };
const success: QueryHookResult = {
  status: "success",
  rows: [],
  schema: [
    { name: "a", dtype: "Int64" },
    { name: "b", dtype: "Float64" },
  ],
  rowCount: 3,
  truncated: false,
  arrow: new ArrayBuffer(8),
};

describe("pivot built-in", () => {
  it("loads the dataset as arrow and records the mapped spec as a probe query", () => {
    state.set("perspective", {
      group_by: ["a"],
      columns: ["a", "b"],
      aggregates: { b: "sum" },
    });
    query.mockReturnValue(success);
    render(<Pivot datasets={["df"]} />);
    expect(query).toHaveBeenCalledWith(source);
    expect(query).toHaveBeenCalledWith({
      dataset: "df",
      group_by: ["a"],
      aggs: [{ col: "b", fn: "sum" }],
      limit: 1,
    });
    expect(screen.getByTestId("viewer")).toBeTruthy();
  });

  it("lists what to code will leave out", () => {
    state.set("perspective", { expressions: { e: "1" } });
    query.mockReturnValue(success);
    render(<Pivot datasets={["df"]} />);
    expect(
      screen.getByText(/to code will leave out: expression e/i),
    ).toBeTruthy();
  });

  it("picks default aggregates from the arrow result's schema", () => {
    state.set("perspective", { group_by: ["a"], columns: ["a", "b"] });
    query.mockReturnValue(success);
    render(<Pivot datasets={["df"]} />);
    expect(query).toHaveBeenLastCalledWith({
      dataset: "df",
      group_by: ["a"],
      aggs: [{ col: "b", fn: "sum" }],
      limit: 1,
    });
  });

  it("asks only for the arrow query until its rows arrive", () => {
    state.set("perspective", { group_by: ["a"], columns: ["a", "b"] });
    query.mockClear();
    query.mockReturnValue({ status: "loading" });
    render(<Pivot datasets={["df"]} />);
    expect(query).toHaveBeenCalled();
    for (const [spec] of query.mock.calls) expect(spec).toEqual(source);
  });

  it("says how many rows the viewer holds when it may not hold them all", () => {
    state.delete("perspective");
    query.mockReturnValue({ ...success, rowCount: 50000 });
    const { unmount } = render(<Pivot datasets={["df"]} />);
    expect(screen.getByText("Showing the first 50,000 rows.")).toBeTruthy();
    unmount();
    // The server's row cap can sit below the viewer's limit.
    query.mockReturnValue({ ...success, rowCount: 7, truncated: true });
    render(<Pivot datasets={["df"]} />);
    expect(screen.getByText("Showing the first 7 rows.")).toBeTruthy();
  });

  it("saves the viewer's layout, its mapped spec and what to code will leave out", () => {
    state.delete("perspective");
    state.delete("dropped");
    state.delete("spec");
    query.mockReturnValue(success);
    render(<Pivot datasets={["df"]} />);
    fireEvent.click(screen.getByTestId("viewer"));
    expect(state.get("perspective")).toEqual(saved);
    expect(state.get("dropped")).toEqual(["expression e"]);
    // The probe's spec without its `limit`, so to code renders the whole result.
    expect(state.get("spec")).toEqual({
      dataset: "df",
      group_by: ["a"],
      aggs: [{ col: "b", fn: "sum" }],
    });
  });
});
