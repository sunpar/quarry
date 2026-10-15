import {
  fireEvent,
  render,
  screen,
  waitFor,
  act,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Column, QuerySpec } from "@/shared/api-types";
import type { RuntimeToHost } from "@/shared/bridge-types";
import type { JsonObject } from "@/shared/json";
import { RuntimeProvider } from "@/runtime/context";
import { RuntimeBridge } from "@/runtime/bridge";
import { RequestCache } from "@/runtime/cache";
import { ViewStateStore } from "@/runtime/state";

vi.mock("ag-grid-react", () => ({ AgGridReact: () => <div>Grid rows</div> }));
vi.mock("ag-grid-community", () => ({
  AllCommunityModule: {},
  ModuleRegistry: { registerModules: () => undefined },
  themeQuartz: { withParams: () => ({}) },
}));
import DataTable from "@builtin/data-table/component";
import DataTableTanstack from "@builtin/data-table-tanstack/component";

const columns: Column[] = [
  { name: "symbol", dtype: "String" },
  { name: "price", dtype: "Float64" },
  { name: "volume", dtype: "Int64" },
  { name: "day", dtype: "Date" },
  { name: "exact", dtype: "Decimal(precision=38, scale=2)" },
];

function mount(Component: typeof DataTable, initial: JsonObject = {}) {
  const sent: RuntimeToHost[] = [];
  let schema = columns;
  const bridge = new RuntimeBridge(
    "v",
    (message) => {
      sent.push(message);
      if (message.type === "schema" || message.type === "query")
        queueMicrotask(() => {
          if (message.type === "schema")
            bridge.handle({
              type: "schemaResult",
              viewId: "v",
              id: message.id,
              ok: true,
              schema,
            });
          else if (message.spec.filters?.some((f) => f.col === "gone"))
            bridge.handle({
              type: "queryResult",
              viewId: "v",
              id: message.id,
              ok: false,
              error: "unknown column gone",
            });
          else
            bridge.handle({
              type: "queryResult",
              viewId: "v",
              id: message.id,
              ok: true,
              result: {
                schema,
                rows: [{ symbol: "A", price: 3 }],
                row_count: 1,
                truncated: false,
                arrow_base64: null,
              },
            });
        });
    },
    () => store.queriesChanged(),
  );
  const store = new ViewStateStore(
    initial,
    (state) => bridge.stateChanged(state),
    0,
  );
  const cache = new RequestCache(bridge);
  render(
    <RuntimeProvider value={{ bridge, store, cache }}>
      <Component datasets={["df"]} />
    </RuntimeProvider>,
  );
  return {
    sent,
    store,
    cache,
    setSchema: (next: Column[]) => {
      schema = next;
    },
    queries: () => sent.filter((m) => m.type === "query").map((m) => m.spec),
    reports: () => sent.filter((m) => m.type === "stateChanged"),
  };
}

