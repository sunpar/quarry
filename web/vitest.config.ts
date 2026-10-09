import path from "node:path";
import { defineConfig } from "vitest/config";

const root = import.meta.dirname;

export default defineConfig({
  resolve: {
    alias: [
      // Built-ins live outside web/, so bare imports from them need an explicit home.
      {
        find: /^(react|ag-grid-react|ag-grid-community|lightweight-charts)(\/.*)?$/,
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
        find: "@builtin",
        replacement: path.resolve(root, "../src/quarry/components/builtin"),
      },
    ],
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
