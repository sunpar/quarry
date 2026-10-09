export const RUNTIME_LIBRARIES = ["ag-grid", "lightweight-charts"] as const;
export type RuntimeLibrary = (typeof RUNTIME_LIBRARIES)[number];
