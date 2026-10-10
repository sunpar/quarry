import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";
import type { Column, Row } from "@/shared/api-types";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const plot = vi.hoisted(() => vi.fn<(props: { data: unknown[] }) => void>());
const saved = vi.hoisted((): Record<string, unknown> => ({}));
const schema = vi.hoisted(() => ({
  current: null as { name: string; dtype: string }[] | null,
}));
// View state starts from `saved` and keeps what the pickers set, as the real hook does.
vi.mock("@quarry/hooks", async () => {
  const { useState } = await import("react");
  return {
    useQuery: (spec: unknown) => query(spec),
    useViewState: <T,>(key: string, initial: T) =>
      useState<T>(key in saved ? (saved[key] as T) : initial),
    useDatasetSchema: () =>
      schema.current ?? [
        { name: "date", dtype: "Date" },
        { name: "ticker", dtype: "String" },
        { name: "ret", dtype: "Float64" },
      ],
  };
});
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

// Renders with `columns` saved or with the live schema replaced, then puts both back.
function renderWith(options: {
  columns?: object;
  live?: { name: string; dtype: string }[];
}) {
  if (options.columns !== undefined) saved.columns = options.columns;
  if (options.live !== undefined) schema.current = options.live;
  try {
    return render(<Heatmap datasets={["rets"]} />);
  } finally {
    delete saved.columns;
    schema.current = null;
  }
}

const pivotOf = (index: string, columns: string, values: string) => ({
  ...spec,
  pivot: { ...spec.pivot, index: [index], columns, values },
  sort: [{ col: index }],
});

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
    renderWith({ columns: { row: "ticker", column: "ticker", value: null } });
    expect(query).toHaveBeenLastCalledWith(pivotOf("ticker", "date", "ret"));
  });

  it("never keys on the value column, so no pick leaves the grid without a value", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({ columns: { row: "ret", column: null, value: null } });
    expect(query).toHaveBeenLastCalledWith(spec);
  });

  it("pivots on a numeric key only once the researcher picks it", () => {
    query.mockReturnValue({ status: "loading" });
    const f64 = (name: string) => ({ name, dtype: "Float64" });
    const placeholder = { dataset: "rets", limit: 1 };
    // Each distinct value of a column key becomes a column, so `[a, b, c]` waits too.
    renderWith({ live: [f64("a"), f64("b"), f64("c")] });
    expect(query).toHaveBeenLastCalledWith(placeholder);
    expect(screen.getByText("Pick a row key.")).toBeTruthy();
    cleanup();
    schema.current = [
      { name: "ticker", dtype: "String" },
      f64("px"),
      f64("vol"),
    ];
    try {
      render(<Heatmap datasets={["rets"]} />);
      expect(query).toHaveBeenLastCalledWith(placeholder);
      expect(screen.getByText("Pick a column key.")).toBeTruthy();
      expect(screen.getByLabelText("Row")).toBeTruthy();
      fireEvent.change(screen.getByLabelText("Column"), {
        target: { value: "vol" },
      });
    } finally {
      schema.current = null;
    }
    expect(query).toHaveBeenLastCalledWith(pivotOf("ticker", "vol", "px"));
  });

  it("drops saved columns the live schema no longer has", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({ columns: { row: "gone", column: "ticker", value: "px" } });
    expect(query).toHaveBeenLastCalledWith(spec);
  });

  it("says when the grid shows only the first rows", () => {
    const rows = Array.from({ length: 500 }, (_, i) => ({ date: `d${i}` }));
    query.mockReturnValue(success(rows));
    render(<Heatmap datasets={["rets"]} />);
    expect(screen.getByText("Showing the first 500 rows.")).toBeTruthy();
  });
});
