import Plot from "react-plotly.js";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Agg, Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

type Columns = {
  row: string | null;
  column: string | null;
  value: string | null;
};

const AGGS: Agg["fn"][] = ["mean", "sum", "count", "min", "max", "median"];
const LIMIT = 500;

const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);
// A saved column counts only while the live schema still offers it.
const fit = (saved: string | null, options: string[]) =>
  saved !== null && options.includes(saved) ? saved : null;
// The options no earlier role holds, compared ignoring case as the kernel compares names.
const others = (options: string[], taken: (string | null)[]) =>
  options.filter(
    (o) => !taken.some((t) => t?.toLowerCase() === o.toLowerCase()),
  );

export default function Heatmap({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [agg, setAgg] = useViewState<Agg["fn"]>("agg", "mean");
  const [chosen, setChosen] = useViewState<Columns>("columns", {
    row: null,
    column: null,
    value: null,
  });
  const names = (schema ?? []).map((c) => c.name);
  const numeric = (schema ?? [])
    .filter((c) => isNumeric(c.dtype))
    .map((c) => c.name);
  // The value first, so no key choice can leave it without a column. The keys take the
  // rest, non-numeric ones first, and a column pivoted against itself is only a diagonal.
  const value = fit(chosen.value, numeric) ?? numeric[0] ?? null;
  const free = others(names, [value]);
  const keys = [
    ...free.filter((n) => !numeric.includes(n)),
    ...free.filter((n) => numeric.includes(n)),
  ];
  const row = fit(chosen.row, free) ?? keys[0] ?? null;
  const columns = others(free, [row]);
  const column = fit(chosen.column, columns) ?? others(keys, [row])[0] ?? null;
  const ready = row !== null && column !== null && value !== null;
  const result = useQuery(
    ready
      ? {
          dataset,
          pivot: { index: [row], columns: column, values: value, agg },
          sort: [{ col: row }],
          limit: LIMIT,
        }
      : { dataset, limit: 1 },
  );

  if (schema === null)
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs two key columns and a numeric column.
      </p>
    );
  if (result.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (result.status === "error")
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {result.message}
      </pre>
    );

  // The pivoted frame is the row key plus one column per distinct `column` value. `cols`
  // reads the result schema, so an empty result still renders an empty grid. A null or
  // non-numeric cell becomes NaN, which Plotly leaves blank.
  const cols = result.schema.map((c) => c.name).filter((n) => n !== row);
  const z = result.rows.map((r) => cols.map((c) => parseValue(r[c] ?? null)));
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        <Select
          label="Row"
          value={row}
          options={free}
          onChange={(v) => setChosen({ row: v, column, value })}
        />
        <Select
          label="Column"
          value={column}
          options={columns}
          onChange={(v) => setChosen({ row, column: v, value })}
        />
        <Select
          label="Value"
          value={value}
          options={numeric}
          onChange={(v) => setChosen({ row, column, value: v })}
        />
        <Select
          label="Aggregate"
          value={agg}
          options={AGGS}
          onChange={(v) => setAgg(v as Agg["fn"])}
        />
      </div>
      {(result.truncated || result.rows.length >= LIMIT) && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          Showing the first {result.rows.length.toLocaleString()} rows.
        </p>
      )}
      <div className="min-h-0 flex-1">
        <Plot
          data={[
            {
              type: "heatmap",
              z,
              x: cols,
              y: result.rows.map((r) => String(r[row] ?? null)),
              colorscale: "Viridis",
            },
          ]}
          layout={{
            autosize: true,
            margin: { t: 16, r: 16, b: 60, l: 80 },
            font: { family: "IBM Plex Sans, sans-serif" },
          }}
          useResizeHandler
          style={{ width: "100%", height: "100%" }}
          config={{ displaylogo: false }}
        />
      </div>
    </div>
  );
}

interface SelectProps {
  label: string;
  value: string;
  options: string[];
  onChange: (next: string) => void;
}

function Select({ label, value, options, onChange }: SelectProps) {
  return (
    <label className="flex items-center gap-1 text-muted-foreground">
      {label}
      <select
        className="bg-transparent text-foreground"
        value={value}
        onChange={(e) => onChange(e.target.value)}
      >
        {options.map((o) => (
          <option key={o} value={o}>
            {o}
          </option>
        ))}
      </select>
    </label>
  );
}

// Decimal columns are serialised as strings to keep their precision.
function parseValue(raw: Row[string]): number {
  if (typeof raw === "number") return raw;
  return typeof raw === "string" && raw.trim() !== "" ? Number(raw) : NaN;
}
