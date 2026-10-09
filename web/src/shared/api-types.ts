import type { Json, JsonObject } from "./json";

export interface Column {
  name: string;
  dtype: string;
}

export interface Filter {
  col: string;
  op:
    | "eq"
    | "ne"
    | "lt"
    | "le"
    | "gt"
    | "ge"
    | "in"
    | "not_in"
    | "between"
    | "contains"
    | "starts_with"
    | "is_null"
    | "not_null";
  value?: Json;
}

export interface Agg {
  col: string;
  fn:
    | "sum"
    | "mean"
    | "min"
    | "max"
    | "count"
    | "median"
    | "std"
    | "first"
    | "last";
  alias?: string;
}

export interface Pivot {
  index: string[];
  columns: string;
  values: string;
  agg: Agg["fn"];
}

export interface Sort {
  col: string;
  desc?: boolean;
}

export interface QuerySpec {
  dataset: string;
  select?: string[];
  filters?: Filter[];
  group_by?: string[];
  aggs?: Agg[];
  pivot?: Pivot;
  sort?: Sort[];
  limit?: number;
  offset?: number;
  format?: "json" | "arrow";
}

export type Row = { [column: string]: Json };

export interface QueryResult {
  schema: Column[];
  rows: Row[] | null;
  arrow_base64: string | null;
  row_count: number;
  truncated: boolean;
}

export interface DatasetMeta {
  name: string;
  backing: "polars" | "polars_lazy" | "duckdb";
  schema: Column[];
  rows: number | null;
  preview: Row[];
  error: string | null;
}

export interface ExecError {
  type: string;
  message: string;
  traceback: string;
}

export interface Snapshot {
  ts: string;
  state: JsonObject;
  queries: JsonObject[];
}

export interface View {
  component_id: string;
  content_hash: string;
  source: string;
  initial_state: JsonObject;
  datasets: string[];
  snapshots: Snapshot[];
}

export type StepStatus = "running" | "ok" | "error" | "interrupted";

export interface Step {
  id: string;
  index: number;
  kind: "prompt" | "manual" | "load" | "recall";
  prompt: string | null;
  code: string;
  status: StepStatus;
  error: ExecError | null;
  note: string;
  stdout_tail: string;
  stderr_tail: string;
  reads: string[];
  writes: string[];
  defines: string[];
  datasets: DatasetMeta[];
  view: View | null;
  created_at: string;
  duration_ms: number;
}

export interface SessionMeta {
  id: string;
  title: string;
  created_at: string;
  provider: { name: string; model: string };
}

export interface Session {
  meta: SessionMeta;
  steps: Step[];
}

export interface KernelStatus {
  status: "starting" | "idle" | "running" | "dead";
  pid: number | null;
}

export interface SessionStatus {
  session_id: string;
  running_step: string | null;
  kernel: KernelStatus;
  last_error: string | null;
}

export interface RepairRequest {
  step_id: string;
  error: string;
}

export interface StepRequest {
  prompt: string;
  repair?: RepairRequest;
}

export interface ReplayReport {
  replayed: number;
  failed_step: number | null;
  error: string | null;
}
