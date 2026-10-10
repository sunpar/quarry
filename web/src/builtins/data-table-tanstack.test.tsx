import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
const setSort = vi.fn();
const saved = vi.hoisted((): Record<string, unknown> => ({}));
const schema = vi.hoisted(() => ({
  current: null as { name: string; dtype: string }[] | null,
}));
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(key: string, initial: T) => [
    key in saved ? (saved[key] as T) : initial,
    key === "sort" ? setSort : () => undefined,
  ],
  useDatasetSchema: () => schema.current,
}));

import DataTableTanstack from "@builtin/data-table-tanstack/component";

const prices: QueryHookResult = {
  status: "success",
  rows: [
    { sym: "A", px: 1.5 },
    { sym: "B", px: 2 },
  ],
  schema: [
    { name: "sym", dtype: "String" },
    { name: "px", dtype: "Float64" },
  ],
  rowCount: 2,
  truncated: false,
  arrow: null,
};

describe("data-table-tanstack built-in", () => {
  it("renders header cells and rows, and pushes a header click into the sort state", () => {
    query.mockReturnValue(prices);
    render(<DataTableTanstack datasets={["df"]} />);
    expect(query).toHaveBeenCalledWith({ dataset: "df", limit: 500 });
    expect(screen.getByRole("columnheader", { name: /px/ })).toBeTruthy();
    // Numeric columns are right-aligned through the column meta.
    expect(screen.getByText("1.5").className).toContain("text-right");
    expect(screen.getByText("A").className).not.toContain("text-right");
    expect(screen.queryByText(/Showing the first/)).toBeNull();
    fireEvent.click(screen.getByRole("columnheader", { name: /px/ }));
    expect(setSort).toHaveBeenLastCalledWith({ col: "px", desc: false });
  });

  it("sends a saved sort to the query and cycles it from ascending to descending to none", () => {
    query.mockReturnValue(prices);
    try {
      saved.sort = { col: "px", desc: false };
      const { unmount } = render(<DataTableTanstack datasets={["df"]} />);
      expect(query).toHaveBeenLastCalledWith({
        dataset: "df",
        limit: 500,
        sort: [{ col: "px", desc: false }],
      });
      fireEvent.click(screen.getByRole("columnheader", { name: /px/ }));
      expect(setSort).toHaveBeenLastCalledWith({ col: "px", desc: true });
      unmount();
      saved.sort = { col: "px", desc: true };
      render(<DataTableTanstack datasets={["df"]} />);
      fireEvent.click(screen.getByRole("columnheader", { name: /px/ }));
      expect(setSort).toHaveBeenLastCalledWith(null);
    } finally {
      delete saved.sort;
    }
  });

  it("drops a saved sort on a column the live schema lacks", () => {
    query.mockReturnValue({ status: "loading" });
    saved.sort = { col: "gone", desc: true };
    schema.current = [{ name: "a", dtype: "Int64" }];
    try {
      render(<DataTableTanstack datasets={["df"]} />);
    } finally {
      delete saved.sort;
      schema.current = null;
    }
    expect(query).toHaveBeenLastCalledWith({ dataset: "df", limit: 500 });
  });

  it("shows the notice when a full page comes back", () => {
    // row_count is the number of rows returned, so a full page is the only sign of more.
    const rows = Array.from({ length: 500 }, (_, i) => ({ a: i }));
    query.mockReturnValue({
      status: "success",
      rows,
      schema: [{ name: "a", dtype: "Int64" }],
      rowCount: 500,
      truncated: false,
      arrow: null,
    });
    render(<DataTableTanstack datasets={["df"]} />);
    expect(screen.getByText("Showing the first 500 rows.")).toBeTruthy();
  });

  it("shows query errors in place", () => {
    query.mockReturnValue({ status: "error", message: "unknown column" });
    render(<DataTableTanstack datasets={["df"]} />);
    expect(screen.getByText("unknown column")).toBeTruthy();
  });
});
