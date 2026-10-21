import { Button } from "@/components/ui/button";

interface ToCodeDrawerProps {
  code: string;
  dropped: string[];
  pending: boolean;
  error: string | null;
  onChange: (code: string) => void;
  onRun: () => void;
  onClose: () => void;
}

export function ToCodeDrawer({
  code,
  dropped,
  pending,
  error,
  onChange,
  onRun,
  onClose,
}: ToCodeDrawerProps) {
  return (
    <section
      aria-label="To code"
      className="flex basis-full flex-col gap-2 rounded-md border border-border bg-card p-3"
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
