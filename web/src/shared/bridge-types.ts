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
  /** Kernel data may have changed: refetch, keeping what is shown until answers arrive. */
  | { type: "refresh"; viewId: string }
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

const isRecord = (v: unknown): v is Record<string, unknown> =>
  typeof v === "object" && v !== null && !Array.isArray(v);
const isString = (v: unknown): v is string => typeof v === "string";

/** Generated code can post to the host directly, so every field is checked, not just `type`. */
export function isRuntimeMessage(data: unknown): data is RuntimeToHost {
  if (!isRecord(data)) return false;
  switch (data["type"]) {
    case "ready":
      return true;
    case "query":
      return (
        isString(data["viewId"]) &&
        isString(data["id"]) &&
        isRecord(data["spec"])
      );
    case "schema":
      return (
        isString(data["viewId"]) &&
        isString(data["id"]) &&
        isString(data["dataset"])
      );
    case "stateChanged":
      return (
        isString(data["viewId"]) &&
        isRecord(data["state"]) &&
        Array.isArray(data["queries"]) &&
        data["queries"].every(isRecord)
      );
    case "error":
      return (
        isString(data["viewId"]) &&
        isString(data["message"]) &&
        (data["stack"] === undefined || isString(data["stack"]))
      );
    default:
      return false;
  }
}

export function isHostMessage(data: unknown): data is HostToRuntime {
  return (
    typeof data === "object" &&
    data !== null &&
    "type" in data &&
    "viewId" in data
  );
}
