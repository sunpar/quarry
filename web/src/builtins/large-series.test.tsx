import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";
import type { Row } from "@/shared/api-types";

interface Option {
  useUTC: boolean;
  series: { large: boolean; data: [number, number][] }[];
}

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const chart = vi.hoisted(() => vi.fn<(option: Option) => void>());
const saved = vi.hoisted((): Record<string, unknown> => ({}));
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    key in saved ? (saved[key] as T) : initial,
    () => undefined,
  ],
  useDatasetSchema: () => [
    { name: "ts", dtype: "Datetime(time_unit='us', time_zone=None)" },
    { name: "px", dtype: "Float64" },
  ],
}));
vi.mock("echarts-for-react", () => ({
  default: (props: { option: Option }) => {
    chart(props.option);
    return (
      <div
        data-testid="echarts"
        data-large={String(props.option.series[0]?.large)}
      />
    );
  },
}));

import LargeSeries from "@builtin/large-series/component";

const success = (rows: Row[], truncated = false): QueryHookResult => ({
  status: "success",
  rows,
  schema: [],
  rowCount: rows.length,
  truncated,
  arrow: null,
});

describe("large-series built-in", () => {
  it("asks for up to 500,000 rows sorted by time and draws a large series", () => {
    query.mockReturnValue(success([{ ts: "2024-01-02T10:00:00", px: 1 }]));
    render(<LargeSeries datasets={["ticks"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "ticks",
      select: ["ts", "px"],
      sort: [{ col: "ts" }],
      limit: 500000,
    });
    expect(screen.getByTestId("echarts").dataset.large).toBe("true");
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
      [base + 2000, 2.5],
    ]);
    // The server's row cap sits below the chart's limit.
    expect(screen.getByText("Showing the first 5 rows.")).toBeTruthy();
  });

  it("drops a saved column the live schema no longer has", () => {
    query.mockReturnValue({ status: "loading" });
    saved.columns = { time: "gone", value: "px" };
    try {
      render(<LargeSeries datasets={["ticks"]} />);
    } finally {
      delete saved.columns;
    }
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({ select: ["ts", "px"] }),
    );
  });
});
