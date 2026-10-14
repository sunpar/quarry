import path from "node:path";
import { defineConfig } from "vitest/config";

// The naive-datetime tests need a non-UTC zone, or reading them as local time would pass.
process.env.TZ = "America/New_York";

const root = import.meta.dirname;
const nodeTests = [
  "src/shared/base64.test.ts",
  "src/host/api/auth.test.ts",
  "src/host/api/client.test.ts",
  "src/host/api/download.test.ts",
  "src/host/bridge/SharedStateHub.test.ts",
  "src/runtime/bridge.test.ts",
  "src/runtime/loader.test.ts",
  "src/runtime/state.test.ts",
  "src/runtime/perspective/filters.test.ts",
  "src/runtime/perspective/toSpec.test.ts",
  "src/runtime/libs/registry.test.ts",
  "src/runtime/libs/scichart.test.ts",
];

export default defineConfig({
  cacheDir: ".cache/vitest",
  resolve: {
    alias: [
      // Built-ins live outside web/, so bare imports from them need an explicit home.
      {
        find: /^(react|ag-grid-react|ag-grid-community|lightweight-charts|@tanstack\/react-table|recharts|echarts-for-react)(\/.*)?$/,
        replacement: `${path.resolve(root, "node_modules")}/$1$2`,
      },
      // Exact: the app imports `react-plotly.js/factory` through the package exports map.
      {
        find: /^react-plotly\.js$/,
        replacement: path.resolve(root, "node_modules/react-plotly.js"),
      },
      { find: "@", replacement: path.resolve(root, "./src") },
      {
        find: "@quarry/hooks",
        replacement: path.resolve(root, "./src/runtime/hooks.ts"),
      },
      {
        find: "@quarry/perspective",
        replacement: path.resolve(root, "./src/runtime/perspective/index.ts"),
      },
      {
        find: "@quarry/highcharts",
        replacement: path.resolve(
          root,
          "./src/runtime/libs/HighchartsReact.tsx",
        ),
      },
      {
        find: "@builtin",
        replacement: path.resolve(root, "../src/quarry/components/builtin"),
      },
    ],
  },
  // As in vite.config.ts: built-ins are read as `?raw` source from outside web/.
  server: { fs: { allow: [path.resolve(root, "..")] } },
  test: {
    maxWorkers: 2,
    projects: [
      {
        extends: true,
        test: { name: "node", environment: "node", include: nodeTests },
      },
      {
        extends: true,
        test: {
          name: "dom",
          environment: "jsdom",
          // Reuse jsdom's import while keeping a fresh window and VM for each file.
          pool: "vmThreads",
          setupFiles: ["./src/test/setup.ts"],
          include: ["src/**/*.test.{ts,tsx}"],
          exclude: nodeTests,
        },
      },
    ],
  },
});
