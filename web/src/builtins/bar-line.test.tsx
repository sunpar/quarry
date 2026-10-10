import type { ReactNode } from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";
import type { Row } from "@/shared/api-types";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
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
      { name: "sector", dtype: "String" },
      { name: "ret", dtype: "Float64" },
    ],
}));
interface ChartProps {
  data: Row[];
  children: ReactNode;
}
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div data-testid="chart">{children}</div>
  ),
  BarChart: ({ data, children }: ChartProps) => (
    <div data-testid="bar" data-rows={JSON.stringify(data)}>
      {children}
    </div>
  ),
  LineChart: ({ data, children }: ChartProps) => (
    <div data-testid="line" data-rows={JSON.stringify(data)}>
      {children}
    </div>
  ),
  Bar: () => null,
  Line: () => null,
  XAxis: () => null,
  YAxis: () => null,
  Tooltip: () => null,
}));

import BarLine from "@builtin/bar-line/component";

const success = (rows: Row[]): QueryHookResult => ({
  status: "success",
  rows,
  schema: [],
  rowCount: rows.length,
  truncated: false,
  arrow: null,
});

describe("bar-line built-in", () => {
  it("groups by the first string column and sums the first numeric one", () => {
    query.mockReturnValue(success([{ sector: "tech", ret_sum: "0.5" }]));
    render(<BarLine datasets={["trades"]} />);
    expect(query).toHaveBeenCalledWith({
      dataset: "trades",
      group_by: ["sector"],
      aggs: [{ col: "ret", fn: "sum" }],
      sort: [{ col: "sector" }],
      limit: 500,
    });
    expect(screen.getByTestId("chart")).toBeTruthy();
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("reads decimal strings as numbers and keeps a null aggregate as a gap", () => {
    query.mockReturnValue(
      success([
        { sector: "energy", ret_sum: null },
        { sector: "tech", ret_sum: "0.5" },
        { sector: "utilities", ret_sum: 2 },
      ]),
    );
    saved.kind = "line";
    try {
      render(<BarLine datasets={["trades"]} />);
    } finally {
      delete saved.kind;
    }
    expect(JSON.parse(screen.getByTestId("line").dataset.rows ?? "")).toEqual([
      { sector: "energy", ret_sum: null },
      { sector: "tech", ret_sum: 0.5 },
      { sector: "utilities", ret_sum: 2 },
    ]);
  });

  it("drops a saved column the live schema no longer has", () => {
    query.mockReturnValue({ status: "loading" });
    saved.columns = { category: "gone", value: "px" };
    try {
      render(<BarLine datasets={["trades"]} />);
    } finally {
      delete saved.columns;
    }
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({
        group_by: ["sector"],
        aggs: [{ col: "ret", fn: "sum" }],
      }),
    );
  });

  it("groups by a numeric column when the dataset has no other kind", () => {
    query.mockReturnValue({ status: "loading" });
    schema.current = [
      { name: "a", dtype: "Float64" },
      { name: "b", dtype: "Int64" },
    ];
    try {
      render(<BarLine datasets={["trades"]} />);
    } finally {
      schema.current = null;
    }
    expect(query).toHaveBeenLastCalledWith({
      dataset: "trades",
      group_by: ["b"],
      aggs: [{ col: "a", fn: "sum" }],
      sort: [{ col: "b" }],
      limit: 500,
    });
    // With no other column left, the value groups itself, which the kernel accepts.
    schema.current = [
      { name: "ret", dtype: "Float64" },
      { name: "ret_sum", dtype: "Float64" },
    ];
    try {
      render(<BarLine datasets={["trades"]} />);
    } finally {
      schema.current = null;
    }
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({
        group_by: ["ret"],
        aggs: [{ col: "ret", fn: "sum" }],
      }),
    );
  });

  it("never groups by a column named like the aggregate, in any case", () => {
    query.mockReturnValue({ status: "loading" });
    saved.columns = { category: "RET_SUM", value: null };
    schema.current = [
      { name: "RET_SUM", dtype: "String" },
      { name: "sector", dtype: "String" },
      { name: "ret", dtype: "Float64" },
    ];
    try {
      render(<BarLine datasets={["trades"]} />);
    } finally {
      delete saved.columns;
      schema.current = null;
    }
    expect(query).toHaveBeenLastCalledWith(
      expect.objectContaining({
        group_by: ["sector"],
        sort: [{ col: "sector" }],
      }),
    );
  });

  it("says when the chart shows only the first groups", () => {
    const rows = Array.from({ length: 500 }, (_, i) => ({
      sector: `s${i}`,
      ret_sum: i,
    }));
    query.mockReturnValue(success(rows));
    render(<BarLine datasets={["trades"]} />);
    expect(screen.getByText("Showing the first 500 rows.")).toBeTruthy();
  });
});
