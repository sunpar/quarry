import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { Project } from "@/shared/api-types";
import { useApi } from "../api/context";
import {
  projectQuery,
  useCreateProject,
  useProjects,
  useRecall,
} from "../api/hooks";
import { ProjectBrowser } from "../components/ProjectBrowser";

interface ProjectRailProps {
  sessionId: string | null;
  onOpen: (slug: string) => void;
}

export function ProjectRail({ sessionId, onOpen }: ProjectRailProps) {
  const api = useApi();
  const metas = useProjects();
  const create = useCreateProject();
  const recall = useRecall();
  const [expanded, setExpanded] = useState<string | null>(null);
  // Only the open project needs its datasets and views; the rest list by name.
  const detail = useQuery({
    ...projectQuery(api, expanded ?? ""),
    enabled: expanded !== null,
  });
  const projects: Project[] = (metas.data ?? []).map((meta) =>
    meta.slug === expanded && detail.data !== undefined
      ? detail.data
      : { meta, datasets: [], views: [] },
  );
  return (
    <div className="flex flex-col gap-2">
      <ProjectBrowser
        projects={projects}
        expanded={expanded}
        onToggle={(slug) => setExpanded(expanded === slug ? null : slug)}
        onOpen={onOpen}
        onRecall={(project, kind, name) => {
          if (sessionId === null) return;
          const effect =
            kind === "dataset"
              ? "An existing dataset with that name is replaced."
              : "This loads the view and any of its datasets the session lacks.";
          if (window.confirm(`Recall ${name} into this session? ${effect}`)) {
            recall.mutate({ sessionId, project, kind, name });
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
