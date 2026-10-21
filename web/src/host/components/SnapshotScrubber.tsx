interface SnapshotScrubberProps {
  count: number;
  /** The position of the snapshot shown. */
  value: number;
  onPick: (position: number) => void;
}

export function SnapshotScrubber({
  count,
  value,
  onPick,
}: SnapshotScrubberProps) {
  if (count < 2) return null;
  return (
    <label className="flex items-center gap-3 text-sm text-muted-foreground">
      History
      <input
        type="range"
        min={0}
        max={count - 1}
        value={value}
        onChange={(e) => onPick(Number(e.target.value))}
        className="w-48 accent-primary"
      />
      <span className="tabular-nums">
        {value + 1} of {count}
      </span>
    </label>
  );
}
