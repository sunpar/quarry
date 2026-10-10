import { render, screen } from "@testing-library/react";
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
  useDatasetSchema: () => null,
}));
vi.mock("@quarry/perspective", async () => ({
  PerspectiveViewer: () => <div data-testid="viewer" />,
  perspectiveToSpec: (await import("@/runtime/perspective/toSpec"))
    .perspectiveToSpec,
}));

import Pivot from "@builtin/pivot/component";

const success: QueryHookResult = {
  status: "success",
  rows: [],
  schema: [{ name: "a", dtype: "Int64" }],
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
    expect(query).toHaveBeenCalledWith({
      dataset: "df",
      format: "arrow",
      limit: 50000,
    });
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
});
