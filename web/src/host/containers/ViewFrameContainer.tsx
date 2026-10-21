import { useQueryClient } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import type {
  RepairRequest,
  Session,
  Snapshot,
  Step,
} from "@/shared/api-types";
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
  /** Given the position of the snapshot picked in the history, absent without a pick. */
  actions?: (picked?: number) => ReactNode;
}

// An updater that leaves an uncached session (undefined) as it is.
const withSnapshot =
  (stepId: string, snapshot: Snapshot) => (session: Session | undefined) =>
    session && {
      ...session,
      steps: session.steps.map((s) => {
        if (s.id !== stepId || !s.view) return s;
        // Mirrors the server's rule: a snapshot of the last state replaces it.
        const kept = s.view.snapshots;
        const repeats =
          JSON.stringify(kept.at(-1)?.state) === JSON.stringify(snapshot.state);
        const snapshots = [...(repeats ? kept.slice(0, -1) : kept), snapshot];
        return { ...s, view: { ...s.view, snapshots } };
      }),
    };

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
  // A pick in the scrubber holds only while the snapshot count and the view's report count it was
  // made at both hold. Each report drops it: the view has left the picked state even when its
  // report replaces the last snapshot and the count holds. A restore sends no report, and a
  // refetch alone keeps the pick. Counted here, not keyed on the scrubber, so it keeps its focus.
  const [reports, setReports] = useState(0);
  const [pick, setPick] = useState<{
    at: number;
    of: number;
    reports: number;
  } | null>(null);
  const view = step.view;
  if (view === null) return null;
  const { snapshots } = view;
  const picked =
    pick !== null && pick.of === snapshots.length && pick.reports === reports
      ? pick.at
      : undefined;
  return (
    <div className="flex flex-col gap-2">
      <ViewHost
        key={JSON.stringify([sessionId, step.id])}
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
          setReports((n) => n + 1);
          void api
            .postSnapshot(sessionId, step.id, { state, queries })
            // The scrubber reads snapshots from the session; record this one there instead of
            // refetching the whole session. An uncached session stays uncached.
            .then(() =>
              queryClient.setQueryData(
                keys.session(sessionId),
                withSnapshot(step.id, {
                  ts: new Date().toISOString(),
                  state,
                  queries,
                }),
              ),
            )
            .catch((e: unknown) => console.error("snapshot not saved", e));
        }}
        onFix={(error) => onRepair({ step_id: step.id, error })}
      />
      <div className="flex items-center gap-4 empty:hidden">
        <SnapshotScrubber
          count={snapshots.length}
          value={picked ?? snapshots.length - 1}
          onPick={(at) => {
            setPick({ at, of: snapshots.length, reports });
            const shown = snapshots[at];
            if (shown !== undefined) setRestoreState(shown.state);
          }}
        />
        {actions !== undefined && (
          <div className="ml-auto">{actions(picked)}</div>
        )}
      </div>
    </div>
  );
}
