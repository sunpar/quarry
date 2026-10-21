import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  createChart,
  type CandlestickData,
  type IChartApi,
  type UTCTimestamp,
} from "lightweight-charts";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import type { Row } from "@/shared/api-types";

interface Props {
  datasets: string[];
}

type Role = "time" | "open" | "high" | "low" | "close";
type Columns = Record<Role, string | null>;

const LIMIT = 50000;
const EMPTY: Columns = {
  time: null,
  open: null,
  high: null,
  low: null,
  close: null,
};
const LABELS: Record<Role, string> = {
  time: "Time",
  open: "Open",
  high: "High",
  low: "Low",
  close: "Close",
};
const PRICES = ["open", "high", "low", "close"] as const;

const isTime = (dtype: string) =>
  dtype === "Date" || dtype.startsWith("Datetime");
const isNumeric = (dtype: string) => /^(Int|UInt|Float|Decimal)/.test(dtype);
// The kernel compares names ignoring case, so it refuses a select holding two names
// that differ only in case, though it takes one column picked for two roles.
const clashes = (name: string, taken: (string | null)[]) =>
  taken.some((t) => t !== name && t?.toLowerCase() === name.toLowerCase());
// The options no role holds and none clashes with.
const others = (options: string[], taken: (string | null)[]) =>
  options.filter((o) => !taken.includes(o) && !clashes(o, taken));

export default function Ohlc({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  const schema = useDatasetSchema(dataset);
  const [chosen, setChosen] = useViewState<Columns>("columns", EMPTY);
  const names = (fits: (dtype: string) => boolean) =>
    (schema ?? []).filter((c) => fits(c.dtype)).map((c) => c.name);
  const times = names(isTime);
  const numeric = names(isNumeric);
  const columns = resolve(chosen, times, numeric);
  const { time, open, high, low, close } = columns;
  const ready =
    time !== null &&
    open !== null &&
    high !== null &&
    low !== null &&
    close !== null;
  const result = useQuery(
    ready
      ? {
          dataset,
          // A column picked for two roles is selected once: the kernel refuses a repeat.
          select: [...new Set([time, open, high, low, close])],
          sort: [{ col: time }],
          limit: LIMIT,
        }
      : { dataset, limit: 1 },
  );
  const rows = result.status === "success" ? result.rows : null;
  const container = useRef<HTMLDivElement>(null);

  // Keyed on the column names: resolve() builds a new `columns` on every render.
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
    const series = chart.addSeries(CandlestickSeries, {
      upColor: "#1e6e63",
      downColor: "#9a3b2e",
      wickUpColor: "#1e6e63",
      wickDownColor: "#9a3b2e",
      borderVisible: false,
    });
    series.setData(toCandles(rows, { time, open, high, low, close }));
    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [ready, rows, time, open, high, low, close]);

  if (schema === null)
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (!ready)
    return (
      <p className="p-4 text-sm text-muted-foreground">
        This dataset needs a date column and open, high, low and close columns.
      </p>
    );

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-wrap gap-3 border-b border-border px-3 py-1 text-sm">
        {(["time", ...PRICES] as const).map((role) => (
          <ColumnPicker
            key={role}
            label={LABELS[role]}
            value={columns[role] ?? ""}
            options={(role === "time" ? times : numeric).filter(
              (o) => !clashes(o, Object.values({ ...columns, [role]: null })),
            )}
            onChange={(v) => setChosen({ ...columns, [role]: v })}
          />
        ))}
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

// Saved columns the live schema still fits, then columns named like the role, then the
// next numeric one. A saved column counts only if it does not clash with one resolved
// before it, and a guess takes only a column no other role holds. The time comes after
// the saved prices, so its fallback skips a time column that clashes with one.
function resolve(chosen: Columns, times: string[], numeric: string[]) {
  const out: Columns = { ...EMPTY };
  const fit = (saved: string | null, options: string[]) =>
    saved !== null &&
    options.includes(saved) &&
    !clashes(saved, Object.values(out))
      ? saved
      : null;
  for (const role of PRICES) out[role] = fit(chosen[role], numeric);
  out.time =
    fit(chosen.time, times) ??
    others(times, Object.values(out))[0] ??
    times[0] ??
    null;
  // With no other time column free, a saved price that clashes gives way to the time.
  for (const role of PRICES) {
    const price = out[role];
    if (price !== null && clashes(price, [out.time])) out[role] = null;
  }
  const guess = (match: (name: string, role: string) => boolean) => {
    for (const role of PRICES)
      out[role] ??=
        others(numeric, Object.values(out)).find((n) => match(n, role)) ?? null;
  };
  guess((name, role) => name.toLowerCase().startsWith(role));
  guess(() => true);
  return out;
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

type Candle = CandlestickData<UTCTimestamp>;

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
function toCandles(rows: Row[], columns: Record<Role, string>): Candle[] {
  const candles: Candle[] = [];
  for (const row of rows) {
    const ms = parseTime(row[columns.time] ?? null);
    const candle: Candle = {
      time: Math.floor(ms / 1000) as UTCTimestamp,
      open: parseValue(row[columns.open] ?? null),
      high: parseValue(row[columns.high] ?? null),
      low: parseValue(row[columns.low] ?? null),
      close: parseValue(row[columns.close] ?? null),
    };
    if (!Object.values(candle).every(Number.isFinite)) continue;
    if (candles.at(-1)?.time === candle.time) candles.pop();
    candles.push(candle);
  }
  return candles;
}
