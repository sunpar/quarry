import perspective from "@finos/perspective";
import type { Client } from "@finos/perspective";
import perspectiveViewer from "@finos/perspective-viewer";
import "@finos/perspective-viewer-datagrid";
import "@finos/perspective-viewer-d3fc";
import serverWasm from "@finos/perspective/dist/wasm/perspective-server.wasm?url";
import clientWasm from "@finos/perspective-viewer/dist/wasm/perspective-viewer.wasm?url";
import workerSource from "@finos/perspective/dist/cdn/perspective-server.worker.js?raw";

let viewer: Promise<void> | null = null;
let engine: Promise<Client> | null = null;

/** One engine worker per runtime frame; the wasm files are fetched from the bundle. */
export function ensureEngine(): Promise<Client> {
  engine ??= (async () => {
    perspective.init_server(fetch(serverWasm));
    await initViewer();
    // Perspective's own worker is a module worker, which Chromium refuses from a
    // blob: URL in an opaque-origin frame; the same script runs as a classic one.
    const url = URL.createObjectURL(
      new Blob([workerSource], { type: "text/javascript" }),
    );
    const worker = new Worker(url);
    // A failed start would otherwise leave its worker running beside the retry's.
    return perspective
      .worker(Promise.resolve(worker))
      .catch((error: unknown) => {
        worker.terminate();
        throw error;
      });
  })().catch((error: unknown) => {
    // Forgotten, as a failed SciChart load is, so a later pivot retries.
    engine = null;
    throw error;
  });
  return engine;
}

/** The viewer's wasm defines its custom elements, so a retry reuses a started one. */
function initViewer(): Promise<void> {
  viewer ??= perspectiveViewer
    .init_client(fetch(clientWasm))
    .catch((error: unknown) => {
      viewer = null;
      throw error;
    });
  return viewer;
}
