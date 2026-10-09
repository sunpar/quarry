export const RUNTIME_LIBRARIES = [
  "ag-grid",
  "lightweight-charts",
  "perspective",
] as const;
export type RuntimeLibrary = (typeof RUNTIME_LIBRARIES)[number];
