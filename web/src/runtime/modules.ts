import type { ModuleTable } from "./loader";

// Sucrase's interop reads `__esModule`; spreading the namespace gives it a plain object.
const esm = (ns: object): object => ({ __esModule: true, ...ns });

export const MODULES: ModuleTable = {
  react: () => import("react").then(esm),
  "react/jsx-runtime": () => import("react/jsx-runtime").then(esm),
  "@quarry/hooks": () => import("./hooks").then(esm),
  "@quarry/perspective": () => import("./perspective").then(esm),
  "@/components/ui/button": () => import("@/components/ui/button").then(esm),
  "@/components/ui/badge": () => import("@/components/ui/badge").then(esm),
  "@/components/ui/input": () => import("@/components/ui/input").then(esm),
  "@/components/ui/select": () => import("@/components/ui/select").then(esm),
  "@/components/ui/separator": () =>
    import("@/components/ui/separator").then(esm),
  "@/components/ui/tabs": () => import("@/components/ui/tabs").then(esm),
  "@/components/ui/tooltip": () => import("@/components/ui/tooltip").then(esm),
  "@/components/ui/textarea": () =>
    import("@/components/ui/textarea").then(esm),
  "@/components/ui/scroll-area": () =>
    import("@/components/ui/scroll-area").then(esm),
  "ag-grid-react": () => import("ag-grid-react").then(esm),
  "ag-grid-community": () => import("ag-grid-community").then(esm),
  "lightweight-charts": () => import("lightweight-charts").then(esm),
};
