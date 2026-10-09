import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const setData = vi.hoisted(() => vi.fn());
const query = vi.fn<(spec: unknown) => QueryHookResult>();
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(_key: string, initial: T) => [initial, () => undefined],
  useDatasetSchema: () => [
    { name: "ts", dtype: "Date" },
    { name: "px", dtype: "Float64" },
  ],
}));
vi.mock("lightweight-charts", () => ({
  LineSeries: {},
  createChart: () => ({
    addSeries: () => ({ setData }),
    applyOptions: vi.fn(),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  }),
}));

import TimeSeries from "@builtin/time-series/component";

describe("time-series built-in", () => {
  it("picks the first datetime and numeric columns and sorts by time", () => {
    query.mockReturnValue({ status: "loading" });
    render(<TimeSeries datasets={["px"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "px",
      select: ["ts", "px"],
      sort: [{ col: "ts" }],
      limit: 50000,
    });
    expect(screen.getByText("Loading")).toBeTruthy();
  });

  it("drops unplottable rows, keeps the last of a second, and reads naive times as UTC", () => {
    query.mockReturnValue({
      status: "success",
      schema: [
        { name: "ts", dtype: "Datetime" },
        { name: "px", dtype: "Float64" },
      ],
      rowCount: 7,
      truncated: true,
      rows: [
        { ts: null, px: 1 },
        { ts: "2024-01-02T10:00:00", px: null },
        { ts: "2024-01-02T10:00:01.100", px: 2 },
        { ts: "2024-01-02T10:00:01.900", px: 3 },
        { ts: "2024-01-02T10:00:05+00:00", px: 4 },
        { ts: "2024-01-02T10:00:06+00:00", px: "4.25" },
        { ts: "2024-01-02T10:00:07+00:00", px: "" },
      ],
    });
    render(<TimeSeries datasets={["px"]} />);
    const base = Date.UTC(2024, 0, 2, 10) / 1000;
    expect(setData).toHaveBeenLastCalledWith([
      { time: base + 1, value: 3 },
      { time: base + 5, value: 4 },
      { time: base + 6, value: 4.25 },
    ]);
    // The server's row cap can sit below the chart's limit.
    expect(screen.getByText("Showing the first 7 rows.")).toBeTruthy();
  });
});
