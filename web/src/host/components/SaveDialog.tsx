import { useState } from "react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import type { ProjectMeta, RecallRequest, SaveMode } from "@/shared/api-types";

export interface SaveChoice {
  slug: string;
  name: string;
  mode: SaveMode;
  description: string;
}

interface SaveDialogProps {
  open: boolean;
  kind: RecallRequest["kind"];
  projects: ProjectMeta[] | undefined;
  error: string | null;
  defaultName: string;
  onClose: () => void;
  onSave: (choice: SaveChoice) => void;
}

export const slugifyName = (name: string): string =>
  name
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "");

export function SaveDialog({
  open,
  kind,
  projects,
  error,
  defaultName,
  onClose,
  onSave,
}: SaveDialogProps) {
  const [slug, setSlug] = useState(projects?.[0]?.slug ?? "");
  // The list can load after the dialog opens, so its first project is the default then.
  if (slug === "" && projects?.[0] !== undefined) setSlug(projects[0].slug);
  const [name, setName] = useState(defaultName);
  const [mode, setMode] = useState<SaveMode>("live");
  const [description, setDescription] = useState("");
  const cleanName = kind === "view" ? slugifyName(name) : name;
  const canSave = slug !== "" && cleanName !== "";
  const label = kind === "view" ? "Save view" : "Save dataset";
  // A failed refetch keeps the last list, so an empty one still shows the error.
  const hint =
    projects !== undefined && projects.length > 0
      ? null
      : (error ??
        (projects === undefined
          ? "Loading"
          : "Create a project in the rail first."));
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="flex flex-col gap-4">
        <DialogHeader>
          <DialogTitle>{label}</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="save-project">Project</Label>
          {hint !== null && (
            <p
              className={`text-xs ${hint === error ? "text-destructive" : "text-muted-foreground"}`}
            >
              {hint}
            </p>
          )}
          <select
            id="save-project"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            className="h-8 rounded-md border border-input bg-background px-2 text-sm"
          >
            {projects?.map((p) => (
              <option key={p.slug} value={p.slug}>
                {p.name}
              </option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="save-name">Name</Label>
          <Input
            id="save-name"
            value={name}
            disabled={kind === "dataset"}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <fieldset className="flex flex-col gap-1.5">
          <legend className="text-sm font-medium">Data</legend>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="mode"
              checked={mode === "live"}
              onChange={() => setMode("live")}
            />
            Live recipe
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="radio"
              name="mode"
              checked={mode === "pinned"}
              onChange={() => setMode("pinned")}
            />
            Pinned copy
          </label>
          <p className="text-xs text-muted-foreground">
            A live recipe re-runs the code that made the data. A pinned copy
            also keeps today's rows as parquet.
          </p>
        </fieldset>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="save-description">Description</Label>
          <Textarea
            id="save-description"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            disabled={!canSave}
            onClick={() => onSave({ slug, name: cleanName, mode, description })}
          >
            {label}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
