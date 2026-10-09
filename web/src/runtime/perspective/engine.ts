import perspective from "@finos/perspective";
import type { Client } from "@finos/perspective";
import perspectiveViewer from "@finos/perspective-viewer";
import "@finos/perspective-viewer-datagrid";
import "@finos/perspective-viewer-d3fc";
import serverWasm from "@finos/perspective/dist/wasm/perspective-server.wasm?url";
import clientWasm from "@finos/perspective-viewer/dist/wasm/perspective-viewer.wasm?url";
import workerSource from "@finos/perspective/dist/cdn/perspective-server.worker.js?raw";

let engine: Promise<Client> | null = null;

/** One engine worker per runtime frame; the wasm files are fetched from the bundle. */
export function ensureEngine(): Promise<Client> {
  engine ??= (async () => {
    await Promise.all([
      perspective.init_server(fetch(serverWasm)),
      perspectiveViewer.init_client(fetch(clientWasm)),
    ]);
    // Perspective's own worker is a module worker, which Chromium refuses from a
    // blob: URL in an opaque-origin frame; the same script runs as a classic one.
    const url = URL.createObjectURL(
      new Blob([workerSource], { type: "text/javascript" }),
    );
    return perspective.worker(Promise.resolve(new Worker(url)));
  })();
  return engine;
}
