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
  // Keys whose answer predates a refresh: shown until the refetch lands.
  private stale = new Set<string>();

  constructor(private readonly bridge: RuntimeBridge) {}

  /** Refetch everything on next use, keeping current answers on screen meanwhile. */
  refresh(): void {
    this.stale = new Set([
      ...[...this.queries.keys()].map((k) => `q:${k}`),
      ...[...this.schemas.keys()].map((k) => `s:${k}`),
    ]);
    for (const listener of this.listeners) listener();
  }

  ensureQuery(spec: QuerySpec): QueryState {
    this.bridge.useQuery(spec);
    const key = JSON.stringify(spec);
    const known = this.queries.get(key);
    if (known !== undefined && !this.stale.delete(`q:${key}`)) return known;
    if (known === undefined) this.queries.set(key, LOADING);
    this.bridge.query(spec).then(
      (result) => this.put(this.queries, key, { status: "success", result }),
      (error: unknown) =>
        this.put(this.queries, key, {
          status: "error",
          message: error instanceof Error ? error.message : String(error),
        }),
    );
    return known ?? LOADING;
  }

  ensureSchema(dataset: string): SchemaState {
    const known = this.schemas.get(dataset);
    if (known !== undefined && !this.stale.delete(`s:${dataset}`)) return known;
    if (known === undefined) this.schemas.set(dataset, SCHEMA_LOADING);
    this.bridge.schema(dataset).then(
      (schema) => this.put(this.schemas, dataset, { status: "done", schema }),
      () => this.put(this.schemas, dataset, { status: "done", schema: null }),
    );
    return known ?? SCHEMA_LOADING;
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
