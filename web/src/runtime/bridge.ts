import type { Column, QueryResult, QuerySpec } from "@/shared/api-types";
import type { HostToRuntime, RuntimeToHost } from "@/shared/bridge-types";
import type { JsonObject } from "@/shared/json";

interface Pending {
  resolve: (value: unknown) => void;
  reject: (error: Error) => void;
}

export class RuntimeBridge {
  private readonly pending = new Map<string, Pending>();
  // The specs mounted `useQuery` hooks hold, keyed by spec and counted: two hooks may share one.
  private readonly held = new Map<string, { spec: QuerySpec; count: number }>();
  private reported = "";
  private counter = 0;

  constructor(
    readonly viewId: string,
    private readonly post: (message: RuntimeToHost) => void,
    /** The held specs now differ from the last `stateChanged`. */
    private readonly onQueriesChanged: () => void = () => undefined,
  ) {}

  ready(): void {
    this.post({ type: "ready" });
  }

  retain(key: string, spec: QuerySpec): void {
    const held = this.held.get(key);
    if (held === undefined) this.held.set(key, { spec, count: 1 });
    else held.count += 1;
    this.checkHeld();
  }

  release(key: string): void {
    const held = this.held.get(key);
    if (held === undefined) return;
    held.count -= 1;
    if (held.count === 0) this.held.delete(key);
    this.checkHeld();
  }

  query(spec: QuerySpec): Promise<QueryResult> {
    const id = this.nextId();
    this.post({ type: "query", viewId: this.viewId, id, spec });
    return this.wait<QueryResult>(id);
  }

  schema(dataset: string): Promise<Column[]> {
    const id = this.nextId();
    this.post({ type: "schema", viewId: this.viewId, id, dataset });
    return this.wait<Column[]>(id);
  }

  stateChanged(state: JsonObject): void {
    const queries = [...this.held.values()].map((h) => h.spec);
    this.reported = this.heldKeys();
    this.post({ type: "stateChanged", viewId: this.viewId, state, queries });
  }

  error(message: string, stack?: string): void {
    this.post({ type: "error", viewId: this.viewId, message, stack });
  }

  /** Routes a host message; `onControl` receives mount and restore. */
  handle(message: HostToRuntime, onControl?: (m: HostToRuntime) => void): void {
    if (message.viewId !== this.viewId) return;
    if (message.type === "queryResult" || message.type === "schemaResult") {
      const pending = this.pending.get(message.id);
      if (pending === undefined) return;
      this.pending.delete(message.id);
      if (message.ok)
        pending.resolve(
          message.type === "queryResult" ? message.result : message.schema,
        );
      else pending.reject(new Error(message.error));
      return;
    }
    onControl?.(message);
  }

  private checkHeld(): void {
    if (this.heldKeys() !== this.reported) this.onQueriesChanged();
  }

  // JSON keys never hold a raw newline, so the sorted join names the set.
  private heldKeys(): string {
    return [...this.held.keys()].sort().join("\n");
  }

  private nextId(): string {
    this.counter += 1;
    return `${this.viewId}:${this.counter}`;
  }

  private wait<T>(id: string): Promise<T> {
    return new Promise<T>((resolve, reject) => {
      this.pending.set(id, { resolve: (v) => resolve(v as T), reject });
    });
  }
}
