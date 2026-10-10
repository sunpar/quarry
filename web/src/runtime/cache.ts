import type { Column, QueryResult, QuerySpec } from "@/shared/api-types";
import { decodeBase64 } from "@/shared/base64";
import type { RuntimeBridge } from "./bridge";

export type QueryState =
  | { status: "loading" }
  | { status: "success"; result: QueryResult; arrow: ArrayBuffer | null }
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
  // The newest request per key; an older one answering late is discarded.
  private readonly latest = new Map<string, number>();
  private requests = 0;

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
    const key = JSON.stringify(spec);
    const known = this.queries.get(key);
    if (known !== undefined && !this.stale.delete(`q:${key}`)) return known;
    if (known === undefined) this.queries.set(key, LOADING);
    const ticket = this.ticket(`q:${key}`);
    this.bridge.query(spec).then(
      (result) =>
        this.settle(this.queries, key, `q:${key}`, ticket, {
          status: "success",
          result,
          // Decoded once per answer, so the buffer is stable across renders.
          arrow:
            result.arrow_base64 === null
              ? null
              : decodeBase64(result.arrow_base64),
        }),
      (error: unknown) =>
        this.settle(this.queries, key, `q:${key}`, ticket, {
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
    const ticket = this.ticket(`s:${dataset}`);
    this.bridge.schema(dataset).then(
      (schema) =>
        this.settle(this.schemas, dataset, `s:${dataset}`, ticket, {
          status: "done",
          schema,
        }),
      () =>
        this.settle(this.schemas, dataset, `s:${dataset}`, ticket, {
          status: "done",
          schema: null,
        }),
    );
    return known ?? SCHEMA_LOADING;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private ticket(slot: string): number {
    this.requests += 1;
    this.latest.set(slot, this.requests);
    return this.requests;
  }

  private settle<T>(
    map: Map<string, T>,
    key: string,
    slot: string,
    ticket: number,
    value: T,
  ): void {
    if (this.latest.get(slot) === ticket) this.put(map, key, value);
  }

  private put<T>(map: Map<string, T>, key: string, value: T): void {
    map.set(key, value);
    for (const listener of this.listeners) listener();
  }
}
