import { Button } from "@/components/ui/button";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useApi } from "../api/context";
import { downloadFile } from "../api/download";
import { useProject } from "../api/hooks";
import { DownloadButton } from "../components/DownloadButton";
import { SavedItems } from "../components/SavedItems";
import { CanvasPage } from "./CanvasPage";

interface ProjectPageProps {
  slug: string;
  sessionId: string | null;
  onBack: () => void;
}

export function ProjectPage({ slug, sessionId, onBack }: ProjectPageProps) {
  const api = useApi();
  const project = useProject(slug);
  if (project.data === undefined)
    return (
      <main className="flex-1 p-8 text-sm text-muted-foreground">
        {project.error?.message ?? "Loading"}
      </main>
    );
  // Only the selected panel is mounted, so a hidden tab never keeps canvas iframes alive.
  return (
    <Tabs
      render={<main />}
      defaultValue="canvas"
      className="min-w-0 flex-1 gap-0"
    >
      <div className="flex items-center gap-4 border-b border-border px-8 py-3">
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back to session
        </Button>
        <h1 className="text-base font-medium">{project.data.meta.name}</h1>
        <DownloadButton
          onDownload={() =>
            downloadFile(api, `/projects/${slug}/export.ipynb`, `${slug}.ipynb`)
          }
        >
          Export notebook
        </DownloadButton>
        <TabsList className="ml-auto">
          <TabsTrigger value="saved">Saved</TabsTrigger>
          <TabsTrigger value="canvas">Canvas</TabsTrigger>
        </TabsList>
      </div>
      <TabsContent value="saved" className="flex min-h-0 flex-col">
        <SavedItems
          project={project.data}
          onDownloadRecipe={(name) =>
            downloadFile(
              api,
              `/projects/${slug}/datasets/${name}/recipe.py`,
              `${name}.py`,
            )
          }
        />
      </TabsContent>
      <TabsContent value="canvas" className="flex min-h-0 flex-col">
        {sessionId === null ? (
          <p className="p-8 text-sm text-muted-foreground">
            Open a session first; canvas cards query through it.
          </p>
        ) : (
          <CanvasPage project={project.data} sessionId={sessionId} />
        )}
      </TabsContent>
    </Tabs>
  );
}
