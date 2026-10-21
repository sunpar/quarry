import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";
import type { Row } from "@/shared/api-types";

interface Option {
  useUTC: boolean;
  series: { data: [number, number | null][]; sampling?: string }[];
}

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const chart = vi.hoisted(() => vi.fn<(option: Option) => void>());
const saved = vi.hoisted((): Record<string, unknown> => ({}));
const schema = vi.hoisted(() => ({
  current: null as { name: string; dtype: string }[] | null,
}));
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    key in saved ? (saved[key] as T) : initial,
    () => undefined,
  ],
  useDatasetSchema: () =>
    schema.current ?? [
      { name: "ts", dtype: "Datetime(time_unit='us', time_zone=None)" },
      { name: "px", dtype: "Float64" },
    ],
}));
vi.mock("echarts-for-react", () => ({
  default: (props: { option: Option }) => {
    chart(props.option);
    return <div data-testid="echarts" />;
  },
}));

import LargeSeries from "@builtin/large-series/component";

// Renders with `columns` saved or with the live schema replaced, then puts both back.
function renderWith(options: {
  columns?: object;
  live?: { name: string; dtype: string }[];
}) {
  if (options.columns !== undefined) saved.columns = options.columns;
  if (options.live !== undefined) schema.current = options.live;
  try {
    return render(<LargeSeries datasets={["ticks"]} />);
  } finally {
    delete saved.columns;
    schema.current = null;
  }
}

const options = (label: string) =>
  Array.from(
    screen.getByLabelText<HTMLSelectElement>(label).options,
    (o) => o.value,
  );

const success = (
  rows: Row[],
  truncated = false,
): Extract<QueryHookResult, { status: "success" }> => ({
  status: "success",
  rows,
  schema: [],
  rowCount: rows.length,
  truncated,
  arrow: null,
});

describe("large-series built-in", () => {
  it("requests whole-domain reduction without browser sampling", () => {
    query.mockReturnValue(success([{ ts: "2024-01-02T10:00:00", px: 1 }]));
    render(<LargeSeries datasets={["ticks"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "ticks",
      line_reduce: { time: "ts", value: "px", max_rows: 50000 },
    });
    expect(chart.mock.lastCall?.[0].series[0]).toMatchObject({
      connectNulls: false,
      showSymbol: false,
    });
    expect(chart.mock.lastCall?.[0].series[0]?.sampling).toBeUndefined();
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("plots epoch milliseconds in UTC, reads naive times as UTC, and drops unplottable rows", () => {
    query.mockReturnValue(
      success(
        [
          { ts: "2024-01-02T10:00:00", px: 1 },
          { ts: null, px: 2 },
          { ts: "2024-01-02T10:00:01", px: null },
          { ts: "2024-01-02T10:00:02+00:00", px: "2.5" },
          { ts: "2024-01-02T10:00:03", px: "not a number" },
        ],
        true,
      ),
    );
    render(<LargeSeries datasets={["ticks"]} />);
    const base = Date.UTC(2024, 0, 2, 10);
    const option = chart.mock.lastCall?.[0];
    expect(option?.useUTC).toBe(true);
    expect(option?.series[0]?.data).toEqual([
      [base, 1],
      [base + 1000, null],
      [base + 2000, 2.5],
      [base + 3000, null],
    ]);
    // The server's row cap sits below the chart's limit.
    expect(screen.getByText("Showing the first 5 rows.")).toBeTruthy();
  });

  it("drops a saved column the live schema no longer has", () => {
    query.mockReturnValue({ status: "loading" });
    renderWith({ columns: { time: "gone", value: "px" } });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({
        line_reduce: { time: "ts", value: "px", max_rows: 50000 },
      }),
    );
  });

  it("never pairs the time with a value that differs only in case", () => {
    // The kernel refuses two names that differ only in case.
    query.mockReturnValue({ status: "loading" });
    renderWith({
      live: [
        { name: "Date", dtype: "Date" },
        { name: "date", dtype: "Int64" },
        { name: "px", dtype: "Float64" },
      ],
    });
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({
        line_reduce: { time: "Date", value: "px", max_rows: 50000 },
      }),
    );
    expect(options("Value")).toEqual(["px"]);
  });

  it("takes a time column that leaves a value", () => {
    query.mockReturnValue({ status: "loading" });
    for (const time of [null, "Date"]) {
      cleanup();
      renderWith({
        columns: { time, value: null },
        live: [
          { name: "Date", dtype: "Date" },
          { name: "ts", dtype: "Datetime" },
          { name: "date", dtype: "Int64" },
        ],
      });
      expect(query).toHaveBeenLastCalledWith(
        expect.objectContaining({
          line_reduce: { time: "ts", value: "date", max_rows: 50000 },
        }),
      );
      expect(options("Time")).toEqual(["ts"]);
    }
  });

  it("distinguishes whole-domain reduction from prefix truncation", () => {
    query.mockReturnValue({
      ...success([{ ts: "2026-01-01", px: 1 }]),
      reduced: true,
      sourceRowCount: 60001,
    });
    render(<LargeSeries datasets={["ticks"]} />);
    expect(
      screen.getByText(
        "Reduced 60,001 rows across the whole time range to 1 representative row.",
      ),
    ).toBeTruthy();
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("keeps column selectors available after a query error", () => {
    query.mockReturnValue({
      status: "error",
      message: "row budget cannot preserve gaps",
    });
    render(<LargeSeries datasets={["ticks"]} />);
    expect(screen.getByLabelText("Time")).toBeTruthy();
    expect(screen.getByLabelText("Value")).toBeTruthy();
    expect(screen.getByText("row budget cannot preserve gaps")).toBeTruthy();
  });
});
