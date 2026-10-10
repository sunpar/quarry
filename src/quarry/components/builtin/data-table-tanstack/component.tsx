import { useMemo } from "react";
import {
  createColumnHelper,
  metaHelper,
  tableFeatures,
  useTable,
} from "@tanstack/react-table";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
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
  const [saved, setSort] = useViewState<SortState | null>("sort", null);
  const [limit] = useViewState<number>("limit", 500);
  // A saved sort on a column the live dataset no longer has would fail every query.
  const live = useDatasetSchema(dataset);
  const sort =
    saved !== null && live?.some((c) => c.name === saved.col) === false
      ? null
      : saved;
  const result = useQuery({
    dataset,
    limit,
    ...(sort === null ? {} : { sort: [{ col: sort.col, desc: sort.desc }] }),
  });
  const rows = result.status === "success" ? result.rows : NONE;
  const schema = result.status === "success" ? result.schema : NONE;
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

  if (result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

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
      {(result.truncated || rows.length >= limit) && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          Showing the first {rows.length.toLocaleString()} rows.
        </p>
      )}
      <div className="min-h-0 flex-1 overflow-auto">
        <table className="w-full border-collapse text-sm">
          <thead className="sticky top-0 bg-card">
            {table.getHeaderGroups().map((group) => (
              <tr key={group.id}>
                {group.headers.map((header) => (
                  <th
                    key={header.id}
                    className="cursor-pointer border-b border-border px-2 py-1 text-left font-medium"
                    onClick={() => onHeader(header.column.id)}
                  >
                    <table.FlexRender header={header} />
                    {sort?.col === header.column.id &&
                      (sort.desc ? " ▼" : " ▲")}
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
    </div>
  );
}

function format(value: unknown): string {
  if (value === null || value === undefined) return "";
  return typeof value === "object" ? JSON.stringify(value) : String(value);
}
