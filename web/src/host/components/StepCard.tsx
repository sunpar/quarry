import type { ReactNode } from "react";
import type { Step } from "@/shared/api-types";
import { CodeDrawer } from "./CodeDrawer";
import { DatasetChips } from "./DatasetChips";

interface StepCardProps {
  step: Step;
  index: number;
  view?: ReactNode;
  datasetAction?: (name: string) => ReactNode;
}

const RULE: Record<Step["status"], string> = {
  running: "bg-[var(--status-running)]",
  ok: "bg-[var(--status-ok)]",
  error: "bg-[var(--status-error)]",
  interrupted: "bg-[var(--status-interrupted)]",
};

const LABEL: Record<Step["status"], string> = {
  running: "Running",
  ok: "Done",
  error: "Failed",
  interrupted: "Stopped",
};

export function StepCard({ step, index, view, datasetAction }: StepCardProps) {
  return (
    <article
      className="grid grid-cols-[2.5rem_3px_1fr] gap-x-4"
      aria-label={`Step ${index}`}
    >
      <div className="pt-0.5 text-right font-mono text-sm text-muted-foreground">
        {index}
      </div>
      <div className={`rounded-full ${RULE[step.status]}`} />
      <div className="flex min-w-0 flex-col gap-3 pb-8">
        {step.prompt !== null && (
          <p className="text-base leading-6">{step.prompt}</p>
        )}
        <p className="flex gap-4 text-sm text-muted-foreground">
          <span>{LABEL[step.status]}</span>
          {step.duration_ms > 0 && (
            <span>{(step.duration_ms / 1000).toFixed(1)} s</span>
          )}
        </p>
        {step.note !== "" && <p className="text-sm">{step.note}</p>}
        {step.error !== null && (
          <pre className="overflow-x-auto rounded-md bg-muted p-3 font-mono text-xs text-destructive">
            {step.error.traceback || step.error.message}
          </pre>
        )}
        {view}
        <DatasetChips datasets={step.datasets} renderAction={datasetAction} />
        <CodeDrawer code={step.code} />
      </div>
    </article>
  );
}
