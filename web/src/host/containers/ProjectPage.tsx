import { useState } from "react";
import { Button } from "@/components/ui/button";
import { useProject } from "../api/hooks";
import { SavedItems } from "../components/SavedItems";
import { CanvasPage } from "./CanvasPage";

interface ProjectPageProps {
  slug: string;
  sessionId: string | null;
  onBack: () => void;
}

export function ProjectPage({ slug, sessionId, onBack }: ProjectPageProps) {
  const project = useProject(slug);
  const [tab, setTab] = useState<"saved" | "canvas">("canvas");
  if (project.data === undefined)
    return (
      <main className="flex-1 p-8 text-sm text-muted-foreground">Loading</main>
    );
  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <div className="flex items-center gap-4 border-b border-border px-8 py-3">
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back to session
        </Button>
        <h1 className="text-base font-medium">{project.data.meta.name}</h1>
        <div role="tablist" className="ml-auto flex gap-1">
          {(["saved", "canvas"] as const).map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              className="rounded-md px-2 py-1 text-sm aria-selected:bg-muted aria-selected:text-primary"
            >
              {t === "saved" ? "Saved" : "Canvas"}
            </button>
          ))}
        </div>
      </div>
      {tab === "saved" && <SavedItems project={project.data} />}
      {tab === "canvas" &&
        (sessionId === null ? (
          <p className="p-8 text-sm text-muted-foreground">
            Open a session first; canvas cards query through it.
          </p>
        ) : (
          <CanvasPage project={project.data} sessionId={sessionId} />
        ))}
    </main>
  );
}
