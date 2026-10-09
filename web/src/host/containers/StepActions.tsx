import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Step } from "@/shared/api-types";
import {
  useProjects,
  useSaveDataset,
  useSaveView,
  useSetCanvas,
} from "../api/hooks";
import { SaveDialog, type SaveChoice } from "../components/SaveDialog";

interface StepActionsProps {
  sessionId: string;
  step: Step;
  dataset?: string;
  onDone: (message: string) => void;
}

type Pending =
  { kind: "dataset"; name: string } | { kind: "view"; pin: boolean } | null;

export function StepActions({
  sessionId,
  step,
  dataset,
  onDone,
}: StepActionsProps) {
  const projects = useProjects();
  const [pending, setPending] = useState<Pending>(null);
  const saveDataset = useSaveDataset();
  const saveView = useSaveView();
  const setCanvas = useSetCanvas();
  const onError = (e: Error) => onDone(e.message);

  const onSave = (choice: SaveChoice) => {
    const { slug } = choice;
    if (pending?.kind === "dataset") {
      saveDataset.mutate(
        {
          slug,
          body: {
            session_id: sessionId,
            dataset: pending.name,
            mode: choice.mode,
            description: choice.description,
          },
        },
        {
          onSuccess: (meta) =>
            onDone(
              meta.validated
                ? `Saved ${meta.name}`
                : `Saved ${meta.name} without validation: ${meta.validation_error ?? ""}`,
            ),
          onError,
        },
      );
    } else if (pending?.kind === "view") {
      const pin = pending.pin;
      saveView.mutate(
        {
          slug,
          body: {
            session_id: sessionId,
            step_id: step.id,
            name: choice.name,
            mode: choice.mode,
            description: choice.description,
          },
        },
        {
          onSuccess: (meta) => {
            onDone(`Saved view ${meta.name}`);
            if (pin) {
              const current =
                projects.data?.find((p) => p.slug === slug)?.canvas ?? [];
              const y = current.reduce((max, c) => Math.max(max, c.y + c.h), 0);
              setCanvas.mutate(
                {
                  slug,
                  cards: [...current, { view: meta.name, x: 0, y, w: 6, h: 8 }],
                },
                { onError },
              );
            }
          },
          onError,
        },
      );
    }
    setPending(null);
  };

  return (
    <div className="flex items-center gap-2">
      {dataset !== undefined && (
        <Button
          variant="ghost"
          size="xs"
          aria-label={`Save dataset ${dataset}`}
          onClick={() => setPending({ kind: "dataset", name: dataset })}
        >
          Save
        </Button>
      )}
      {step.view !== null && dataset === undefined && (
        <>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setPending({ kind: "view", pin: false })}
          >
            Save view
          </Button>
          <Button
            variant="ghost"
            size="xs"
            onClick={() => setPending({ kind: "view", pin: true })}
          >
            Pin to canvas
          </Button>
        </>
      )}
      {pending !== null && (
        <SaveDialog
          open
          kind={pending.kind}
          projects={projects.data ?? []}
          defaultName={
            pending.kind === "dataset"
              ? pending.name
              : `step-${step.index + 1}-view`
          }
          onClose={() => setPending(null)}
          onSave={onSave}
        />
      )}
    </div>
  );
}
