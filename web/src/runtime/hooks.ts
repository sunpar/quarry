import { useCallback, useSyncExternalStore } from "react";
import type { Column, QuerySpec, Row } from "@/shared/api-types";
import type { Json } from "@/shared/json";
import { useRuntime } from "./context";

export type QueryHookResult =
  | { status: "loading" }
  | {
      status: "success";
      rows: Row[];
      schema: Column[];
      rowCount: number;
      truncated: boolean;
    }
  | { status: "error"; message: string };

export function useQuery(spec: QuerySpec): QueryHookResult {
  const { cache } = useRuntime();
  const key = JSON.stringify(spec);
  const state = useSyncExternalStore(cache.subscribe.bind(cache), () =>
    cache.ensureQuery(JSON.parse(key) as QuerySpec),
  );
  if (state.status === "success") {
    const { result } = state;
    return {
      status: "success",
      rows: result.rows ?? [],
      schema: result.schema,
      rowCount: result.row_count,
      truncated: result.truncated,
    };
  }
  return state;
}

export function useViewState<T extends Json>(
  key: string,
  initial: T,
): [T, (next: T) => void] {
  const { store } = useRuntime();
  const state = useSyncExternalStore(store.subscribe.bind(store), () =>
    store.current(),
  );
  const value = key in state ? (state[key] as T) : initial;
  const set = useCallback((next: T) => store.set(key, next), [store, key]);
  return [value, set];
}

export function useDatasetSchema(name: string): Column[] | null {
  const { cache } = useRuntime();
  const state = useSyncExternalStore(cache.subscribe.bind(cache), () =>
    cache.ensureSchema(name),
  );
  return state.status === "done" ? state.schema : null;
}
