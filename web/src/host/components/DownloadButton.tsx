import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

interface DownloadButtonProps {
  children: ReactNode;
  label?: string;
  onDownload: () => Promise<void>;
}

/** A download that can fail says why beside its own button. */
export function DownloadButton({
  children,
  label,
  onDownload,
}: DownloadButtonProps) {
  const [pending, setPending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const download = () => {
    setPending(true);
    setError(null);
    onDownload()
      .catch((e: Error) => setError(e.message))
      .finally(() => setPending(false));
  };
  return (
    <span className="flex items-center gap-2">
      <Button
        variant="ghost"
        size="xs"
        aria-label={label}
        disabled={pending}
        onClick={download}
      >
        {children}
      </Button>
      {error !== null && (
        <span className="text-xs text-destructive">{error}</span>
      )}
    </span>
  );
}
