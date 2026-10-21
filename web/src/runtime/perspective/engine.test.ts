import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const server = vi.hoisted(() => ({ init_server: vi.fn(), worker: vi.fn() }));
const client = vi.hoisted(() => ({ init_client: vi.fn() }));
vi.mock("@finos/perspective", () => ({ default: server }));
vi.mock("@finos/perspective-viewer", () => ({ default: client }));
// Both plugins define custom elements on import, which the node environment lacks.
vi.mock("@finos/perspective-viewer-datagrid", () => ({}));
vi.mock("@finos/perspective-viewer-d3fc", () => ({}));

const terminate = vi.fn();

// The engine is cached at module level, so each test imports a fresh copy.
let ensureEngine: () => Promise<unknown>;

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  vi.stubGlobal("fetch", vi.fn());
  vi.stubGlobal(
    "Worker",
    class {
      terminate = terminate;
    },
  );
  client.init_client.mockResolvedValue(undefined);
  server.worker.mockResolvedValue("engine");
  ({ ensureEngine } = await import("./engine"));
});

afterEach(() => vi.unstubAllGlobals());

describe("ensureEngine", () => {
  it("starts one engine per frame, shared by pivots that mount together", async () => {
    const first = ensureEngine();
    expect(ensureEngine()).toBe(first);
    await expect(first).resolves.toBe("engine");
    await ensureEngine();
    expect(server.worker).toHaveBeenCalledTimes(1);
  });

  it("forgets a failed viewer start so a later pivot retries", async () => {
    client.init_client.mockRejectedValueOnce(new Error("no wasm"));
    await expect(ensureEngine()).rejects.toThrow("no wasm");
    await expect(ensureEngine()).resolves.toBe("engine");
    expect(client.init_client).toHaveBeenCalledTimes(2);
  });

  it("retries a failed worker without starting the viewer again", async () => {
    server.worker.mockRejectedValueOnce(new Error("no worker"));
    await expect(ensureEngine()).rejects.toThrow("no worker");
    expect(terminate).toHaveBeenCalledTimes(1);
    await expect(ensureEngine()).resolves.toBe("engine");
    expect(server.init_server).toHaveBeenCalledTimes(2);
    expect(server.worker).toHaveBeenCalledTimes(2);
    expect(client.init_client).toHaveBeenCalledTimes(1);
  });
});
