import { beforeEach, describe, expect, it, vi } from "vitest";
import type { LicensedLibrary } from "@/shared/library-types";

const SCICHART: LicensedLibrary = {
  id: "scichart",
  entry: "/libs/scichart/index.min.mjs",
  license: "k",
};

const surface = vi.hoisted(() => ({
  configure: vi.fn(),
  setRuntimeLicenseKey: vi.fn(),
}));
// Stands in for the researcher's install, which the server serves at this path.
vi.mock("/libs/scichart/index.min.mjs", () => ({ SciChartSurface: surface }));

// The loader caches its import at module level, so each test imports a fresh copy.
let loadScichart: () => Promise<object>;
let setLicensed: (list: LicensedLibrary[]) => void;

beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  ({ loadScichart } = await import("./scichart"));
  ({ setLicensed } = await import("./registry"));
});

describe("loadScichart", () => {
  it("refuses when the library is not enabled", async () => {
    await expect(loadScichart()).rejects.toThrow(/scichart is not enabled/);
  });

  it("points the wasm at the install and applies the license once", async () => {
    setLicensed([SCICHART]);
    const mod = (await loadScichart()) as { SciChartSurface: unknown };
    expect(mod.SciChartSurface).toBe(surface);
    expect(surface.configure).toHaveBeenCalledWith({
      wasmUrl: "/libs/scichart/_wasm/scichart.wasm",
    });
    expect(surface.setRuntimeLicenseKey).toHaveBeenCalledWith("k");
    await loadScichart();
    expect(surface.configure).toHaveBeenCalledTimes(1);
  });

  it("forgets a failed load so a later mount retries", async () => {
    setLicensed([SCICHART]);
    surface.configure.mockImplementationOnce(() => {
      throw new Error("no wasm");
    });
    await expect(loadScichart()).rejects.toThrow("no wasm");
    await expect(loadScichart()).resolves.toHaveProperty(
      "SciChartSurface",
      surface,
    );
    expect(surface.configure).toHaveBeenCalledTimes(2);
  });
});
