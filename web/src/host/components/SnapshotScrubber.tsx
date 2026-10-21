import { useState } from "react";
import type { Snapshot } from "@/shared/api-types";
import type { JsonObject } from "@/shared/json";

interface SnapshotScrubberProps {
  snapshots: Snapshot[];
  onPick: (state: JsonObject) => void;
}

export function SnapshotScrubber({ snapshots, onPick }: SnapshotScrubberProps) {
  // A pick holds only while the list it was made from does; a new snapshot moves to the latest.
  const [pick, setPick] = useState<{ at: number; of: number } | null>(null);
  if (snapshots.length < 2) return null;
  const current =
    pick !== null && pick.of === snapshots.length
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
          setPick({ at: next, of: snapshots.length });
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
