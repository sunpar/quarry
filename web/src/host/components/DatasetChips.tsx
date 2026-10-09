import type { ReactNode } from "react";
import { Badge } from "@/components/ui/badge";
import type { DatasetMeta } from "@/shared/api-types";

interface DatasetChipsProps {
  datasets: DatasetMeta[];
  renderAction?: (name: string) => ReactNode;
}

export function DatasetChips({ datasets, renderAction }: DatasetChipsProps) {
  if (datasets.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {datasets.map((d) => (
        <span key={d.name} className="inline-flex items-center gap-0.5">
          <Badge
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
          {renderAction?.(d.name)}
        </span>
      ))}
    </div>
  );
}
