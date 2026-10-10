import { loadHighstock } from "./libs/highcharts";
import { loadScichart } from "./libs/scichart";
import type { ModuleTable } from "./loader";

// Sucrase's interop reads `__esModule`; spreading the namespace gives it a plain object.
const esm = (ns: object): object => ({ __esModule: true, ...ns });

// The factory takes the prebuilt bundle, so the full plotly.js source never enters the build.
const plotly = async (): Promise<object> => {
  const [factory, lib] = await Promise.all([
    import("react-plotly.js/factory"),
    import("plotly.js-dist-min"),
  ]);
  return esm({ default: factory.default(lib.default) });
};

export const MODULES: ModuleTable = {
  react: () => import("react").then(esm),
  "react/jsx-runtime": () => import("react/jsx-runtime").then(esm),
  "@quarry/hooks": () => import("./hooks").then(esm),
  "@quarry/perspective": () => import("./perspective").then(esm),
  "@quarry/highcharts": () => import("./libs/HighchartsReact").then(esm),
  "@/components/ui/button": () => import("@/components/ui/button").then(esm),
  "@/components/ui/badge": () => import("@/components/ui/badge").then(esm),
  "@/components/ui/input": () => import("@/components/ui/input").then(esm),
  "@/components/ui/select": () => import("@/components/ui/select").then(esm),
  "@/components/ui/separator": () =>
    import("@/components/ui/separator").then(esm),
  "@/components/ui/tabs": () => import("@/components/ui/tabs").then(esm),
  "@/components/ui/tooltip": () => import("@/components/ui/tooltip").then(esm),
  "@/components/ui/textarea": () =>
    import("@/components/ui/textarea").then(esm),
  "@/components/ui/scroll-area": () =>
    import("@/components/ui/scroll-area").then(esm),
  "ag-grid-react": () => import("ag-grid-react").then(esm),
  "ag-grid-community": () => import("ag-grid-community").then(esm),
  "lightweight-charts": () => import("lightweight-charts").then(esm),
  "react-plotly.js": plotly,
  "echarts-for-react": () => import("echarts-for-react").then(esm),
  echarts: () => import("echarts").then(esm),
  recharts: () => import("recharts").then(esm),
  "@tanstack/react-table": () => import("@tanstack/react-table").then(esm),
  d3: () => import("d3").then(esm),
  "highcharts/highstock": loadHighstock,
  scichart: loadScichart,
};
