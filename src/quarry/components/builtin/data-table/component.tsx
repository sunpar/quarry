import { useMemo, useState } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
  type ColDef,
  type SortChangedEvent,
} from "ag-grid-community";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import { TableFilters, type TableFilter } from "@/components/ui/table-filters";

ModuleRegistry.registerModules([AllCommunityModule]);

interface Props {
  datasets: string[];
}

type SortState = {
  col: string;
  desc: boolean;
};

const theme = themeQuartz.withParams({
  fontFamily: "IBM Plex Sans, sans-serif",
  cellFontFamily: "IBM Plex Mono, monospace",
  fontSize: 13,
  rowHeight: 28,
  headerHeight: 30,
});

export default function DataTable({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const [sort, setSort] = useViewState<SortState | null>("sort", null);
  const [limit] = useViewState<number>("limit", 1000);
  const [filters, setFilters] = useViewState<TableFilter[]>("filters", []);
  const live = useDatasetSchema(dataset);
  const result = useQuery({
    dataset,
    limit,
    ...(filters.length === 0 ? {} : { filters }),
    ...(sort === null ? {} : { sort: [{ col: sort.col, desc: sort.desc }] }),
  });
  // A new sort or filter is a new query, which starts out loading: the last answer stays on
  // screen until it lands.
  const [kept, setKept] = useState<typeof result | null>(null);
  if (result.status === "success" && result !== kept) setKept(result);
  const shown = result.status === "loading" && kept !== null ? kept : result;

  const columnDefs = useMemo<ColDef[]>(() => {
    if (shown.status !== "success") return [];
    return shown.schema.map((column) => ({
      field: column.name,
      headerName: column.name,
      sortable: true,
      resizable: true,
      sort: sort?.col === column.name ? (sort.desc ? "desc" : "asc") : null,
      // The query spec sorts on the server; the grid's own sort would compare Decimal
      // strings as text, so it keeps the rows in the order they came.
      comparator: () => 0,
      type: /^(Int|UInt|Float|Decimal)/.test(column.dtype)
        ? "numericColumn"
        : undefined,
    }));
  }, [shown, sort]);

  const onSortChanged = (event: SortChangedEvent) => {
    const sorted = event.api
      .getColumnState()
      .find((c) => c.sort !== null && c.sort !== undefined);
    setSort(
      sorted?.colId === undefined
        ? null
        : { col: sorted.colId, desc: sorted.sort === "desc" },
    );
  };

  return (
    <div className="flex h-full flex-col">
      <TableFilters
        schema={live ?? (shown.status === "success" ? shown.schema : null)}
        filters={filters}
        onChange={setFilters}
        sort={sort}
        onClearSort={() => setSort(null)}
      />
      {shown.status === "loading" ? (
        <p className="p-4 text-sm text-muted-foreground">Loading</p>
      ) : shown.status === "error" ? (
        <pre className="p-4 font-mono text-sm text-destructive">
          {shown.message}
        </pre>
      ) : (
        <>
          {shown !== result && (
            <p
              role="status"
              className="border-b border-border px-3 py-1 text-sm text-muted-foreground"
            >
              Loading
            </p>
          )}
          {(shown.truncated || shown.rows.length >= limit) && (
            <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
              Showing the first {shown.rows.length.toLocaleString()} rows.
            </p>
          )}
          <div className="min-h-0 flex-1" aria-busy={shown !== result}>
            <AgGridReact
              theme={theme}
              rowData={shown.rows}
              columnDefs={columnDefs}
              onSortChanged={onSortChanged}
              suppressMultiSort
              suppressFieldDotNotation
            />
          </div>
        </>
      )}
    </div>
  );
}
