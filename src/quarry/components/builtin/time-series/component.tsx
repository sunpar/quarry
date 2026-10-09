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
      ? { dataset, select: [time, value], sort: [{ col: time }], limit: 50000 }
      : { dataset, limit: 1 },
  );
  const container = useRef<HTMLDivElement>(null);

  // Lightweight Charts owns its canvas; this is the one place a DOM library needs an effect.
  useEffect(() => {
    const el = container.current;
    if (el === null || !ready || result.status !== "success") return;
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
    series.setData(result.rows.map((row) => point(row, time, value)));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [ready, result, time, value]);

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

function point(
  row: Row,
  time: string,
  value: string,
): { time: UTCTimestamp; value: number } {
  const raw = row[time];
  const ms =
    typeof raw === "string"
      ? Date.parse(raw)
      : typeof raw === "number"
        ? raw
        : NaN;
  const v = row[value];
  return {
    time: Math.floor(ms / 1000) as UTCTimestamp,
    value: typeof v === "number" ? v : NaN,
  };
}
