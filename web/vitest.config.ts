import path from "node:path";
import { defineConfig } from "vitest/config";

// The naive-datetime tests need a non-UTC zone, or reading them as local time would pass.
process.env.TZ = "America/New_York";

const root = import.meta.dirname;

export default defineConfig({
  resolve: {
    alias: [
      // Built-ins live outside web/, so bare imports from them need an explicit home.
      {
        find: /^(react|ag-grid-react|ag-grid-community|lightweight-charts|@tanstack\/react-table)(\/.*)?$/,
        replacement: `${path.resolve(root, "node_modules")}/$1$2`,
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
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
