import { useEffect, useRef } from "react";
import type { Table } from "@finos/perspective";
import type {
  HTMLPerspectiveViewerElement,
  ViewerConfigUpdate,
} from "@finos/perspective-viewer";
import { ensureEngine } from "./engine";

interface PerspectiveViewerProps {
  arrow: ArrayBuffer;
  config?: ViewerConfigUpdate;
  onConfig?: (config: ViewerConfigUpdate) => void;
  className?: string;
}

export function PerspectiveViewer({
  arrow,
  config,
  onConfig,
  className,
}: PerspectiveViewerProps) {
  const host = useRef<HTMLDivElement>(null);
  const viewer = useRef<HTMLPerspectiveViewerElement | null>(null);
  const latest = useRef({ config, onConfig });
  latest.current = { config, onConfig };

  // The custom element owns its DOM; React only creates and removes it.
  useEffect(() => {
    const el = host.current;
    if (el === null) return;
    const node = document.createElement(
      "perspective-viewer",
    ) as HTMLPerspectiveViewerElement;
    node.style.height = "100%";
    el.replaceChildren(node);
    viewer.current = node;
    const onUpdate = () => {
      void node.save().then((saved) => latest.current.onConfig?.(saved));
    };
    node.addEventListener("perspective-config-update", onUpdate);
    return () => {
      node.removeEventListener("perspective-config-update", onUpdate);
      void node.delete();
      el.replaceChildren();
      viewer.current = null;
    };
  }, []);

  useEffect(() => {
    const node = viewer.current;
    if (node === null) return;
    let table: Table | null = null;
    let cancelled = false;
    void (async () => {
      const client = await ensureEngine();
      const next = await client.table(arrow);
      if (cancelled) {
        await next.delete();
        return;
      }
      table = next;
      await node.load(next);
      if (latest.current.config !== undefined)
        await node.restore(latest.current.config);
    })();
    return () => {
      cancelled = true;
      // Lazy: the viewer's view still holds this table, and an eager delete aborts.
      void table?.delete({ lazy: true });
    };
  }, [arrow]);

  return <div ref={host} className={className ?? "h-full w-full"} />;
}
