import type { Json, JsonObject } from "@/shared/json";

export class ViewStateStore {
  private values: Map<string, Json>;
  private readonly listeners = new Set<() => void>();
  private timer: ReturnType<typeof setTimeout> | null = null;
  private cached: JsonObject;

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
    this.notify();
    if (this.timer !== null) clearTimeout(this.timer);
    this.timer = setTimeout(() => {
      this.timer = null;
      this.onChange(this.cached);
    }, this.debounceMs);
  }

  replace(state: JsonObject): void {
    this.values = new Map(Object.entries(state));
    this.cached = { ...state };
    this.notify();
  }

  /** Report the current state now, with the queries issued so far. */
  flush(): void {
    if (this.timer !== null) {
      clearTimeout(this.timer);
      this.timer = null;
    }
    this.onChange(this.cached);
  }

  /** Stable reference between changes, for useSyncExternalStore. */
  current(): JsonObject {
    return this.cached;
  }

  subscribe(listener: () => void): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  private snapshot(): JsonObject {
    return Object.fromEntries(this.values);
  }

  private notify(): void {
    for (const listener of this.listeners) listener();
  }
}
