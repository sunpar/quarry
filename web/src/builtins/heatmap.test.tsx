import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";
import type { Column, Row } from "@/shared/api-types";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const plot = vi.hoisted(() => vi.fn<(props: { data: unknown[] }) => void>());
const saved = vi.hoisted((): Record<string, unknown> => ({}));
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    key in saved ? (saved[key] as T) : initial,
    () => undefined,
  ],
  useDatasetSchema: () => [
    { name: "date", dtype: "Date" },
    { name: "ticker", dtype: "String" },
    { name: "ret", dtype: "Float64" },
  ],
}));
vi.mock("react-plotly.js", () => ({
  default: (props: { data: unknown[] }) => {
    plot(props);
    return (
      <div data-testid="plot" data-traces={JSON.stringify(props.data.length)} />
    );
  },
}));

import Heatmap from "@builtin/heatmap/component";

const success = (rows: Row[], schema: Column[] = []): QueryHookResult => ({
  status: "success",
  rows,
  schema,
  rowCount: rows.length,
  truncated: false,
  arrow: null,
});

const spec = {
  dataset: "rets",
  pivot: { index: ["date"], columns: "ticker", values: "ret", agg: "mean" },
  sort: [{ col: "date" }],
  limit: 500,
};

// Renders with `columns` saved, then takes it back out.
function renderWith(columns: object) {
  saved.columns = columns;
  try {
    return render(<Heatmap datasets={["rets"]} />);
  } finally {
    delete saved.columns;
  }
}

describe("heatmap built-in", () => {
  it("pivots the mean value by the first two key columns", () => {
    query.mockReturnValue(success([]));
    render(<Heatmap datasets={["rets"]} />);
    expect(query).toHaveBeenCalledWith(spec);
    expect(screen.getByTestId("plot").dataset.traces).toBe("1");
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("reads cells as numbers and leaves null and non-numeric cells blank", () => {
    query.mockReturnValue(
      success(
        [
          { date: "2024-01-02", AAPL: 0.1, MSFT: null },
          { date: "2024-01-03", AAPL: "0.2", MSFT: "n/a" },
        ],
        [
          { name: "date", dtype: "Date" },
          { name: "AAPL", dtype: "Float64" },
          { name: "MSFT", dtype: "Float64" },
        ],
      ),
    );
    render(<Heatmap datasets={["rets"]} />);
    expect(plot.mock.lastCall?.[0].data[0]).toMatchObject({
      type: "heatmap",
      x: ["AAPL", "MSFT"],
      y: ["2024-01-02", "2024-01-03"],
      z: [
        [0.1, NaN],
        [0.2, NaN],
      ],
    });
  });

  it("never pivots a column against itself", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({ row: "ticker", column: "ticker", value: null });
    expect(query).toHaveBeenLastCalledWith({
      ...spec,
      pivot: { ...spec.pivot, index: ["ticker"], columns: "date" },
      sort: [{ col: "ticker" }],
    });
  });

  it("drops saved columns the live schema no longer has", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({ row: "gone", column: "ticker", value: "px" });
    expect(query).toHaveBeenLastCalledWith(spec);
  });

  it("says when the grid shows only the first rows", () => {
    const rows = Array.from({ length: 500 }, (_, i) => ({ date: `d${i}` }));
    query.mockReturnValue(success(rows));
    render(<Heatmap datasets={["rets"]} />);
    expect(screen.getByText("Showing the first 500 rows.")).toBeTruthy();
  });
});
