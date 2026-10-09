import { Badge } from "@/components/ui/badge";
import type { DatasetMeta } from "@/shared/api-types";

export function DatasetChips({ datasets }: { datasets: DatasetMeta[] }) {
  if (datasets.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {datasets.map((d) => (
        <Badge
          key={d.name}
          variant="secondary"
          className="gap-1.5 font-mono text-xs"
          title={`${d.schema.length} columns`}
        >
          <span>{d.name}</span>
          {d.rows !== null && (
            <span className="text-muted-foreground">
              {d.rows.toLocaleString()}
            </span>
          )}
        </Badge>
      ))}
    </div>
  );
}
