import Plot from "react-plotly.js";
import type { Data } from "plotly.js";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

type Columns = {
  x: string | null;
  y: string | null;
  color: string | null;
};

const LIMIT = 20000;

const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);
// A saved column counts only while the live schema still offers it.
const fit = (saved: string | null, options: string[]) =>
  saved !== null && options.includes(saved) ? saved : null;
// The options no earlier role holds; the kernel refuses a select name repeated in any case.
const others = (options: string[], taken: (string | null)[]) =>
  options.filter(
    (o) => !taken.some((t) => t?.toLowerCase() === o.toLowerCase()),
  );

export default function Scatter({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [chosen, setChosen] = useViewState<Columns>("columns", {
    x: null,
    y: null,
    color: null,
  });
  const names = (schema ?? []).map((c) => c.name);
  const numeric = (schema ?? [])
    .filter((c) => isNumeric(c.dtype))
    .map((c) => c.name);
  const x = fit(chosen.x, numeric) ?? numeric[0] ?? null;
  const ys = others(numeric, [x]);
  const y = fit(chosen.y, ys) ?? ys[0] ?? null;
  const colors = others(names, [x, y]);
  const color = fit(chosen.color, colors);
  const ready = x !== null && y !== null;
  const result = useQuery(
    ready
      ? {
          dataset,
          select: [x, y, ...(color === null ? [] : [color])],
          limit: LIMIT,
        }
      : { dataset, limit: 1 },
  );

  if (schema === null)
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs two numeric columns.
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

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        <Select
          label="X"
          value={x}
          options={numeric}
          onChange={(v) => setChosen({ x: v, y, color })}
        />
        <Select
          label="Y"
          value={y}
          options={ys}
          onChange={(v) => setChosen({ x, y: v, color })}
        />
        <Select
          label="Color"
          value={color ?? ""}
          options={["", ...colors]}
          onChange={(v) => setChosen({ x, y, color: v === "" ? null : v })}
        />
      </div>
      {(result.truncated || result.rows.length >= LIMIT) && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          Showing the first {result.rows.length.toLocaleString()} rows.
        </p>
      )}
      <div className="min-h-0 flex-1">
        <Plot
          data={tracesFor(result.rows, x, y, color)}
          layout={{
            autosize: true,
            margin: { t: 16, r: 16, b: 40, l: 48 },
            xaxis: { title: { text: x } },
            yaxis: { title: { text: y } },
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

// One trace without a color column, one per distinct value with it. A point whose x or y
// is not a finite number is dropped rather than drawn at zero.
function tracesFor(
  rows: Row[],
  x: string,
  y: string,
  color: string | null,
): Data[] {
  const groups = new Map<string, { x: number[]; y: number[] }>();
  for (const row of rows) {
    const px = parseValue(row[x] ?? null);
    const py = parseValue(row[y] ?? null);
    if (!Number.isFinite(px) || !Number.isFinite(py)) continue;
    const key = color === null ? "" : String(row[color] ?? null);
    const group = groups.get(key) ?? { x: [], y: [] };
    group.x.push(px);
    group.y.push(py);
    groups.set(key, group);
  }
  return [...groups.entries()].map(([name, points]) => ({
    type: "scattergl",
    mode: "markers",
    name,
    x: points.x,
    y: points.y,
    marker: { size: 5, ...(color === null ? { color: "#1e6e63" } : {}) },
  }));
}
