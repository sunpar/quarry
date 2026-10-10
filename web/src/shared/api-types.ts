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
  queries: QuerySpec[];
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
  replay_needed: boolean;
}

export interface SessionStatus {
  session_id: string;
  running_step: string | null;
  busy: boolean;
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

export type SaveMode = "live" | "pinned";

export interface CanvasCard {
  view: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

export interface ProjectMeta {
  slug: string;
  name: string;
  description: string;
  created_at: string;
  updated_at: string;
  canvas: CanvasCard[];
}

export interface SavedDatasetMeta {
  name: string;
  description: string;
  backing: DatasetMeta["backing"];
  schema: Column[];
  rows: number | null;
  mode: SaveMode;
  saved_at: string;
  source_session: string;
  source_step: string;
  validated: boolean;
  validation_error: string | null;
}

export interface SavedViewMeta {
  name: string;
  description: string;
  datasets: string[];
  component_id: string;
  saved_at: string;
  source_session: string;
  source_step: string;
}

export interface Project {
  meta: ProjectMeta;
  datasets: SavedDatasetMeta[];
  views: SavedViewMeta[];
}

export interface SaveDatasetRequest {
  session_id: string;
  dataset: string;
  mode: SaveMode;
  description?: string;
}

export interface SaveViewRequest {
  session_id: string;
  step_id: string;
  name: string;
  description?: string;
  mode: SaveMode;
}

export interface RecallRequest {
  project: string;
  kind: "dataset" | "view";
  name: string;
}

export interface SavedView {
  meta: SavedViewMeta;
  source: string;
  state: JsonObject;
  queries: QuerySpec[];
}

export interface LibraryStatus {
  id: "highcharts" | "scichart";
  enabled: boolean;
  reason: string | null;
  license: string | null;
  entry: string | null;
}