for (const [name, Component, limit] of [
  ["AG Grid", DataTable, 1000],
  ["TanStack", DataTableTanstack, 500],
] as const) {
  describe(`${name} filters`, () => {
    it("restores filters and sort through the mounted query and snapshots", async () => {
      const filters = [{ col: "price", op: "ge", value: 2 }];
      const sort = { col: "price", desc: true };
      const m = mount(Component, { filters, sort });
      const spec: QuerySpec = {
        dataset: "df",
        limit,
        filters: [{ col: "price", op: "ge", value: 2 }],
        sort: [sort],
      };
      await waitFor(() => expect(m.queries()).toContainEqual(spec));
      await waitFor(() =>
        expect(m.reports().at(-1)).toMatchObject({
          state: { filters, sort },
          queries: [spec],
        }),
      );
      act(() =>
        m.store.replace({
          filters: [{ col: "symbol", op: "contains", value: "[" }],
        }),
      );
      await waitFor(() =>
        expect(m.queries().at(-1)).toEqual({
          dataset: "df",
          limit,
          filters: [{ col: "symbol", op: "contains", value: "[" }],
        }),
      );
      expect(
        screen.getByRole("button", { name: /Remove symbol/ }),
      ).toBeTruthy();
    });

    it("applies typed filters, rejects unsafe integers, and removes predicates", async () => {
      const m = mount(Component);
      const column = await screen.findByLabelText("Filter column");
      fireEvent.change(column, { target: { value: "price" } });
      fireEvent.change(screen.getByLabelText("Filter operator"), {
        target: { value: "ge" },
      });
      fireEvent.change(screen.getByLabelText("Filter value"), {
        target: { value: "2.5" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));
      await waitFor(() =>
        expect(m.queries().at(-1)?.filters).toEqual([
          { col: "price", op: "ge", value: 2.5 },
        ]),
      );
      fireEvent.change(column, { target: { value: "volume" } });
      fireEvent.change(screen.getByLabelText("Filter value"), {
        target: { value: "9007199254740993" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));
      expect(screen.getByRole("alert").textContent).toContain("safe integer");
      expect(m.store.current().filters).toEqual([
        { col: "price", op: "ge", value: 2.5 },
      ]);
      fireEvent.click(screen.getByRole("button", { name: /Remove price/ }));
      await waitFor(() =>
        expect(m.reports().at(-1)).toMatchObject({
          state: { filters: [] },
          queries: [{ dataset: "df", limit }],
        }),
      );
    });

    it("keeps missing columns and changed types visible without dropping filters", async () => {
      const filters = [
        { col: "gone", op: "contains", value: "A" },
        { col: "price", op: "gt", value: 2 },
      ];
      const m = mount(Component, { filters });
      expect(await screen.findByText("unknown column gone")).toBeTruthy();
      expect(screen.getByText(/gone: column unavailable/)).toBeTruthy();
      act(() => {
        m.setSchema(
          columns.map((c) =>
            c.name === "price" ? { ...c, dtype: "String" } : c,
          ),
        );
        m.cache.refresh();
      });
      expect(
        await screen.findByText(/price: filter does not match String/),
      ).toBeTruthy();
      expect(m.queries().at(-1)?.filters).toEqual(filters);
      fireEvent.click(screen.getByRole("button", { name: /Remove gone/ }));
      expect(m.store.current().filters).toEqual([filters[1]]);
    });

    it.each(["AAPL", "2026-02-30", "0000-01-01"])(
      "flags a restored value %s after its column becomes Date",
      async (value) => {
        const filters = [{ col: "symbol", op: "eq", value }];
        const m = mount(Component, { filters });
        await screen.findByLabelText("Filter column");
        act(() => {
          m.setSchema(
            columns.map((c) =>
              c.name === "symbol" ? { ...c, dtype: "Date" } : c,
            ),
          );
          m.cache.refresh();
        });
        expect(
          await screen.findByText(/symbol: filter does not match Date/),
        ).toBeTruthy();
        expect(m.store.current().filters).toEqual(filters);
        expect(m.queries().at(-1)?.filters).toEqual(filters);
      },
    );

    it("offers date and null filters while limiting unsupported value types", async () => {
      const m = mount(Component);
      const column = await screen.findByLabelText("Filter column");
      fireEvent.change(column, { target: { value: "day" } });
      fireEvent.change(screen.getByLabelText("Filter value"), {
        target: { value: "2026-10-14" },
      });
      fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));
      await waitFor(() =>
        expect(m.queries().at(-1)?.filters).toEqual([
          { col: "day", op: "eq", value: "2026-10-14" },
        ]),
      );
      fireEvent.change(column, { target: { value: "exact" } });
      expect(screen.queryByLabelText("Filter value")).toBeNull();
      expect(screen.getByText(/Only null filters/)).toBeTruthy();
      fireEvent.click(screen.getByRole("button", { name: "Apply filter" }));
      await waitFor(() =>
        expect(m.queries().at(-1)?.filters).toContainEqual({
          col: "exact",
          op: "is_null",
        }),
      );
    });
  });
}
