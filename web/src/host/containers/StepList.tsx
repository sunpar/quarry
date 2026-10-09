import type { ReactNode } from "react";
import type { Step } from "@/shared/api-types";
import { StepCard } from "../components/StepCard";

interface StepListProps {
  steps: Step[];
  renderView?: (step: Step) => ReactNode;
  renderDatasetAction?: (step: Step, name: string) => ReactNode;
}

export function StepList({
  steps,
  renderView,
  renderDatasetAction,
}: StepListProps) {
  if (steps.length === 0) {
    return (
      <p className="px-8 py-10 text-sm text-muted-foreground">
        Ask for data to start. Try "load the prices cache for 2024".
      </p>
    );
  }
  return (
    <div className="flex flex-col px-8 py-8">
      {steps.map((step) => (
        <StepCard
          key={step.id}
          step={step}
          index={step.index + 1}
          view={step.view && renderView ? renderView(step) : undefined}
          datasetAction={
            renderDatasetAction
              ? (name) => renderDatasetAction(step, name)
              : undefined
          }
        />
      ))}
    </div>
  );
}
