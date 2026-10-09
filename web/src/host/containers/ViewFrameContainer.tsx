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
  onRepair: (repair: RepairRequest) => void;
}

export function ViewFrameContainer({
  sessionId,
  step,
  onRepair,
}: ViewFrameContainerProps) {
  const api = useApi();
  const queryClient = useQueryClient();
  const frameRef = useRef<HTMLIFrameElement>(null);
  const [error, setError] = useState<string | null>(null);
  // Snapshots append to step.view on every poll, so the effect keys on the content hash and
  // reads the (immutable) source, initial state and datasets through a ref.
  const viewRef = useRef(step.view);
  viewRef.current = step.view;
  const contentHash = step.view?.content_hash ?? null;
  const ownDatasets = step.datasets;

  // One bridge per iframe for its lifetime; the window listener is the effect's only job.
  useEffect(() => {
    const frame = frameRef.current;
    const view = viewRef.current;
    if (frame === null || view === null || contentHash === null) return;
    // The step already carries the schema of everything it wrote; only datasets from earlier
    // steps need the API, fetched fresh so a view never sees a list from before its step ran.
    const schemaFor = async (dataset: string): Promise<Column[]> => {
      const own = ownDatasets.find((d) => d.name === dataset);
      if (own !== undefined) return own.schema;
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
        void api.postSnapshot(sessionId, step.id, { state, queries });
      },
      onError: (message) => setError(message),
    });
    const stop = bridge.listen(window);
    setError(null);
    bridge.mount({
      source: view.source,
      initialState: view.initial_state,
      datasets: view.datasets,
    });
    return stop;
  }, [api, queryClient, sessionId, step.id, contentHash, ownDatasets]);

  if (step.view === null) return null;
  return (
    <ViewFrame
      ref={frameRef}
      title={`View for step ${step.index + 1}`}
      error={error}
      onFix={() => error !== null && onRepair({ step_id: step.id, error })}
    />
  );
}
