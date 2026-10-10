import { describe, expect, it } from "vitest";
import { RUNTIME_LIBRARIES } from "./libraries";
import { MODULES } from "./modules";

describe("runtime module table", () => {
  it("resolves every import the contract and the library guide name", () => {
    for (const name of [
      "react",
      "@quarry/hooks",
      "@/components/ui/textarea",
      "@/components/ui/scroll-area",
      "@quarry/perspective",
      "@quarry/highcharts",
      "ag-grid-react",
      "ag-grid-community",
      "lightweight-charts",
      "react-plotly.js",
      "echarts-for-react",
      "echarts",
      "recharts",
      "@tanstack/react-table",
      "d3",
      "highcharts/highstock",
      "scichart",
    ])
      expect(MODULES[name], name).toBeTypeOf("function");
  });

  it("advertises every library id the guide has a section for", () => {
    expect([...RUNTIME_LIBRARIES].sort()).toEqual(
      [
        "ag-grid",
        "d3",
        "echarts",
        "highcharts",
        "lightweight-charts",
        "perspective",
        "plotly",
        "recharts",
        "scichart",
        "tanstack-table",
      ].sort(),
    );
  });
});
