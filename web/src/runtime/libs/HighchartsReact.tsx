import { useEffect, useRef } from "react";
import { loadHighstock } from "./highcharts";

interface ChartLike {
  update(options: object, redraw?: boolean): void;
  destroy(): void;
}

interface HighchartsLike {
  chart(el: HTMLElement, options: object): ChartLike;
  stockChart(el: HTMLElement, options: object): ChartLike;
}

interface HighchartsReactProps {
  options: object;
  constructorType?: "chart" | "stockChart";
  className?: string;
}

/** Replaces highcharts-react-official, which would need Highcharts as a bundled peer. */
export function HighchartsReact({
  options,
  constructorType = "stockChart",
  className,
}: HighchartsReactProps) {
  const host = useRef<HTMLDivElement>(null);
  const chart = useRef<ChartLike | null>(null);
  // Highstock loads asynchronously; the chart starts from the options current at that point.
  const latest = useRef(options);
  latest.current = options;

  useEffect(() => {
    const el = host.current;
    if (el === null) return;
    let cancelled = false;
    void loadHighstock().then((mod) => {
      if (cancelled) return;
      const hc = (mod as { default: HighchartsLike }).default;
      chart.current = hc[constructorType](el, latest.current);
    });
    return () => {
      cancelled = true;
      chart.current?.destroy();
      chart.current = null;
    };
  }, [constructorType]);

  // Options changes update in place; only a new constructor type rebuilds the chart.
  useEffect(() => {
    chart.current?.update(options, true);
  }, [options]);

  return <div ref={host} className={className ?? "h-full w-full"} />;
}
