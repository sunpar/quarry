import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface CanvasCardFrameProps {
  title: string;
  missing: string[];
  loading: boolean;
  onLoad: () => void;
  onRemove: () => void;
  children: ReactNode;
}

export function CanvasCardFrame({
  title,
  missing,
  loading,
  onLoad,
  onRemove,
  children,
}: CanvasCardFrameProps) {
  return (
    <div className="flex h-full flex-col overflow-hidden rounded-md border border-border bg-card">
      <div className="card-handle flex cursor-move items-center justify-between border-b border-border px-3 py-1.5 text-sm">
        <span className="truncate">{title}</span>
        <Button
          variant="ghost"
          size="xs"
          aria-label={`Remove ${title} from canvas`}
          title={`Remove ${title} from canvas`}
          onClick={onRemove}
        >
          Remove
        </Button>
      </div>
      <div className="min-h-0 flex-1">
        {missing.length === 0 ? (
          children
        ) : (
          <div className="flex h-full flex-col items-start gap-2 p-4 text-sm text-muted-foreground">
            <p>Needs {missing.join(", ")} in this session.</p>
            <Button size="sm" disabled={loading} onClick={onLoad}>
              {loading ? "Loading" : "Load"}
            </Button>
          </div>
        )}
      </div>
    </div>
  );
}
