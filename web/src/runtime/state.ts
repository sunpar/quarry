import type { Json, JsonObject } from "@/shared/json";

export class ViewStateStore {
  private values: Map<string, Json>;
  private readonly listeners = new Set<() => void>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private cached: JsonObject;
  // A restored state is a snapshot already on record, so the queries it brings are not news.
  private restored = false;

  constructor(
    initial: JsonObject,
    private readonly onChange: (state: JsonObject) => void,
    private readonly debounceMs: number,
  ) {
    this.values = new Map(Object.entries(initial));
    this.cached = { ...initial };
  }

  get(key: string): Json | undefined {
    return this.values.get(key);
  }

  set(key: string, value: Json): void {
    this.values.set(key, value);
    this.cached = this.snapshot();
    this.restored = false;
    this.notify();
    this.schedule();
  }

  replace(state: JsonObject): void {
    this.values = new Map(Object.entries(state));
    this.cached = { ...state };
    this.restored = true;
    this.notify();
  }

  /** The view's queries changed: report the state as a change does, unless it was restored. */
  queriesChanged(): void {
    if (!this.restored) this.schedule();
  }

  /** Stable reference between changes, for useSyncExternalStore. */
  current(): JsonObject {
    return this.cached;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private schedule(): void {
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.onChange(this.cached);
    }, this.debounceMs);
  }

  private snapshot(): JsonObject {
    return Object.fromEntries(this.values);
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}
