import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

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
  useDatasetSchema: () => schema.current,
}));
// The grid itself is AG Grid's to test; jsdom has no layout, so stub it and check the contract.
const gridProps = vi.fn();
const gridMounts = vi.fn();
vi.mock("ag-grid-react", async () => {
  const { useEffect } = await import("react");
  return {
    AgGridReact: (props: object) => {
      gridProps(props);
      useEffect(() => gridMounts(), []);
      return <div data-testid="grid" />;
    },
  };
});
vi.mock("ag-grid-community", () => ({
  AllCommunityModule: {},
  ModuleRegistry: { registerModules: () => undefined },
  themeQuartz: { withParams: () => ({}) },
}));

import DataTable from "@builtin/data-table/component";

describe("data-table built-in", () => {
  it("queries the first dataset with a limit and renders a truncation banner", () => {
    query.mockReturnValue({
      status: "success",
      rows: [{ a: 1 }],
      schema: [{ name: "a", dtype: "Int64" }],
      rowCount: 50000,
      truncated: true,
      arrow: null,
    });
    render(<DataTable datasets={["df"]} />);
    expect(query).toHaveBeenCalledWith(
      expect.objectContaining({ dataset: "df", limit: 1000 }),
    );
    expect(screen.getByText("Showing the first 1 rows.")).toBeTruthy();
    // A column named "a.b" is a literal key in the rows, not a nested path.
    expect(gridProps).toHaveBeenLastCalledWith(
      expect.objectContaining({ suppressFieldDotNotation: true }),
    );
    // The server sorts; the grid keeps that order rather than comparing "10" < "2".
    const [{ columnDefs }] = gridProps.mock.lastCall as [
      { columnDefs: { comparator: (a: unknown, b: unknown) => number }[] },
    ];
    expect(columnDefs[0]?.comparator("10", "2")).toBe(0);
  });

  it("shows the notice when a full page comes back and hides it otherwise", () => {
    const rows = (n: number) => Array.from({ length: n }, (_, i) => ({ a: i }));
    const page = (n: number): QueryHookResult => ({
      status: "success",
      rows: rows(n),
      schema: [{ name: "a", dtype: "Int64" }],
      rowCount: n,
      truncated: false,
      arrow: null,
    });
    query.mockReturnValue(page(1000));
    const { unmount } = render(<DataTable datasets={["df"]} />);
    expect(screen.getByText("Showing the first 1,000 rows.")).toBeTruthy();
    unmount();
    query.mockReturnValue(page(999));
    render(<DataTable datasets={["df"]} />);
    expect(screen.queryByText(/Showing the first/)).toBeNull();
  });

  it("keeps a missing saved sort visible so it can be cleared", () => {
    query.mockReturnValue({ status: "loading" });
    saved.sort = { col: "gone", desc: true };
    schema.current = [{ name: "a", dtype: "Int64" }];
    try {
      render(<DataTable datasets={["df"]} />);
    } finally {
      delete saved.sort;
      schema.current = null;
    }
    expect(query).toHaveBeenLastCalledWith({
      dataset: "df",
      limit: 1000,
      sort: [{ col: "gone", desc: true }],
    });
    expect(
      screen.getByRole("button", { name: "Clear sort (gone)" }),
    ).toBeTruthy();
  });

  it("keeps the grid and its rows while a changed query loads", () => {
    const rows = [{ a: 1 }];
    query.mockReturnValue({
      status: "success",
      rows,
      schema: [{ name: "a", dtype: "Int64" }],
      rowCount: 1,
      truncated: false,
      arrow: null,
    });
    gridMounts.mockClear();
    const { rerender } = render(<DataTable datasets={["df"]} />);
    // A new sort or filter is a new spec, which starts out loading.
    query.mockReturnValue({ status: "loading" });
    rerender(<DataTable datasets={["df"]} />);
    expect(screen.getByRole("status").textContent).toBe("Loading");
    expect(gridProps).toHaveBeenLastCalledWith(
      expect.objectContaining({ rowData: rows }),
    );
    // The same grid stays mounted rather than being rebuilt.
    expect(gridMounts).toHaveBeenCalledTimes(1);
  });

  it("shows query errors in place", () => {
    query.mockReturnValue({ status: "error", message: "unknown column" });
    render(<DataTable datasets={["df"]} />);
    expect(screen.getByText("unknown column")).toBeTruthy();
  });
});
