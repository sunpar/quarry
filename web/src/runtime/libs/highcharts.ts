import { licensed, notEnabled } from "./registry";

declare global {
  interface Window {
    Highcharts?: object;
  }
}

let loading: Promise<object> | null = null;

/** Highstock is a classic UMD script; a module import would pull hundreds of ESM files. */
export function loadHighstock(): Promise<object> {
  const lib = licensed("highcharts");
  if (lib === null) return Promise.reject(notEnabled("highcharts"));
  loading ??= new Promise<object>((resolve, reject) => {
    const script = document.createElement("script");
    script.src = lib.entry;
    // A failed load is forgotten, so the next view that imports Highcharts tries again.
    const fail = (error: Error) => {
      script.remove();
      loading = null;
      reject(error);
    };
    script.onload = () => {
      const global = window.Highcharts;
      if (global === undefined)
        fail(new Error(`${lib.entry} loaded but defined no Highcharts global`));
      else resolve({ __esModule: true, default: global, ...global });
    };
    script.onerror = () => fail(new Error(`could not load ${lib.entry}`));
    document.head.append(script);
  });
  return loading;
}
