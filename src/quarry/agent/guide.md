## lightweight-charts

Price and return series, OHLC. Use when speed and a clean look matter more than annotations. Import `createChart`, `LineSeries`, `CandlestickSeries` from "lightweight-charts". Use chart.addSeries(LineSeries, options) (v5 API) and keep attributionLogo: true.

## plotly

Scatter, heatmap, 3D, statistical plots, anything general. `import Plot from "react-plotly.js"`; pass `data`, `layout` and `useResizeHandler` with a sized container.

## echarts

Series with more than about 100k points, calendar and sankey. `import ReactECharts from "echarts-for-react"`; pass `option` and `style={{ height: "100%" }}`.

## recharts

Small aggregated bar and line charts inside shadcn layouts. Import `ResponsiveContainer`, `BarChart`, `LineChart`, `Bar`, `Line`, `XAxis`, `YAxis`, `Tooltip` from "recharts".

## perspective

When the researcher should drive pivots and filters directly. Import `PerspectiveViewer` from "@quarry/perspective". Query with `format: "arrow"` and pass the result's `arrow` buffer; read the viewer's config through `onConfig`.

## ag-grid

Tables with column filters and resizing. Import `AgGridReact` from "ag-grid-react" and `AllCommunityModule`, `ModuleRegistry`, `themeQuartz` from "ag-grid-community". Call ModuleRegistry.registerModules([AllCommunityModule]) once and pass theme={themeQuartz}; do not import CSS.

## tanstack-table

Tables that need custom cell rendering inside shadcn styling. TanStack Table v9, not v8: import `useTable`, `tableFeatures`, `createColumnHelper` from "@tanstack/react-table". At module scope, `const features = tableFeatures({})` (add `rowSortingFeature` and `sortedRowModel: createSortedRowModel()` to sort) and `const helper = createColumnHelper<typeof features, MyRow>()`. Call `useTable({ features, columns, data })` with a memoised `data`, and render `<table.FlexRender header={header} />` and, over `row.getAllCells()`, `<table.FlexRender cell={cell} />`.

## d3

Only when nothing above fits. `import * as d3 from "d3"` and draw into a ref inside an effect.

## highcharts

Full stock charts: navigator, range selector, indicators, annotations. Import `HighchartsReact` from "@quarry/highcharts" and pass `options`; `import Highcharts from "highcharts/highstock"` only for static helpers.

## scichart

Very large series and realtime rendering. Import `SciChartSurface`, `NumericAxis`, `FastLineRenderableSeries`, `XyDataSeries` from "scichart" and create the surface in an effect; the runtime has already configured the wasm path and license.
