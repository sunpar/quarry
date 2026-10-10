import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { LicensedLibrary } from "@/shared/library-types";

const HIGHCHARTS: LicensedLibrary = {
  id: "highcharts",
  entry: "/libs/highcharts/highstock.js",
  license: null,
};

// The loader caches its script at module level, so each test imports a fresh copy.
let loadHighstock: () => Promise<object>;
let setLicensed: (list: LicensedLibrary[]) => void;

beforeEach(async () => {
  vi.resetModules();
  ({ loadHighstock } = await import("./highcharts"));
  ({ setLicensed } = await import("./registry"));
});

afterEach(() => {
  document.head.querySelectorAll("script").forEach((s) => s.remove());
  delete window.Highcharts;
});

const scripts = () =>
  document.querySelectorAll<HTMLScriptElement>(
    `script[src="${HIGHCHARTS.entry}"]`,
  );

describe("loadHighstock", () => {
  it("refuses when the library is not enabled", async () => {
    await expect(loadHighstock()).rejects.toThrow(/highcharts is not enabled/);
    expect(scripts()).toHaveLength(0);
  });

  it("inserts the entry script once and resolves to the global", async () => {
    setLicensed([HIGHCHARTS]);
    const pending = loadHighstock();
    expect(scripts()).toHaveLength(1);
    window.Highcharts = { stockChart: () => ({}) };
    scripts()[0]?.dispatchEvent(new Event("load"));
    const mod = (await pending) as { default: { stockChart: unknown } };
    expect(typeof mod.default.stockChart).toBe("function");
    await loadHighstock();
    expect(scripts()).toHaveLength(1);
  });

  it("forgets a failed load so a later mount retries", async () => {
    setLicensed([HIGHCHARTS]);
    const failed = loadHighstock();
    scripts()[0]?.dispatchEvent(new Event("error"));
    await expect(failed).rejects.toThrow(/could not load/);
    expect(scripts()).toHaveLength(0);
    const retried = loadHighstock();
    expect(scripts()).toHaveLength(1);
    window.Highcharts = { stockChart: () => ({}) };
    scripts()[0]?.dispatchEvent(new Event("load"));
    await expect(retried).resolves.toHaveProperty("default", window.Highcharts);
  });
});
