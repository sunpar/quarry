import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const setData = vi.hoisted(() => vi.fn());
const createChart = vi.hoisted(() =>
  vi.fn(() => ({
    addSeries: () => ({ setData }),
    applyOptions: vi.fn(),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  })),
);
const query = vi.fn<(spec: unknown) => QueryHookResult>();
const saved = vi.hoisted((): Record<string, unknown> => ({}));
const live = vi.hoisted(() => ({
  current: null as { name: string; dtype: string }[] | null,
}));
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    key in saved ? (saved[key] as T) : initial,
    () => undefined,
  ],
  useDatasetSchema: () =>
    live.current ?? [
      { name: "ts", dtype: "Date" },
      { name: "px", dtype: "Float64" },
    ],
}));
vi.mock("lightweight-charts", () => ({ LineSeries: {}, createChart }));

import TimeSeries from "@builtin/time-series/component";

// Renders with `columns` saved and the live schema replaced, then puts both back.
function renderWith(
  schema: { name: string; dtype: string }[],
  columns?: object,
) {
  if (columns !== undefined) saved.columns = columns;
  live.current = schema;
  try {
    return render(<TimeSeries datasets={["px"]} />);
  } finally {
    delete saved.columns;
    live.current = null;
  }
}

const options = (label: string) =>
  Array.from(
    screen.getByLabelText<HTMLSelectElement>(label).options,
    (o) => o.value,
  );

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

  it("drops a saved column the live schema no longer has", () => {
    query.mockReturnValue({ status: "loading" });
    saved.columns = { time: "gone", value: "px" };
    try {
      render(<TimeSeries datasets={["px"]} />);
    } finally {
      delete saved.columns;
    }
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["ts", "px"] }),
    );
  });

  it("never pairs the time with a value that differs only in case", () => {
    // The kernel refuses two selected names that differ only in case.
    query.mockReturnValue({ status: "loading" });
    renderWith([
      { name: "Date", dtype: "Date" },
      { name: "date", dtype: "Int64" },
      { name: "px", dtype: "Float64" },
    ]);
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["Date", "px"] }),
    );
    expect(options("Value")).toEqual(["px"]);
  });

  it("takes a time column that leaves a value", () => {
    query.mockReturnValue({ status: "loading" });
    for (const time of [null, "Date"]) {
      cleanup();
      renderWith(
        [
          { name: "Date", dtype: "Date" },
          { name: "ts", dtype: "Datetime" },
          { name: "date", dtype: "Int64" },
        ],
        { time, value: null },
      );
      expect(query).toHaveBeenLastCalledWith(
        expect.objectContaining({ select: ["ts", "date"] }),
      );
      expect(options("Time")).toEqual(["ts"]);
    }
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
      arrow: null,
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

  it("keeps its pickers above a query error", () => {
    query.mockReturnValue({ status: "error", message: "unknown column" });
    setData.mockClear();
    render(<TimeSeries datasets={["px"]} />);
    expect(screen.getByLabelText("Time")).toBeTruthy();
    expect(screen.getByLabelText("Value")).toBeTruthy();
    expect(screen.getByText("unknown column")).toBeTruthy();
    expect(setData).not.toHaveBeenCalled();
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("draws the chart once a query error clears", () => {
    query.mockReturnValue({ status: "error", message: "unknown column" });
    createChart.mockClear();
    const { rerender } = render(<TimeSeries datasets={["px"]} />);
    expect(screen.getByText("unknown column")).toBeTruthy();
    query.mockReturnValue({
      status: "success",
      schema: [],
      rowCount: 1,
      truncated: false,
      arrow: null,
      rows: [{ ts: "2024-01-02", px: 1.5 }],
    });
    rerender(<TimeSeries datasets={["px"]} />);
    expect(createChart).toHaveBeenCalledTimes(1);
    expect(setData).toHaveBeenLastCalledWith([
      { time: 1704153600, value: 1.5 },
    ]);
    expect(screen.queryByText("unknown column")).toBeNull();
  });
});
