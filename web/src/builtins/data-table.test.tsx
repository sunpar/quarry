import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { QueryHookResult } from "@/runtime/hooks";

const query = vi.fn<(spec: unknown) => QueryHookResult>();
vi.mock("@quarry/hooks", () => ({
  useQuery: (spec: unknown) => query(spec),
  useViewState: <T,>(_key: string, initial: T) => [initial, () => undefined],
  useDatasetSchema: () => null,
}));
// The grid itself is AG Grid's to test; jsdom has no layout, so stub it and check the contract.
vi.mock("ag-grid-react", () => ({
  AgGridReact: () => <div data-testid="grid" />,
}));
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
    });
    render(<DataTable datasets={["df"]} />);
    expect(query).toHaveBeenCalledWith(
      expect.objectContaining({ dataset: "df", limit: 1000 }),
    );
    expect(screen.getByText(/showing 1 of 50,000 rows/i)).toBeTruthy();
  });

  it("shows query errors in place", () => {
    query.mockReturnValue({ status: "error", message: "unknown column" });
    render(<DataTable datasets={["df"]} />);
    expect(screen.getByText("unknown column")).toBeTruthy();
  });
});
