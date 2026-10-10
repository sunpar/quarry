import {
  useCallback,
  useLayoutEffect,
  useMemo,
  useSyncExternalStore,
} from "react";
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
      arrow: ArrayBuffer | null;
    }
  | { status: "error"; message: string };

export function useQuery(spec: QuerySpec): QueryHookResult {
  const { bridge, cache } = useRuntime();
  const key = JSON.stringify(spec);
  const state = useSyncExternalStore(cache.subscribe.bind(cache), () =>
    cache.ensureQuery(JSON.parse(key) as QuerySpec),
  );
  // Snapshots report the specs mounted hooks hold, not every spec a render asked for.
  useLayoutEffect(() => {
    bridge.retain(key, JSON.parse(key) as QuerySpec);
    return () => bridge.release(key);
  }, [bridge, key]);
  return useMemo<QueryHookResult>(() => {
    if (state.status !== "success") return state;
    const { result } = state;
    return {
      status: "success",
      rows: result.rows ?? [],
      schema: result.schema,
      rowCount: result.row_count,
      truncated: result.truncated,
      arrow: state.arrow,
    };
  }, [state]);
}

export function useViewState<T extends Json>(
  key: string,
  initial: T,
): [T, (next: T) => void] {
  const { store } = useRuntime();
  const state = useSyncExternalStore(store.subscribe.bind(store), () =>
    store.current(),
  );
  const value = Object.hasOwn(state, key) ? (state[key] as T) : initial;
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
