import { mkdirSync, writeFileSync } from "node:fs";
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, type Plugin } from "vite";
import { RUNTIME_LIBRARIES } from "./src/runtime/libraries.ts";

const root = import.meta.dirname;
const outDir = path.resolve(root, "../src/quarry/static");
const apiPort = process.env.QUARRY_PORT ?? "8765";

function runtimeManifest(): Plugin {
  return {
    name: "quarry-runtime-manifest",
    closeBundle() {
      mkdirSync(outDir, { recursive: true });
      writeFileSync(
        path.join(outDir, "runtime-manifest.json"),
        JSON.stringify({ libraries: RUNTIME_LIBRARIES }, null, 2),
      );
    },
  };
}

export default defineConfig({
  plugins: [react(), tailwindcss(), runtimeManifest()],
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
        find: "@builtin",
        replacement: path.resolve(root, "../src/quarry/components/builtin"),
      },
    ],
  },
  server: {
    fs: { allow: [path.resolve(root, "..")] },
    proxy: {
      "/sessions": `http://127.0.0.1:${apiPort}`,
      "/projects": `http://127.0.0.1:${apiPort}`,
      "/healthz": `http://127.0.0.1:${apiPort}`,
    },
  },
  build: {
    outDir,
    emptyOutDir: true,
    rollupOptions: {
      input: {
        index: path.resolve(root, "index.html"),
        runtime: path.resolve(root, "runtime.html"),
      },
    },
  },
});
