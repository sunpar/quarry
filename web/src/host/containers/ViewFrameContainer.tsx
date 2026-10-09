import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import type { RepairRequest, Step } from "@/shared/api-types";
import type { JsonObject } from "@/shared/json";
import { useApi } from "../api/context";
import { keys } from "../api/keys";
import { SnapshotScrubber } from "../components/SnapshotScrubber";
import { ViewHost } from "./ViewHost";

interface ViewFrameContainerProps {
  sessionId: string;
  step: Step;
  running: boolean;
  /** Changes whenever kernel data may have: a step finished or a new kernel started. */
  dataVersion: string;
  onRepair: (repair: RepairRequest) => void;
  actions?: ReactNode;
}

export function ViewFrameContainer({
  sessionId,
  step,
  running,
  dataVersion,
  onRepair,
  actions,
}: ViewFrameContainerProps) {
  const api = useApi();
  const queryClient = useQueryClient();
  const [restoreState, setRestoreState] = useState<JsonObject | null>(null);
  const view = step.view;
  if (view === null) return null;
  return (
    <div className="flex flex-col gap-2">
      <ViewHost
        viewId={step.id}
        sessionId={sessionId}
        contentKey={view.content_hash}
        source={view.source}
        initialState={view.initial_state}
        datasets={view.datasets}
        restoreState={restoreState}
        dataVersion={dataVersion}
        title={`View for step ${step.index + 1}`}
        disabled={running}
        onStateChanged={(state, queries) => {
          void api
            .postSnapshot(sessionId, step.id, { state, queries })
            // The scrubber reads snapshots from the session; status and datasets are unchanged.
            .then(() => {
              void queryClient.invalidateQueries({
                queryKey: keys.session(sessionId),
                exact: true,
              });
            })
            .catch((e: unknown) => console.error("snapshot not saved", e));
        }}
        onFix={(error) => onRepair({ step_id: step.id, error })}
      />
      <div className="flex items-center gap-4 empty:hidden">
        <SnapshotScrubber snapshots={view.snapshots} onPick={setRestoreState} />
        {actions !== undefined && <div className="ml-auto">{actions}</div>}
      </div>
    </div>
  );
}
