import {
  Bar,
  BarChart,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Agg, Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

type Kind = "bar" | "line";
type Columns = {
  category: string | null;
  value: string | null;
};

const AGGS: Agg["fn"][] = ["sum", "mean", "count", "min", "max", "median"];
const LIMIT = 500;

const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);
// A saved column counts only while the live schema still offers it.
const fit = (saved: string | null, options: string[]) =>
  saved !== null && options.includes(saved) ? saved : null;
// The options no other output column holds; the kernel compares output names ignoring case.
const others = (options: string[], taken: (string | null)[]) =>
  options.filter(
    (o) => !taken.some((t) => t?.toLowerCase() === o.toLowerCase()),
  );

export default function BarLine({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [kind, setKind] = useViewState<Kind>("kind", "bar");
  const [agg, setAgg] = useViewState<Agg["fn"]>("agg", "sum");
  const [chosen, setChosen] = useViewState<Columns>("columns", {
    category: null,
    value: null,
  });
  const names = (schema ?? []).map((c) => c.name);
  const numeric = (schema ?? [])
    .filter((c) => isNumeric(c.dtype))
    .map((c) => c.name);
  const value = fit(chosen.value, numeric) ?? numeric[0] ?? null;
  // The kernel names the aggregate `<value>_<fn>`, so no category may take that name.
  const key = `${value}_${agg}`;
  const categories = others(names, [key]);
  // A non-numeric category first, then any other column, then the value itself: the
  // kernel groups by any dtype, and by the column it aggregates as well.
  const category =
    fit(chosen.category, categories) ??
    categories.find((n) => !numeric.includes(n)) ??
    categories.find((n) => n !== value) ??
    categories[0] ??
    null;
  const ready = category !== null && value !== null;
  const result = useQuery(
    ready
      ? {
          dataset,
          group_by: [category],
          aggs: [{ col: value, fn: agg }],
          sort: [{ col: category }],
          limit: LIMIT,
        }
      : { dataset, limit: 1 },
  );

  if (schema === null)
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs a category column and a numeric column.
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

  // Integer sums arrive as exact decimal strings, and a group with no values aggregates
  // to null, which Recharts leaves a gap for.
  const data = result.rows.map((row) => {
    const v = parseValue(row[key] ?? null);
    return { ...row, [key]: Number.isFinite(v) ? v : null };
  });
  const Chart = kind === "bar" ? BarChart : LineChart;
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        <Select
          label="Chart"
          value={kind}
          options={["bar", "line"]}
          onChange={(v) => setKind(v as Kind)}
        />
        <Select
          label="Category"
          value={category}
          options={categories}
          onChange={(v) => setChosen({ category: v, value })}
        />
        <Select
          label="Value"
          value={value}
          options={numeric}
          onChange={(v) => setChosen({ category, value: v })}
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
      <div className="min-h-0 flex-1 p-2">
        <ResponsiveContainer width="100%" height="100%">
          <Chart data={data}>
            <XAxis dataKey={category} />
            <YAxis />
            <Tooltip />
            {kind === "bar" ? (
              <Bar dataKey={key} fill="#1e6e63" />
            ) : (
              <Line dataKey={key} stroke="#1e6e63" dot={false} />
            )}
          </Chart>
        </ResponsiveContainer>
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
