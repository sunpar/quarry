import { Button } from "@/components/ui/button";
import type { QuerySpec, Snapshot } from "@/shared/api-types";

interface ToCodeDrawerProps {
  open: boolean;
  code: string;
  dropped: string[];
  pending: boolean;
  error: string | null;
  onChange: (code: string) => void;
  onRun: () => void;
  onClose: () => void;
}

const isSpec = (value: unknown): value is QuerySpec =>
  typeof value === "object" &&
  value !== null &&
  typeof (value as { dataset?: unknown }).dataset === "string";

/**
 * What "To code" renders for a view's latest snapshot. A view may publish its to-code spec
 * under `spec`, which wins over its queries; the pivot's are an arrow load and a probe.
 */
export function toCodeSource(snapshot: Snapshot | undefined): {
  queries: QuerySpec[];
  dropped: string[];
} {
  if (snapshot === undefined) return { queries: [], dropped: [] };
  const { spec, dropped } = snapshot.state;
  const strings =
    Array.isArray(dropped) &&
    dropped.every((d): d is string => typeof d === "string");
  return {
    queries: isSpec(spec) ? [spec] : snapshot.queries,
    dropped: strings ? dropped : [],
  };
}

export function ToCodeDrawer({
  open,
  code,
  dropped,
  pending,
  error,
  onChange,
  onRun,
  onClose,
}: ToCodeDrawerProps) {
  if (!open) return null;
  return (
    <section
      aria-label="To code"
      className="flex w-[40rem] max-w-full basis-full flex-col gap-2 rounded-md border border-border bg-card p-3"
    >
      <p className="text-sm text-muted-foreground">
        Python for this view's queries. Edit it, then run it as a step; its
        outputs join the lineage.
      </p>
      {dropped.length > 0 && (
        <p className="text-sm text-muted-foreground">
          Left out: {dropped.join(", ")}.
        </p>
      )}
      <textarea
        aria-label="Python"
        className="min-h-48 w-full rounded-md bg-muted p-3 font-mono text-xs leading-relaxed"
        value={code}
        spellCheck={false}
        onChange={(e) => onChange(e.target.value)}
      />
      {error !== null && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button
          size="sm"
          disabled={pending || code.trim() === ""}
          onClick={onRun}
        >
          Run as step
        </Button>
        <Button size="sm" variant="ghost" onClick={onClose}>
          Close
        </Button>
      </div>
    </section>
  );
}
