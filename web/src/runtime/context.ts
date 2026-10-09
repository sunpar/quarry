import { createContext, useContext } from "react";
import type { RuntimeBridge } from "./bridge";
import type { RequestCache } from "./cache";
import type { ViewStateStore } from "./state";

export interface RuntimeServices {
  bridge: RuntimeBridge;
  store: ViewStateStore;
  cache: RequestCache;
}

const RuntimeContext = createContext<RuntimeServices | null>(null);

export const RuntimeProvider = RuntimeContext.Provider;

export function useRuntime(): RuntimeServices {
  const services = useContext(RuntimeContext);
  if (services === null)
    throw new Error("hooks from @quarry/hooks only work inside a view");
  return services;
}
