import { licensed, notEnabled } from "./registry";

interface SciChartLike {
  SciChartSurface: {
    configure(config: { wasmUrl: string }): void;
    setRuntimeLicenseKey(key: string): void;
  };
}

let loading: Promise<object> | null = null;

/** SciChart's single-file ES module, served from the researcher's install under /libs/. */
export function loadScichart(): Promise<object> {
  const lib = licensed("scichart");
  if (lib === null) return Promise.reject(notEnabled("scichart"));
  loading ??= import(/* @vite-ignore */ lib.entry)
    .then((mod: unknown) => {
      const sc = mod as SciChartLike;
      const base = lib.entry.slice(0, lib.entry.lastIndexOf("/") + 1);
      sc.SciChartSurface.configure({ wasmUrl: `${base}_wasm/scichart.wasm` });
      if (lib.license !== null)
        sc.SciChartSurface.setRuntimeLicenseKey(lib.license);
      return { __esModule: true, ...(mod as object) };
    })
    .catch((error: unknown) => {
      // Forgotten, as a failed Highcharts load is, so a later mount retries.
      loading = null;
      throw error;
    });
  return loading;
}
