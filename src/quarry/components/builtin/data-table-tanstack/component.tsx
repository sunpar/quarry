import { useMemo, useState } from "react";
import {
  createColumnHelper,
  metaHelper,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import { TableFilters, type TableFilter } from "@/components/ui/table-filters";
import type { Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

type SortState = {
  col: string;
  desc: boolean;
};

// The query spec sorts on the server, so the table registers no sorting feature.
const features = tableFeatures({
  columnMeta: metaHelper<{ numeric: boolean }>(),
});
const helper = createColumnHelper<typeof features, Row>();
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);
// One empty list for loading and error renders, so `columns` keeps its identity.
const NONE: never[] = [];

export default function DataTableTanstack({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const [sort, setSort] = useViewState<SortState | null>("sort", null);
  const [limit] = useViewState<number>("limit", 500);
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
  const rows = shown.status === "success" ? shown.rows : NONE;
  const schema = shown.status === "success" ? shown.schema : NONE;
  const columns = useMemo(
    () =>
      helper.columns(
        schema.map((c) =>
          helper.accessor((row) => row[c.name], {
            id: c.name,
            header: c.name,
            cell: (info) => format(info.getValue()),
            meta: { numeric: isNumeric(c.dtype) },
          }),
        ),
      ),
    [schema],
  );
  const table = useTable({ features, columns, data: rows });

  // Ascending, then descending, then back to the order the rows came in.
  const onHeader = (col: string) =>
    setSort(
      sort?.col !== col
        ? { col, desc: false }
        : sort.desc
          ? null
          : { col, desc: true },
    );

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
          {(shown.truncated || rows.length >= limit) && (
            <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
              Showing the first {rows.length.toLocaleString()} rows.
            </p>
          )}
          <div
            className="min-h-0 flex-1 overflow-auto"
            aria-busy={shown !== result}
          >
            <table className="w-full border-collapse text-sm">
              <thead className="sticky top-0 bg-card">
                {table.getHeaderGroups().map((group) => (
                  <tr key={group.id}>
                    {group.headers.map((header) => (
                      <th
                        key={header.id}
                        className="border-b border-border px-2 py-1 text-left font-medium"
                        aria-sort={
                          sort?.col !== header.column.id
                            ? "none"
                            : sort.desc
                              ? "descending"
                              : "ascending"
                        }
                      >
                        <button
                          type="button"
                          className="w-full cursor-pointer text-left"
                          onClick={() => onHeader(header.column.id)}
                        >
                          <table.FlexRender header={header} />
                          {/* aria-sort carries the direction, so the arrow stays out of the name. */}
                          {sort?.col === header.column.id && (
                            <span aria-hidden="true">
                              {sort.desc ? " ▼" : " ▲"}
                            </span>
                          )}
                        </button>
                      </th>
                    ))}
                  </tr>
                ))}
              </thead>
              <tbody>
                {table.getRowModel().rows.map((row) => (
                  <tr key={row.id} className="border-b border-border/60">
                    {row.getAllCells().map((cell) => (
                      <td
                        key={cell.id}
                        className={
                          cell.column.columnDef.meta?.numeric
                            ? "px-2 py-1 text-right font-mono"
                            : "px-2 py-1"
                        }
                      >
                        <table.FlexRender cell={cell} />
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
    </div>
  );
}

function format(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
