import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";
import type { Row } from "@/shared/api-types";
import type { Json } from "@/shared/json";

const setData = vi.hoisted(() => vi.fn());
const createChart = vi.hoisted(() =>
  vi.fn(() => ({
    addSeries: () => ({ setData }),
    timeScale: () => ({ fitContent: vi.fn() }),
    remove: vi.fn(),
  })),
);
const query = vi.fn<(spec: unknown) => QueryHookResult>();
const saved = vi.hoisted((): Record<string, unknown> => ({}));
const bars = [
  { name: "ts", dtype: "Date" },
  { name: "open", dtype: "Float64" },
  { name: "high", dtype: "Float64" },
  { name: "low", dtype: "Float64" },
  { name: "close", dtype: "Float64" },
  { name: "volume", dtype: "Int64" },
];
const schema = vi.hoisted(() => ({
  current: null as { name: string; dtype: string }[] | null,
}));
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    key in saved ? (saved[key] as T) : initial,
    () => undefined,
  ],
  useDatasetSchema: () => schema.current ?? bars,
}));
vi.mock("lightweight-charts", () => ({ CandlestickSeries: {}, createChart }));

import Ohlc from "@builtin/ohlc/component";

const success = (rows: Row[], truncated = false): QueryHookResult => ({
  status: "success",
  rows,
  schema: [],
  rowCount: rows.length,
  truncated,
  arrow: null,
});

// Renders with `columns` saved or with the live schema replaced, then puts both back.
function renderWith(options: {
  columns?: object;
  live?: { name: string; dtype: string }[];
}) {
  if (options.columns !== undefined) saved.columns = options.columns;
  if (options.live !== undefined) schema.current = options.live;
  try {
    return render(<Ohlc datasets={["bars"]} />);
  } finally {
    delete saved.columns;
    schema.current = null;
  }
}

const numeric = (...names: string[]) =>
  names.map((name) => ({ name, dtype: "Float64" }));

describe("ohlc built-in", () => {
  it("guesses the price columns by name, sorts by time, and feeds candles", () => {
    query.mockReturnValue(
      success([{ ts: "2024-01-02", open: 1, high: 2, low: 0.5, close: 1.5 }]),
    );
    render(<Ohlc datasets={["bars"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "bars",
      select: ["ts", "open", "high", "low", "close"],
      sort: [{ col: "ts" }],
      limit: 50000,
    });
    expect(setData).toHaveBeenLastCalledWith([
      { time: 1704153600, open: 1, high: 2, low: 0.5, close: 1.5 },
    ]);
    expect(screen.getByLabelText("Close")).toBeTruthy();
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("drops unplottable candles, keeps the last of a second, and reads naive times as UTC", () => {
    const bar = (ts: Json, close: Json) => ({
      ts,
      open: 1,
      high: 2,
      low: 0.5,
      close,
    });
    query.mockReturnValue(
      success(
        [
          bar(null, 1),
          bar("2024-01-02T09:30:00", 1.25),
          bar("2024-01-02T09:30:01.100", 1),
          bar("2024-01-02T09:30:01.900", 1.75),
          bar("2024-01-02T09:30:02", "not a number"),
          bar("2024-01-02T09:30:03+00:00", "1.5"),
          bar("2024-01-02T09:30:04", null),
        ],
        true,
      ),
    );
    renderWith({ live: [{ name: "ts", dtype: "Datetime" }, ...bars.slice(1)] });
    const base = Date.UTC(2024, 0, 2, 9, 30) / 1000;
    const candle = (time: number, close: number) => ({
      time,
      open: 1,
      high: 2,
      low: 0.5,
      close,
    });
    expect(setData).toHaveBeenLastCalledWith([
      candle(base, 1.25),
      candle(base + 1, 1.75),
      candle(base + 3, 1.5),
    ]);
    // The server's row cap can sit below the chart's limit.
    expect(screen.getByText("Showing the first 7 rows.")).toBeTruthy();
  });

  it("keeps one chart while the rows and columns stay the same", () => {
    const result = success([
      { ts: "2024-01-02", open: 1, high: 2, low: 0.5, close: 1.5 },
    ]);
    query.mockReturnValue(result);
    createChart.mockClear();
    const { rerender } = render(<Ohlc datasets={["bars"]} />);
    rerender(<Ohlc datasets={["bars"]} />);
    expect(createChart).toHaveBeenCalledTimes(1);
  });

  it("never gives one guessed column two roles", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({
      live: [
        { name: "ts", dtype: "Date" },
        ...numeric("open", "high", "x", "y"),
      ],
    });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["ts", "open", "high", "x", "y"] }),
    );
    // A fallback guess must not take a column a later role matches by name.
    renderWith({
      live: [
        { name: "ts", dtype: "Date" },
        ...numeric("high", "low", "close", "y"),
      ],
    });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["ts", "y", "high", "low", "close"] }),
    );
    // Nor a column saved for another role.
    renderWith({
      columns: { time: null, open: null, high: null, low: null, close: "x" },
      live: [
        { name: "ts", dtype: "Date" },
        ...numeric("open", "high", "x", "y"),
      ],
    });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["ts", "open", "high", "y", "x"] }),
    );
  });

  it("drops a saved column the live schema no longer has", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({
      columns: {
        time: "gone",
        open: "open",
        high: null,
        low: null,
        close: "px",
      },
    });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({
        select: ["ts", "open", "high", "low", "close"],
      }),
    );
  });

  it("selects a column once when the researcher picks it for two roles", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({
      columns: {
        time: "ts",
        open: "close",
        high: "high",
        low: "low",
        close: "close",
      },
    });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["ts", "close", "high", "low"] }),
    );
  });

  it("asks for the columns it needs when the dataset lacks them", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({ live: [{ name: "ts", dtype: "Date" }, ...numeric("px")] });
    expect(
      screen.getByText(
        "This dataset needs a date column and open, high, low and close columns.",
      ),
    ).toBeTruthy();
  });

  it("shows query errors in place", () => {
    query.mockReturnValue({ status: "error", message: "unknown column" });
    render(<Ohlc datasets={["bars"]} />);
    expect(screen.getByText("unknown column")).toBeTruthy();
  });
});
