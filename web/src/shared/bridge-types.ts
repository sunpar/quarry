import type { Column, QueryResult, QuerySpec } from "./api-types";
import type { JsonObject } from "./json";

export type HostToRuntime =
  | {
      type: "mount";
      viewId: string;
      source: string;
      initialState: JsonObject;
      datasets: string[];
    }
  | { type: "restore"; viewId: string; state: JsonObject }
  | {
      type: "queryResult";
      viewId: string;
      id: string;
      ok: true;
      result: QueryResult;
    }
  | {
      type: "queryResult";
      viewId: string;
      id: string;
      ok: false;
      error: string;
    }
  | {
      type: "schemaResult";
      viewId: string;
      id: string;
      ok: true;
      schema: Column[];
    }
  | {
      type: "schemaResult";
      viewId: string;
      id: string;
      ok: false;
      error: string;
    };

export type RuntimeToHost =
  | { type: "ready" }
  | { type: "query"; viewId: string; id: string; spec: QuerySpec }
  | { type: "schema"; viewId: string; id: string; dataset: string }
  | {
      type: "stateChanged";
      viewId: string;
      state: JsonObject;
      queries: QuerySpec[];
    }
  | { type: "error"; viewId: string; message: string; stack?: string };

export function isRuntimeMessage(data: unknown): data is RuntimeToHost {
  return typeof data === "object" && data !== null && "type" in data;
}

export function isHostMessage(data: unknown): data is HostToRuntime {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    "viewId" in data
  );
}
