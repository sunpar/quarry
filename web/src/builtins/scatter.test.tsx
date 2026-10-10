import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";
import type { Row } from "@/shared/api-types";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const saved = vi.hoisted((): Record<string, unknown> => ({}));
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    key in saved ? (saved[key] as T) : initial,
    () => undefined,
  ],
  useDatasetSchema: () => [
    { name: "x", dtype: "Float64" },
    { name: "y", dtype: "Float64" },
    { name: "sym", dtype: "String" },
  ],
}));
vi.mock("react-plotly.js", () => ({
  default: (props: { data: unknown[] }) => (
    <div data-testid="plot" data-traces={JSON.stringify(props.data)} />
  ),
}));

import Scatter from "@builtin/scatter/component";

const success = (rows: Row[], truncated = false): QueryHookResult => ({
  status: "success",
  rows,
  schema: [],
  rowCount: rows.length,
  truncated,
  arrow: null,
});

// Renders with `columns` saved, then takes it back out.
function renderWith(columns: object) {
  saved.columns = columns;
  try {
    return render(<Scatter datasets={["pts"]} />);
  } finally {
    delete saved.columns;
  }
}

const traces = () =>
  JSON.parse(screen.getByTestId("plot").dataset.traces ?? "") as {
    name: string;
    x: number[];
    y: number[];
  }[];

describe("scatter built-in", () => {
  it("plots the first two numeric columns as one trace", () => {
    query.mockReturnValue(success([{ x: 1, y: 2 }]));
    render(<Scatter datasets={["pts"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "pts",
      select: ["x", "y"],
      limit: 20000,
    });
    expect(traces()).toHaveLength(1);
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("drops points whose x or y is not a finite number", () => {
    query.mockReturnValue(
      success(
        [
          { x: 1, y: 2 },
          { x: null, y: 3 },
          { x: "4", y: "not a number" },
          { x: "1.5", y: "2.5" },
          { x: 5, y: null },
        ],
        true,
      ),
    );
    render(<Scatter datasets={["pts"]} />);
    expect(traces()[0]).toMatchObject({ x: [1, 1.5], y: [2, 2.5] });
    expect(screen.getByText("Showing the first 5 rows.")).toBeTruthy();
  });

  it("splits the points into one trace per color value", () => {
    query.mockReturnValue(
      success([
        { x: 1, y: 2, sym: "a" },
        { x: 3, y: 4, sym: "b" },
        { x: 5, y: 6, sym: "a" },
      ]),
    );
    renderWith({ x: null, y: null, color: "sym" });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["x", "y", "sym"] }),
    );
    expect(traces().map((t) => [t.name, t.x])).toEqual([
      ["a", [1, 5]],
      ["b", [3]],
    ]);
  });

  it("never selects one column for two roles", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({ x: "x", y: "x", color: "y" });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["x", "y"] }),
    );
  });

  it("drops saved columns the live schema no longer has", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({ x: "gone", y: "y", color: "gone" });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["x", "y"] }),
    );
  });
});
