import ReactECharts from "echarts-for-react";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

type Columns = {
  time: string | null;
  value: string | null;
};

const isTime = (dtype: string) =>
  dtype === "Date" || dtype.startsWith("Datetime");
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);
// A saved column counts only while the live schema still offers it.
const fit = (saved: string | null, options: string[]) =>
  saved !== null && options.includes(saved) ? saved : null;
// The options no earlier role holds; the kernel refuses a select name repeated in any case.
const others = (options: string[], taken: (string | null)[]) =>
  options.filter(
    (o) => !taken.some((t) => t?.toLowerCase() === o.toLowerCase()),
  );

export default function LargeSeries({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [chosen, setChosen] = useViewState<Columns>("columns", {
    time: null,
    value: null,
  });
  const names = (fits: (dtype: string) => boolean) =>
    (schema ?? []).filter((c) => fits(c.dtype)).map((c) => c.name);
  const numeric = names(isNumeric);
  // A time column fits only if it leaves a value: `Date` beside a lone `date` does not.
  const times = names(isTime).filter((t) =>
    numeric.some((n) => n.toLowerCase() !== t.toLowerCase()),
  );
  // A saved time stays; otherwise take the first that does not clash with the saved value.
  const time =
    fit(chosen.time, times) ??
    others(times, [fit(chosen.value, numeric)])[0] ??
    times[0] ??
    null;
  const values = others(numeric, [time]);
  const value = fit(chosen.value, values) ?? values[0] ?? null;
  const ready = time !== null && value !== null;
  const result = useQuery(
    ready
      ? { dataset, line_reduce: { time, value, max_rows: 50000 } }
      : { dataset, limit: 1 },
  );

  if (schema === null)
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs a date column and a numeric column whose names differ
        by more than case.
      </p>
    );
  const option = {
    animation: false,
    // Points are UTC epoch milliseconds; local time would shift labels across DST changes.
    useUTC: true,
    grid: { top: 16, right: 16, bottom: 48, left: 56 },
    xAxis: { type: "time" },
    yAxis: { type: "value", scale: true },
    dataZoom: [{ type: "inside" }, { type: "slider" }],
    tooltip: { trigger: "axis" },
    series: [
      {
        type: "line",
        showSymbol: false,
        connectNulls: false,
        data: toPoints(
          result.status === "success" ? result.rows : [],
          time,
          value,
        ),
        lineStyle: { color: "#1e6e63", width: 1 },
      },
    ],
  };
  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        <Select
          label="Time"
          value={time}
          options={others(times, [value])}
          onChange={(v) => setChosen({ time: v, value })}
        />
        <Select
          label="Value"
          value={value}
          options={values}
          onChange={(v) => setChosen({ time, value: v })}
        />
      </div>
      {result.status === "success" && result.truncated && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          Showing the first {result.rows.length.toLocaleString()} rows.
        </p>
      )}
      {result.status === "success" && result.reduced && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          Reduced {result.sourceRowCount?.toLocaleString()} rows across the
          whole time range to {result.rows.length.toLocaleString()}{" "}
          representative {result.rows.length === 1 ? "row" : "rows"}.
        </p>
      )}
      <div className="min-h-0 flex-1">
        {result.status === "loading" ? (
          <p className="p-4 text-sm text-muted-foreground">Loading</p>
        ) : result.status === "error" ? (
          <pre className="whitespace-pre-wrap p-4 font-mono text-sm text-destructive">
            {result.message}
          </pre>
        ) : (
          <ReactECharts
            option={option}
            notMerge
            style={{ height: "100%", width: "100%" }}
          />
        )}
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

// Naive ISO datetimes carry no offset; the kernel runs in UTC, so read them as UTC.
function parseTime(raw: Row[string]): number {
  if (typeof raw === "number") return raw;
  if (typeof raw !== "string") return NaN;
  const naive = raw.includes("T") && !/(Z|[+-]\d{2}:?\d{2})$/.test(raw);
  return Date.parse(naive ? `${raw}Z` : raw);
}

// Decimal columns are serialised as strings to keep their precision.
function parseValue(raw: Row[string]): number {
  if (typeof raw === "number") return raw;
  return typeof raw === "string" && raw.trim() !== "" ? Number(raw) : NaN;
}

// Keep null values as line breaks; a missing time has no position on the chart.
function toPoints(
  rows: Row[],
  time: string,
  value: string,
): [number, number | null][] {
  const points: [number, number | null][] = [];
  for (const row of rows) {
    const ms = parseTime(row[time] ?? null);
    const v = parseValue(row[value] ?? null);
    if (Number.isFinite(ms)) points.push([ms, Number.isFinite(v) ? v : null]);
  }
  return points;
}
