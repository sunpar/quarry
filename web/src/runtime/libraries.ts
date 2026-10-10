export const RUNTIME_LIBRARIES = [
  "ag-grid",
  "lightweight-charts",
  "perspective",
  "plotly",
  "echarts",
  "recharts",
  "tanstack-table",
  "d3",
  "highcharts",
  "scichart",
] as const;
export type RuntimeLibrary = (typeof RUNTIME_LIBRARIES)[number];
