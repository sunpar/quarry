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
}

interface Mounted {
  bridge: RuntimeBridge;
  store: ViewStateStore;
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
    const cache = new RequestCache(bridge);
    const m: Mounted = { bridge, store };
    mounted = m;
    try {
      const component = await loadComponent(message.source, table);
      if (mounted !== m) return;
      render(m, cache, component, message.datasets);
    } catch (error) {
      if (mounted !== m) return;
      const e = error instanceof Error ? error : new Error(String(error));
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
      });
    },
  };
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
