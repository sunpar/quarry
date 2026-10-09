import { createRoot, type Root } from "react-dom/client";
import type { HostToRuntime, RuntimeToHost } from "@/shared/bridge-types";
import { RuntimeBridge } from "./bridge";
import { RequestCache } from "./cache";
import { RuntimeProvider } from "./context";
import { ErrorBoundary } from "./ErrorBoundary";
import { loadComponent, type ModuleTable, type ViewComponent } from "./loader";
import { MODULES } from "./modules";
import { ViewStateStore } from "./state";

export interface Runtime {
  handle(message: HostToRuntime): void;
  /** Forward an error thrown outside React (a timer, a promise) to the mounted view's host. */
  reportError(error: unknown): void;
}

interface Mounted {
  bridge: RuntimeBridge;
  store: ViewStateStore;
  cache: RequestCache;
}

export function createRuntime(
  post: (message: RuntimeToHost) => void,
  container: HTMLElement,
  table: ModuleTable = MODULES,
): Runtime {
  const root: Root = createRoot(container);
  let mounted: Mounted | null = null;

  const render = (
    m: Mounted,
    cache: RequestCache,
    component: ViewComponent,
    datasets: string[],
  ) => {
    root.render(
      <RuntimeProvider value={{ bridge: m.bridge, store: m.store, cache }}>
        <ErrorBoundary
          resetKey={m.bridge.viewId}
          onError={(e) => m.bridge.error(e.message, e.stack)}
        >
          <View component={component} datasets={datasets} />
        </ErrorBoundary>
      </RuntimeProvider>,
    );
  };

  const mount = async (message: Extract<HostToRuntime, { type: "mount" }>) => {
    const bridge = new RuntimeBridge(message.viewId, post);
    const store = new ViewStateStore(
      message.initialState,
      (s) => bridge.stateChanged(s),
      300,
    );
    // Runs before React re-renders, so the next snapshot carries only the new state's queries.
    store.subscribe(() => bridge.resetUsage());
    const cache = new RequestCache(bridge);
    const m: Mounted = { bridge, store, cache };
    mounted = m;
    try {
      const component = await loadComponent(message.source, table);
      if (mounted !== m) return;
      render(m, cache, component, message.datasets);
      // One report after the first render so an untouched view still records its queries.
      setTimeout(() => {
        if (mounted === m) store.flush();
      }, 300);
    } catch (error) {
      if (mounted !== m) return;
      const e = toError(error);
      bridge.error(e.message, e.stack);
      root.render(
        <pre className="m-4 whitespace-pre-wrap font-mono text-sm text-destructive">
          {e.message}
        </pre>,
      );
    }
  };

  post({ type: "ready" });

  return {
    handle(message) {
      if (message.type === "mount") {
        void mount(message);
        return;
      }
      if (mounted === null) return;
      mounted.bridge.handle(message, (control) => {
        if (control.type === "restore") mounted?.store.replace(control.state);
        if (control.type === "refresh") mounted?.cache.refresh();
      });
    },
    reportError(error) {
      const e = toError(error);
      mounted?.bridge.error(e.message, e.stack);
    },
  };
}

function toError(error: unknown): Error {
  return error instanceof Error ? error : new Error(String(error));
}

function View({
  component: Component,
  datasets,
}: {
  component: ViewComponent;
  datasets: string[];
}) {
  return <Component datasets={datasets} />;
}
