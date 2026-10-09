import { Badge } from "@/components/ui/badge";

interface ValidationBadgeProps {
  error: string | null;
}

export function ValidationBadge({ error }: ValidationBadgeProps) {
  return (
    <Badge
      variant="outline"
      title={`Not validated: ${error ?? "unknown reason"}`}
      className="text-[var(--status-interrupted)]"
    >
      unvalidated
    </Badge>
  );
}
