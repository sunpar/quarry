import { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import {
  AllCommunityModule,
  ModuleRegistry,
  themeQuartz,
  type ColDef,
  type SortChangedEvent,
} from "ag-grid-community";
import { useQuery, useViewState } from "@quarry/hooks";

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
  const result = useQuery({
    dataset,
    limit,
    ...(sort === null ? {} : { sort: [{ col: sort.col, desc: sort.desc }] }),
  });

  const columnDefs = useMemo<ColDef[]>(() => {
    if (result.status !== "success") return [];
    return result.schema.map((column) => ({
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
  }, [result, sort]);

  if (result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

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
      {(result.truncated || result.rows.length >= limit) && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          Showing the first {result.rows.length.toLocaleString()} rows.
        </p>
      )}
      <div className="min-h-0 flex-1">
        <AgGridReact
          theme={theme}
          rowData={result.rows}
          columnDefs={columnDefs}
          onSortChanged={onSortChanged}
          suppressMultiSort
          suppressFieldDotNotation
        />
      </div>
    </div>
  );
}
