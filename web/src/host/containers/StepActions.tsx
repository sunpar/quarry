import { useState } from "react";
import { Button } from "@/components/ui/button";
import type { Step, View } from "@/shared/api-types";
import type { ToCodeResponse } from "@/shared/component-types";
import { ApiError } from "../api/client";
import {
  useProjects,
  useSaveComponent,
  useSaveDataset,
  useSaveView,
  useSubmitManual,
  useToCode,
} from "../api/hooks";
import {
  SaveComponentDialog,
  type ComponentChoice,
} from "../components/SaveComponentDialog";
import { SaveDialog, type SaveChoice } from "../components/SaveDialog";
import { ToCodeDrawer } from "../components/ToCodeDrawer";

interface StepActionsProps {
  sessionId: string;
  step: Step;
  /** The ts of an older snapshot picked in the view's history, absent otherwise. */
  picked?: string;
  dataset?: string;
  onDone: (message: string) => void;
}

// A view save keeps the pick made at the press: a report while the dialog is open drops it.
type Pending =
  | { kind: "dataset"; name: string }
  | { kind: "view"; pin: boolean; snapshotTs?: string }
  | null;

export function StepActions({
  sessionId,
  step,
  picked,
  dataset,
  onDone,
}: StepActionsProps) {
  const projects = useProjects();
  const [pending, setPending] = useState<Pending>(null);
  const saveDataset = useSaveDataset();
  const saveView = useSaveView();
  const saving = saveDataset.isPending || saveView.isPending;
  const onError = (e: Error) => onDone(e.message);
  const toCodeRequest = useToCode(sessionId);
  const submitManual = useSubmitManual(sessionId);
  const [toCode, setToCode] = useState<ToCodeResponse | null>(null);
  const saveComponent = useSaveComponent();
  const [toLibrary, setToLibrary] = useState<View | null>(null);
  const refusal = saveComponent.error;

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
      onDone(`Saving view ${choice.name}…`);
      saveView.mutate(
        {
          slug,
          body: {
            ...common,
            step_id: step.id,
            name: choice.name,
            pin: pending.pin,
            snapshot_ts: pending.snapshotTs,
          },
        },
        { onSuccess: (meta) => onDone(`Saved view ${meta.name}`), onError },
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
            onClick={() =>
              setPending({ kind: "view", pin: false, snapshotTs: picked })
            }
          >
            Save view
          </Button>
          <Button
            variant="ghost"
            size="xs"
            disabled={saving}
            onClick={() =>
              setPending({ kind: "view", pin: true, snapshotTs: picked })
            }
          >
            Pin to canvas
          </Button>
          <Button
            variant="ghost"
            size="xs"
            // Nothing to render until the view reports what it shows.
            disabled={
              step.view.snapshots.length === 0 || toCodeRequest.isPending
            }
            onClick={() =>
              toCodeRequest.mutate(
                { stepId: step.id, snapshotTs: picked },
                {
                  onSuccess: (rendered) => {
                    submitManual.reset();
                    setToCode(rendered);
                  },
                  onError,
                },
              )
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
