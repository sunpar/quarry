import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { Button } from "@/components/ui/button";
import type { Step, View } from "@/shared/api-types";
import { ApiError } from "../api/client";
import { useApi } from "../api/context";
import {
  projectQuery,
  useProjects,
  useSaveComponent,
  useSaveDataset,
  useSaveView,
  useSetCanvas,
  useSubmitManual,
  useToCode,
} from "../api/hooks";
import {
  SaveComponentDialog,
  type ComponentChoice,
} from "../components/SaveComponentDialog";
import { SaveDialog, type SaveChoice } from "../components/SaveDialog";
import { ToCodeDrawer, toCodeSource } from "../components/ToCodeDrawer";

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
  const api = useApi();
  const qc = useQueryClient();
  const projects = useProjects();
  const [pending, setPending] = useState<Pending>(null);
  const saveDataset = useSaveDataset();
  const saveView = useSaveView();
  const setCanvas = useSetCanvas();
  const saving =
    saveDataset.isPending || saveView.isPending || setCanvas.isPending;
  const onError = (e: Error) => onDone(e.message);
  const codeInput = toCodeSource(step.view?.snapshots.at(-1));
  const toCodeRequest = useToCode(sessionId);
  const submitManual = useSubmitManual(sessionId);
  const [toCode, setToCode] = useState<{
    code: string;
    dropped: string[];
  } | null>(null);
  const saveComponent = useSaveComponent();
  const [toLibrary, setToLibrary] = useState<View | null>(null);
  const refusal = saveComponent.error;

  // The project itself, not the list, holds the canvas this pin extends.
  const pinCard = async (slug: string, view: string) => {
    const project = await qc.fetchQuery(projectQuery(api, slug));
    const current = project.meta.canvas;
    // The save already refreshed an existing card through its saved_at.
    if (current.some((c) => c.view === view)) return;
    const y = current.reduce((max, c) => Math.max(max, c.y + c.h), 0);
    setCanvas.mutate(
      { slug, cards: [...current, { view, x: 0, y, w: 6, h: 8 }] },
      { onError },
    );
  };

  const onSave = (choice: SaveChoice) => {
    const { slug } = choice;
    const common = {
      session_id: sessionId,
      mode: choice.mode,
      description: choice.description,
    };
    if (pending?.kind === "dataset") {
      onDone(`Saving ${pending.name}…`);
      saveDataset.mutate(
        { slug, body: { ...common, dataset: pending.name } },
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
      onDone(`Saving view ${choice.name}…`);
      saveView.mutate(
        { slug, body: { ...common, step_id: step.id, name: choice.name } },
        {
          onSuccess: (meta) => {
            onDone(`Saved view ${meta.name}`);
            if (pin) pinCard(slug, meta.name).catch(onError);
          },
          onError,
        },
      );
    }
    setPending(null);
  };

  const onSaveComponent = (choice: ComponentChoice, view: View) => {
    // The server takes both or neither, so a view without datasets binds nothing.
    const bound = view.datasets[0] ?? null;
    saveComponent.mutate(
      {
        ...choice,
        source: view.source,
        session_id: bound === null ? null : sessionId,
        dataset: bound,
      },
      {
        onSuccess: (manifest) => {
          setToLibrary(null);
          onDone(`Saved ${manifest.id} to your library`);
        },
      },
    );
  };

  return (
    <div className="flex flex-wrap items-center justify-end gap-2">
      {dataset !== undefined && (
        <Button
          variant="ghost"
          size="xs"
          aria-label={`Save dataset ${dataset}`}
          disabled={saving}
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
            disabled={saving}
            onClick={() => setPending({ kind: "view", pin: false })}
          >
            Save view
          </Button>
          <Button
            variant="ghost"
            size="xs"
            disabled={saving}
            onClick={() => setPending({ kind: "view", pin: true })}
          >
            Pin to canvas
          </Button>
          <Button
            variant="ghost"
            size="xs"
            disabled={codeInput.queries.length === 0 || toCodeRequest.isPending}
            onClick={() =>
              toCodeRequest.mutate(codeInput.queries, {
                onSuccess: ({ code }) => {
                  submitManual.reset();
                  setToCode({ code, dropped: codeInput.dropped });
                },
                onError,
              })
            }
          >
            To code
          </Button>
          {step.view.component_id === "inline" && (
            <Button
              variant="ghost"
              size="xs"
              onClick={() => setToLibrary(step.view)}
            >
              Save to library
            </Button>
          )}
        </>
      )}
      {toCode !== null && (
        <ToCodeDrawer
          open
          code={toCode.code}
          dropped={toCode.dropped}
          pending={submitManual.isPending}
          error={submitManual.error?.message ?? null}
          onChange={(code) => setToCode({ ...toCode, code })}
          onRun={() =>
            submitManual.mutate(toCode.code, {
              onSuccess: () => setToCode(null),
            })
          }
          onClose={() => setToCode(null)}
        />
      )}
      {toLibrary !== null && (
        <SaveComponentDialog
          open
          defaultId={`step-${step.index + 1}-view`}
          pending={saveComponent.isPending}
          error={
            refusal instanceof ApiError
              ? refusal.detail
              : (refusal?.message ?? null)
          }
          onClose={() => {
            saveComponent.reset();
            setToLibrary(null);
          }}
          onSave={(choice) => onSaveComponent(choice, toLibrary)}
        />
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
