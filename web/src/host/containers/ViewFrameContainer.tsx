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
  /** Given the ts of an older snapshot picked in the history, absent otherwise. */
  actions?: (picked?: string) => ReactNode;
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
  // The picked snapshot's ts, as the server stamped it, so the pick follows its snapshot through a
  // refetch and lapses once the server drops it. Each report drops it too: the view has left the
  // picked state even when its report replaces the last snapshot. A restore sends no report.
  // Dropped here, not by keying the scrubber, so it keeps its focus.
  const [pick, setPick] = useState<string | null>(null);
  const view = step.view;
  if (view === null) return null;
  const { snapshots } = view;
  // Once a refetch drops the picked snapshot, the view goes back to the latest, like the scrubber.
  if (pick !== null && !snapshots.some((s) => s.ts === pick)) {
    setPick(null);
    setRestoreState(snapshots.at(-1)?.state ?? null);
  }
  const picked = snapshots.findIndex((s) => s.ts === pick);
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
          // Cleared with the pick, so picking the same snapshot again restores it again.
          setPick(null);
          setRestoreState(null);
          void api
            .postSnapshot(sessionId, step.id, { state, queries })
            // The scrubber reads snapshots from the session; record the server's there instead
            // of refetching the whole session. An uncached session stays uncached.
            .then((saved) =>
              queryClient.setQueryData(
                keys.session(sessionId),
                withSnapshot(step.id, saved),
              ),
            )
            .catch((e: unknown) => console.error("snapshot not saved", e));
        }}
        onFix={(error) => onRepair({ step_id: step.id, error })}
      />
      <div className="flex items-center gap-4 empty:hidden">
        <SnapshotScrubber
          count={snapshots.length}
          value={picked === -1 ? snapshots.length - 1 : picked}
          onPick={(at) => {
            const shown = snapshots[at];
            // A pick of the latest is none: the view then follows newer snapshots, and the actions
            // send no ts, since a report of the same state restamps the latest.
            setPick(at === snapshots.length - 1 ? null : (shown?.ts ?? null));
            setRestoreState(shown?.state ?? null);
          }}
        />
        {actions !== undefined && (
          <div className="ml-auto">{actions(snapshots[picked]?.ts)}</div>
        )}
      </div>
    </div>
  );
}
