import { Button } from "@/components/ui/button";
import type { Project } from "@/shared/api-types";

interface ProjectBrowserProps {
  projects: Project[];
  expanded: string | null;
  onToggle: (slug: string) => void;
  onOpen: (slug: string) => void;
  onRecall: (slug: string, kind: "dataset" | "view", name: string) => void;
  onCreate: () => void;
}

export function ProjectBrowser({
  projects,
  expanded,
  onToggle,
  onOpen,
  onRecall,
  onCreate,
}: ProjectBrowserProps) {
  return (
    <section className="flex flex-col gap-2 border-t border-border pt-4">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-medium">Projects</h2>
        <Button variant="ghost" size="xs" onClick={onCreate}>
          New project
        </Button>
      </div>
      {projects.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Save a dataset or view to start a project.
        </p>
      )}
      <ul className="flex flex-col gap-1">
        {projects.map(({ meta, datasets, views }) => (
          <li key={meta.slug} className="flex flex-col gap-1">
            <div className="flex items-center gap-1">
              <button
                type="button"
                aria-expanded={expanded === meta.slug}
                onClick={() => onToggle(meta.slug)}
                className="flex-1 truncate rounded-md px-2 py-1 text-left text-sm hover:bg-muted"
              >
                {meta.name}
              </button>
              <Button
                variant="ghost"
                size="xs"
                aria-label={`Open ${meta.name}`}
                onClick={() => onOpen(meta.slug)}
              >
                Open
              </Button>
            </div>
            {expanded === meta.slug && (
              <ul className="ml-3 flex flex-col gap-0.5 border-l border-border pl-2">
                {datasets.map((d) => (
                  <li
                    key={`dataset-${d.name}`}
                    className="flex items-center gap-2 text-sm"
                  >
                    <button
                      type="button"
                      aria-label={`Recall ${d.name}`}
                      onClick={() => onRecall(meta.slug, "dataset", d.name)}
                      className="truncate font-mono hover:text-primary"
                    >
                      {d.name}
                    </button>
                    <span className="text-xs text-muted-foreground">
                      {d.mode}
                    </span>
                    {!d.validated && (
                      <span
                        title={`Not validated: ${d.validation_error ?? "unknown reason"}`}
                        className="text-xs text-[var(--status-interrupted)]"
                      >
                        unvalidated
                      </span>
                    )}
                  </li>
                ))}
                {views.map((v) => (
                  <li key={`view-${v.name}`} className="text-sm">
                    <button
                      type="button"
                      aria-label={`Recall ${v.name}`}
                      onClick={() => onRecall(meta.slug, "view", v.name)}
                      className="truncate hover:text-primary"
                    >
                      {v.name}
                    </button>
                    <span className="ml-2 text-xs text-muted-foreground">
                      view
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ul>
    </section>
  );
}
