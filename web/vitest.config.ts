import path from "node:path";
import { defineConfig } from "vitest/config";

const root = import.meta.dirname;

export default defineConfig({
  resolve: {
    alias: {
      "@": path.resolve(root, "./src"),
      "@quarry/hooks": path.resolve(root, "./src/runtime/hooks.ts"),
      "@builtin": path.resolve(root, "../src/quarry/components/builtin"),
    },
  },
  test: {
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.{ts,tsx}"],
  },
});
