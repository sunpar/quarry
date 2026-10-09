import { Button } from "@/components/ui/button";
import type { KernelStatus, ReplayReport } from "@/shared/api-types";

interface KernelBannerProps {
  kernel: KernelStatus | undefined;
  lastError: string | null;
  restarting: boolean;
  restartError: string | null;
  replay: ReplayReport | null;
  onRestart: () => void;
}

export function KernelBanner({
  kernel,
  lastError,
  restarting,
  restartError,
  replay,
  onRestart,
}: KernelBannerProps) {
  const message =
    kernel?.status === "dead"
      ? `The Python kernel stopped${lastError ? `: ${lastError}` : "."}`
      : kernel?.replay_needed
        ? "The kernel restarted without this session's steps."
        : null;
  const failure =
    replay !== null && replay.failed_step !== null && replay.error !== null
      ? `Replay stopped at step ${replay.failed_step + 1}: ${replay.error}`
      : null;
  if (message === null && failure === null && restartError === null)
    return null;
  return (
    <div className="flex flex-wrap items-center gap-4 border-b border-border bg-card px-8 py-3 text-sm">
      {message !== null && <span className="text-destructive">{message}</span>}
      {failure !== null && <span className="text-destructive">{failure}</span>}
      {restartError !== null && (
        <span className="text-destructive">{restartError}</span>
      )}
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
