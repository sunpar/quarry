import { useState } from "react";
import { useQueries } from "@tanstack/react-query";
import type { Project } from "@/shared/api-types";
import { useApi } from "../api/context";
import { useCreateProject, useProjects, useRecall } from "../api/hooks";
import { keys } from "../api/keys";
import { ProjectBrowser } from "../components/ProjectBrowser";

interface ProjectRailProps {
  sessionId: string | null;
  onOpen: (slug: string) => void;
}

export function ProjectRail({ sessionId, onOpen }: ProjectRailProps) {
  const api = useApi();
  const metas = useProjects();
  const create = useCreateProject();
  const recall = useRecall(sessionId ?? "");
  const [expanded, setExpanded] = useState<string | null>(null);
  const details = useQueries({
    queries: (metas.data ?? []).map((m) => ({
      queryKey: keys.project(m.slug),
      queryFn: () => api.getProject(m.slug),
    })),
  });
  const projects: Project[] = details.flatMap((q) => (q.data ? [q.data] : []));
  return (
    <div className="flex flex-col gap-2">
      <ProjectBrowser
        projects={projects}
        expanded={expanded}
        onToggle={(slug) => setExpanded(expanded === slug ? null : slug)}
        onOpen={onOpen}
        onRecall={(project, kind, name) => {
          if (sessionId === null) return;
          if (
            window.confirm(
              `Recall ${name} into this session? An existing dataset with that name is replaced.`,
            )
          ) {
            recall.mutate({ project, kind, name });
          }
        }}
        onCreate={() => {
          const name = window.prompt("Project name");
          if (name) create.mutate(name);
        }}
      />
      {recall.error !== null && (
        <p className="text-xs text-destructive">{recall.error.message}</p>
      )}
      {create.error !== null && (
        <p className="text-xs text-destructive">{create.error.message}</p>
      )}
    </div>
  );
}
