import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

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
    addSeries: () => ({ setData: vi.fn() }),
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
});
