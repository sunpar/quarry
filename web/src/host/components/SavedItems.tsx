import { Badge } from "@/components/ui/badge";
import type { Project } from "@/shared/api-types";
import { DownloadButton } from "./DownloadButton";
import { ValidationBadge } from "./ValidationBadge";

interface SavedItemsProps {
  project: Project;
  onDownloadRecipe: (dataset: string) => Promise<void>;
}

export function SavedItems({ project, onDownloadRecipe }: SavedItemsProps) {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto px-8 py-6">
      <div className="flex max-w-[944px] flex-col gap-8">
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium">Datasets</h2>
          {project.datasets.length === 0 && (
            <p className="text-sm text-muted-foreground">No saved datasets.</p>
          )}
          <ul className="flex flex-col gap-3">
            {project.datasets.map((d) => (
              <li key={d.name} className="flex flex-col gap-1 text-sm">
                <div className="flex items-center gap-2">
                  <span className="font-mono">{d.name}</span>
                  <span className="text-xs text-muted-foreground">
                    {d.mode}
                  </span>
                  {d.rows !== null && (
                    <span className="text-xs text-muted-foreground">
                      {d.rows} rows
                    </span>
                  )}
                  {d.validated ? (
                    <Badge variant="secondary">validated</Badge>
                  ) : (
                    <ValidationBadge error={d.validation_error} />
                  )}
                  <DownloadButton
                    label={`Download recipe ${d.name}`}
                    onDownload={() => onDownloadRecipe(d.name)}
                  >
                    Download recipe
                  </DownloadButton>
                </div>
                {!d.validated && (
                  <p className="text-xs text-muted-foreground">
                    Not validated: {d.validation_error ?? "unknown reason"}
                  </p>
                )}
                {d.description !== "" && (
                  <p className="text-muted-foreground">{d.description}</p>
                )}
              </li>
            ))}
          </ul>
        </section>
        <section className="flex flex-col gap-3">
          <h2 className="text-sm font-medium">Views</h2>
          {project.views.length === 0 && (
            <p className="text-sm text-muted-foreground">No saved views.</p>
          )}
          <ul className="flex flex-col gap-3">
            {project.views.map((v) => (
              <li key={v.name} className="flex flex-col gap-1 text-sm">
                <div className="flex items-center gap-2">
                  <span>{v.name}</span>
                  <span className="font-mono text-xs text-muted-foreground">
                    {v.component_id}
                  </span>
                </div>
                <p className="text-xs text-muted-foreground">
                  Uses{" "}
                  <span className="font-mono">{v.datasets.join(", ")}</span>
                </p>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </div>
  );
}
