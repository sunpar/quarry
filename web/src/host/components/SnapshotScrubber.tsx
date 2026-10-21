import { useState } from "react";
import type { Snapshot } from "@/shared/api-types";
import type { JsonObject } from "@/shared/json";

interface SnapshotScrubberProps {
  snapshots: Snapshot[];
  /** Counts the view's reports; a new one means the view has left the picked state. */
  reports: number;
  onPick: (state: JsonObject) => void;
}

export function SnapshotScrubber({
  snapshots,
  reports,
  onPick,
}: SnapshotScrubberProps) {
  // A pick holds only while the list it was made from and the view's reports do; a new snapshot
  // or report moves to the latest. A report can replace the last snapshot and keep the count.
  const [pick, setPick] = useState<{
    at: number;
    of: number;
    reports: number;
  } | null>(null);
  if (snapshots.length < 2) return null;
  const current =
    pick !== null && pick.of === snapshots.length && pick.reports === reports
      ? pick.at
      : snapshots.length - 1;
  return (
    <label className="flex items-center gap-3 text-sm text-muted-foreground">
      History
      <input
        type="range"
        min={0}
        max={snapshots.length - 1}
        value={current}
        onChange={(e) => {
          const next = Number(e.target.value);
          setPick({ at: next, of: snapshots.length, reports });
          const picked = snapshots[next];
          if (picked !== undefined) onPick(picked.state);
        }}
        className="w-48 accent-primary"
      />
      <span className="tabular-nums">
        {current + 1} of {snapshots.length}
      </span>
    </label>
  );
}
