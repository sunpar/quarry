import { useEffect, useRef } from "react";
import {
  createChart,
  LineSeries,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

type Columns = {
  time: string | null;
  value: string | null;
};

const LIMIT = 50000;

const isTime = (dtype: string) =>
  dtype === "Date" || dtype.startsWith("Datetime");
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);

export default function TimeSeries({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [chosen, setChosen] = useViewState<Columns>("columns", {
    time: null,
    value: null,
  });
  const time =
    chosen.time ?? schema?.find((c) => isTime(c.dtype))?.name ?? null;
  const value =
    chosen.value ?? schema?.find((c) => isNumeric(c.dtype))?.name ?? null;
  const ready = time !== null && value !== null;
  const result = useQuery(
    ready
      ? { dataset, select: [time, value], sort: [{ col: time }], limit: LIMIT }
      : { dataset, limit: 1 },
  );
  const rows = result.status === "success" ? result.rows : null;
  const container = useRef<HTMLDivElement>(null);

  // Lightweight Charts owns its canvas; this is the one place a DOM library needs an effect.
  useEffect(() => {
    const el = container.current;
    if (el === null || !ready || rows === null) return;
    const chart: IChartApi = createChart(el, {
      autoSize: true,
      layout: {
        attributionLogo: true,
        fontFamily: "IBM Plex Sans, sans-serif",
      },
    });
    const series = chart.addSeries(LineSeries, {
      color: "#1e6e63",
      lineWidth: 2,
    });
    series.setData(toPoints(rows, time, value));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [ready, rows, time, value]);

  if (schema === null)
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready) {
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs a date column and a numeric column.
      </p>
    );
  }
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
      <div className="flex gap-3 border-b border-border px-3 py-1 text-sm">
        <ColumnPicker
          label="Time"
          value={time}
          options={schema.filter((c) => isTime(c.dtype)).map((c) => c.name)}
          onChange={(t) => setChosen({ time: t, value })}
        />
        <ColumnPicker
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
      <div ref={container} className="min-h-0 flex-1" />
    </div>
  );
}

interface PickerProps {
  label: string;
  value: string;
  options: string[];
  onChange: (next: string) => void;
}

function ColumnPicker({ label, value, options, onChange }: PickerProps) {
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

type Point = { time: UTCTimestamp; value: number };

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

// Rows arrive sorted by time. Lightweight Charts needs finite, strictly ascending
// times, so unplottable rows are dropped and rows on the same second keep the last.
function toPoints(rows: Row[], time: string, value: string): Point[] {
  const points: Point[] = [];
  for (const row of rows) {
    const v = parseValue(row[value] ?? null);
    const ms = parseTime(row[time] ?? null);
    if (!Number.isFinite(v) || !Number.isFinite(ms)) continue;
    const t = Math.floor(ms / 1000) as UTCTimestamp;
    if (points.length > 0 && points[points.length - 1]?.time === t)
      points.pop();
    points.push({ time: t, value: v });
  }
  return points;
}
