import { forwardRef } from "react";
import { Button } from "@/components/ui/button";

interface ViewFrameProps {
  title: string;
  error: string | null;
  disabled: boolean;
  onFix: () => void;
  onLoad: () => void;
}

export const ViewFrame = forwardRef<HTMLIFrameElement, ViewFrameProps>(
  function ViewFrame({ title, error, disabled, onFix, onLoad }, ref) {
    return (
      <div className="relative border-y border-border bg-card">
        <iframe
          ref={ref}
          title={title}
          src="/runtime.html"
          sandbox="allow-scripts"
          className="block h-[420px] w-full"
          onLoad={onLoad}
        />
        {error !== null && (
          <div className="absolute inset-0 flex flex-col gap-3 overflow-auto bg-card p-4">
            <p className="text-sm text-muted-foreground">
              The view did not mount.
            </p>
            <pre className="whitespace-pre-wrap font-mono text-sm text-destructive">
              {error}
            </pre>
            <div>
              <Button size="sm" disabled={disabled} onClick={onFix}>
                Fix this view
              </Button>
            </div>
          </div>
        )}
      </div>
    );
  },
);
