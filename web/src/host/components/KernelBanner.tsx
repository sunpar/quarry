import { Button } from "@/components/ui/button";
import type { KernelStatus } from "@/shared/api-types";

interface KernelBannerProps {
  kernel: KernelStatus | undefined;
  lastError: string | null;
  restarting: boolean;
  onRestart: () => void;
}

export function KernelBanner({
  kernel,
  lastError,
  restarting,
  onRestart,
}: KernelBannerProps) {
  if (kernel?.status !== "dead") return null;
  return (
    <div className="flex items-center gap-4 border-b border-border bg-card px-8 py-3 text-sm">
      <span className="text-destructive">
        The Python kernel stopped{lastError ? `: ${lastError}` : "."}
      </span>
      <Button
        size="sm"
        variant="outline"
        disabled={restarting}
        onClick={onRestart}
      >
        Restart kernel
      </Button>
      <span className="text-muted-foreground">
        Restarting replays every finished step.
      </span>
    </div>
  );
}
