import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { Column, RepairRequest, Step } from "@/shared/api-types";
import { useApi } from "../api/context";
import { keys } from "../api/keys";
import { HostBridge } from "../bridge/HostBridge";
import { ViewFrame } from "../components/ViewFrame";

interface ViewFrameContainerProps {
  sessionId: string;
  step: Step;
  running: boolean;
  onRepair: (repair: RepairRequest) => void;
}

export function ViewFrameContainer({
  sessionId,
  step,
  running,
  onRepair,
}: ViewFrameContainerProps) {
  const api = useApi();
  const queryClient = useQueryClient();
  const frameRef = useRef<HTMLIFrameElement>(null);
  // The frame loads once, as soon as it is committed; the bridge arrives later, in the effect.
  const loaded = useRef(false);
  const bridgeRef = useRef<HostBridge | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Snapshots append to step.view on every poll, so the effect keys on the content hash and
  // reads the (immutable) source, initial state and datasets through a ref.
  const viewRef = useRef(step.view);
  viewRef.current = step.view;
  const contentHash = step.view?.content_hash ?? null;

  // One bridge per iframe for its lifetime; the window listener is the effect's only job.
  useEffect(() => {
    const frame = frameRef.current;
    const view = viewRef.current;
    if (frame === null || view === null || contentHash === null) return;
    // Schemas come from the live kernel, as queries do: a later step may have redefined the
    // name. Fetched fresh so a view never sees a list from before its step ran.
    const schemaFor = async (dataset: string): Promise<Column[]> => {
      const datasets = await queryClient.fetchQuery({
        queryKey: keys.datasets(sessionId),
        queryFn: () => api.datasets(sessionId),
        staleTime: 0,
      });
      const match = datasets.find((d) => d.name === dataset);
      if (match === undefined) throw new Error(`unknown dataset ${dataset}`);
      return match.schema;
    };
    const bridge = new HostBridge({
      viewId: step.id,
      frame: {
        postMessage: (m, origin) => frame.contentWindow?.postMessage(m, origin),
      },
      isFrame: (source) => source === frame.contentWindow,
      onQuery: (spec) => api.query(sessionId, spec),
      onSchema: schemaFor,
      onStateChanged: (state, queries) => {
        void api
          .postSnapshot(sessionId, step.id, { state, queries })
          .catch((e: unknown) => console.error("snapshot not saved", e));
      },
      onError: (message) => setError(message),
    });
    const stop = bridge.listen(window);
    bridgeRef.current = bridge;
    setError(null);
    bridge.mount({
      source: view.source,
      initialState: view.initial_state,
      datasets: view.datasets,
    });
    // The runtime posts `ready` once while loading, which can beat this listener; a frame
    // that has already loaded is listening, so mount now.
    if (loaded.current) bridge.frameLoaded();
    return () => {
      bridgeRef.current = null;
      stop();
    };
  }, [api, queryClient, sessionId, step.id, contentHash]);

  if (step.view === null) return null;
  return (
    <ViewFrame
      ref={frameRef}
      title={`View for step ${step.index + 1}`}
      error={error}
      disabled={running}
      onFix={() => error !== null && onRepair({ step_id: step.id, error })}
      onLoad={() => {
        loaded.current = true;
        bridgeRef.current?.frameLoaded();
      }}
    />
  );
}
