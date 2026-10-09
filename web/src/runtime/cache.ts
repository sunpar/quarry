import type { Column, QueryResult, QuerySpec } from "@/shared/api-types";
import type { RuntimeBridge } from "./bridge";

export type QueryState =
  | { status: "loading" }
  | { status: "success"; result: QueryResult }
  | { status: "error"; message: string };

export type SchemaState =
  { status: "loading" } | { status: "done"; schema: Column[] | null };

const LOADING: QueryState = { status: "loading" };
const SCHEMA_LOADING: SchemaState = { status: "loading" };

/** Idempotent per-view request cache; `ensure*` may be called during render. */
export class RequestCache {
  private readonly queries = new Map<string, QueryState>();
  private readonly schemas = new Map<string, SchemaState>();
  private readonly listeners = new Set<() => void>();

  constructor(private readonly bridge: RuntimeBridge) {}

  ensureQuery(spec: QuerySpec): QueryState {
    const key = JSON.stringify(spec);
    const known = this.queries.get(key);
    if (known !== undefined) return known;
    this.queries.set(key, LOADING);
    this.bridge.query(spec).then(
      (result) => this.put(this.queries, key, { status: "success", result }),
      (error: unknown) =>
        this.put(this.queries, key, {
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        }),
    );
    return LOADING;
  }

  ensureSchema(dataset: string): SchemaState {
    const known = this.schemas.get(dataset);
    if (known !== undefined) return known;
    this.schemas.set(dataset, SCHEMA_LOADING);
    this.bridge.schema(dataset).then(
      (schema) => this.put(this.schemas, dataset, { status: "done", schema }),
      () => this.put(this.schemas, dataset, { status: "done", schema: null }),
    );
    return SCHEMA_LOADING;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private put<T>(map: Map<string, T>, key: string, value: T): void {
    map.set(key, value);
    for (const listener of this.listeners) listener();
  }
}
