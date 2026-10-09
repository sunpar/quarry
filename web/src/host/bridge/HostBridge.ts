import type { Column, QueryResult, QuerySpec } from "@/shared/api-types";
import {
  isRuntimeMessage,
  type HostToRuntime,
  type RuntimeToHost,
} from "@/shared/bridge-types";
import type { JsonObject } from "@/shared/json";

export interface MountSpec {
  source: string;
  initialState: JsonObject;
  datasets: string[];
}

export interface HostBridgeOptions {
  viewId: string;
  frame: { postMessage(message: HostToRuntime, targetOrigin: string): void };
  isFrame: (source: unknown) => boolean;
  onQuery: (spec: QuerySpec) => Promise<QueryResult>;
  onSchema: (dataset: string) => Promise<Column[]>;
  onStateChanged: (state: JsonObject, queries: QuerySpec[]) => void;
  onError: (message: string, stack?: string) => void;
}

export class HostBridge {
  private ready = false;
  private mountSpec: MountSpec | null = null;

  constructor(private readonly options: HostBridgeOptions) {}

  listen(target: Window): () => void {
    const handler = (event: MessageEvent<unknown>) => this.handleEvent(event);
    target.addEventListener("message", handler);
    return () => target.removeEventListener("message", handler);
  }

  handleEvent(event: { data: unknown; source: unknown }): void {
    if (!this.options.isFrame(event.source)) return;
    if (!isRuntimeMessage(event.data)) return;
    this.receive(event.data);
  }

  mount(spec: MountSpec): void {
    this.mountSpec = spec;
    if (this.ready) this.flushMount();
  }

  /** The frame's `load` fired, so its runtime is listening even if `ready` was missed. */
  frameLoaded(): void {
    if (this.ready) return;
    this.ready = true;
    this.flushMount();
  }

  refresh(): void {
    this.send({ type: "refresh", viewId: this.options.viewId });
  }

  restore(state: JsonObject): void {
    this.send({ type: "restore", viewId: this.options.viewId, state });
  }

  private receive(message: RuntimeToHost): void {
    if (message.type === "ready") {
      this.ready = true;
      this.flushMount();
      return;
    }
    if (message.viewId !== this.options.viewId) return;
    const { viewId } = this.options;
    switch (message.type) {
      case "query":
        void this.options.onQuery(message.spec).then(
          (result) =>
            this.send({
              type: "queryResult",
              viewId,
              id: message.id,
              ok: true,
              result,
            }),
          (error: unknown) =>
            this.send({
              type: "queryResult",
              viewId,
              id: message.id,
              ok: false,
              error: text(error),
            }),
        );
        return;
      case "schema":
        void this.options.onSchema(message.dataset).then(
          (schema) =>
            this.send({
              type: "schemaResult",
              viewId,
              id: message.id,
              ok: true,
              schema,
            }),
          (error: unknown) =>
            this.send({
              type: "schemaResult",
              viewId,
              id: message.id,
              ok: false,
              error: text(error),
            }),
        );
        return;
      case "stateChanged":
        this.options.onStateChanged(message.state, message.queries);
        return;
      case "error":
        this.options.onError(message.message, message.stack);
        return;
    }
  }

  private flushMount(): void {
    if (this.mountSpec === null) return;
    const { source, initialState, datasets } = this.mountSpec;
    this.send({
      type: "mount",
      viewId: this.options.viewId,
      source,
      initialState,
      datasets,
    });
  }

  private send(message: HostToRuntime): void {
    // The sandboxed frame has an opaque origin; "*" is the only target that reaches it.
    this.options.frame.postMessage(message, "*");
  }
}

function text(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}
