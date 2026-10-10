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

// The one built-in that asks for more rows than the server's cap; the server truncates.
const LIMIT = 500000;

const isTime = (dtype: string) =>
  dtype === "Date" || dtype.startsWith("Datetime");
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);

export default function LargeSeries({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [chosen, setChosen] = useViewState<Columns>("columns", {
    time: null,
    value: null,
  });
  // A saved column counts only while the live schema still has it with a fitting dtype.
  const pick = (saved: string | null, fits: (dtype: string) => boolean) =>
    schema?.find((c) => c.name === saved && fits(c.dtype))?.name ??
    schema?.find((c) => fits(c.dtype))?.name ??
    null;
  const time = pick(chosen.time, isTime);
  const value = pick(chosen.value, isNumeric);
  const ready = time !== null && value !== null;
  const result = useQuery(
    ready
      ? { dataset, select: [time, value], sort: [{ col: time }], limit: LIMIT }
      : { dataset, limit: 1 },
  );

  if (schema === null)
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs a date column and a numeric column.
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
        large: true,
        largeThreshold: 2000,
        sampling: "lttb",
        data: toPoints(result.rows, time, value),
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
          options={schema.filter((c) => isTime(c.dtype)).map((c) => c.name)}
          onChange={(v) => setChosen({ time: v, value })}
        />
        <Select
          label="Value"
          value={value}
          options={schema.filter((c) => isNumeric(c.dtype)).map((c) => c.name)}
          onChange={(v) => setChosen({ time, value: v })}
        />
      </div>
      {(result.truncated || result.rows.length >= LIMIT) && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          Showing the first {result.rows.length.toLocaleString()} rows.
        </p>
      )}
      <div className="min-h-0 flex-1">
        <ReactECharts
          option={option}
          notMerge
          style={{ height: "100%", width: "100%" }}
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

// [epoch ms, value] pairs, in the time order the rows arrive in; unplottable rows are dropped.
function toPoints(
  rows: Row[],
  time: string,
  value: string,
): [number, number][] {
  const points: [number, number][] = [];
  for (const row of rows) {
    const ms = parseTime(row[time] ?? null);
    const v = parseValue(row[value] ?? null);
    if (Number.isFinite(ms) && Number.isFinite(v)) points.push([ms, v]);
  }
  return points;
}
