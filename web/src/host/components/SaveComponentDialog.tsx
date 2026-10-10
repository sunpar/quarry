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

export interface ComponentChoice {
  id: string;
  name: string;
  description: string;
  tags: string[];
}

interface SaveComponentDialogProps {
  open: boolean;
  defaultId: string;
  /** The last save is still in flight. */
  pending?: boolean;
  /** Why the server refused the last save. */
  error?: string | null;
  onClose: () => void;
  onSave: (choice: ComponentChoice) => void;
}

const ID = /^[a-z0-9][a-z0-9-]{0,63}$/;

// Unlike a view name, a component id has no underscores.
const normaliseId = (value: string): string =>
  value
    .toLowerCase()
    .replace(/[^a-z0-9-]+/g, "-")
    .replace(/^-+|-+$/g, "");

export function SaveComponentDialog({
  open,
  defaultId,
  pending = false,
  error = null,
  onClose,
  onSave,
}: SaveComponentDialogProps) {
  const [id, setId] = useState(defaultId);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [tags, setTags] = useState("");
  const cleanId = normaliseId(id);
  const canSave = !pending && ID.test(cleanId) && name.trim() !== "";
  const save = () =>
    onSave({
      id: cleanId,
      name: name.trim(),
      description,
      tags: tags
        .split(",")
        .map((t) => t.trim())
        .filter((t) => t !== ""),
    });
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="flex flex-col gap-4">
        <DialogHeader>
          <DialogTitle>Save to library</DialogTitle>
        </DialogHeader>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="component-id">Id</Label>
          <Input
            id="component-id"
            value={id}
            onChange={(e) => setId(e.target.value)}
          />
          {cleanId !== id && cleanId !== "" && (
            <p className="text-xs text-muted-foreground">
              Saved as <code className="font-mono">{cleanId}</code>
            </p>
          )}
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="component-name">Name</Label>
          <Input
            id="component-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="component-description">Description</Label>
          <Textarea
            id="component-description"
            rows={2}
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="component-tags">Tags</Label>
          <Input
            id="component-tags"
            placeholder="scatter, returns"
            value={tags}
            onChange={(e) => setTags(e.target.value)}
          />
        </div>
        {error !== null && <p className="text-sm text-destructive">{error}</p>}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={!canSave} onClick={save}>
            Save to library
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
