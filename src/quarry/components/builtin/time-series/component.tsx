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
// A saved column counts only while the live schema still offers it.
const fit = (saved: string | null, options: string[]) =>
  saved !== null && options.includes(saved) ? saved : null;
// The options no earlier role holds; the kernel refuses a select name repeated in any case.
const others = (options: string[], taken: (string | null)[]) =>
  options.filter(
    (o) => !taken.some((t) => t?.toLowerCase() === o.toLowerCase()),
  );

export default function TimeSeries({ datasets }: Props) {
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
  const times = names(isTime).filter((t) => others(numeric, [t]).length > 0);
  const time = fit(chosen.time, times) ?? times[0] ?? null;
  const values = others(numeric, [time]);
  const value = fit(chosen.value, values) ?? values[0] ?? null;
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

  return (
    <div className="flex h-full flex-col">
      <div className="flex gap-3 border-b border-border px-3 py-1 text-sm">
        <ColumnPicker
          label="Time"
          value={time}
          options={times}
          onChange={(t) => setChosen({ time: t, value })}
        />
        <ColumnPicker
          label="Value"
          value={value}
          options={values}
          onChange={(v) => setChosen({ time, value: v })}
        />
      </div>
      {result.status === "success" &&
        (result.truncated || result.rows.length >= LIMIT) && (
          <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
            Showing the first {result.rows.length.toLocaleString()} rows.
          </p>
        )}
      {result.status === "loading" ? (
        <p className="p-4 text-sm text-muted-foreground">Loading</p>
      ) : result.status === "error" ? (
        <pre className="whitespace-pre-wrap p-4 font-mono text-sm text-destructive">
          {result.message}
        </pre>
      ) : (
        <div ref={container} className="min-h-0 flex-1" />
      )}
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
