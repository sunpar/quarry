import { useState } from "react";
import { KernelBanner } from "../components/KernelBanner";
import { PromptBox } from "../components/PromptBox";
import { SessionRail } from "../components/SessionRail";
import {
  useCreateSession,
  useInterrupt,
  useRestart,
  useSession,
  useSessions,
  useSessionStatus,
  useSubmitPrompt,
} from "../api/hooks";
import { StepList } from "./StepList";
import { ViewFrameContainer } from "./ViewFrameContainer";

export function SessionPage() {
  const sessions = useSessions();
  const create = useCreateSession();
  const [activeId, setActiveId] = useState<string | null>(null);
  const current = activeId ?? sessions.data?.[0]?.id ?? null;

  return (
    <div className="flex h-screen">
      <SessionRail
        sessions={sessions.data ?? []}
        activeId={current}
        onSelect={setActiveId}
        onCreate={() =>
          create.mutate("Untitled", {
            onSuccess: (meta) => setActiveId(meta.id),
          })
        }
      />
      {current === null ? (
        <main className="flex-1" />
      ) : (
        <SessionColumn key={current} id={current} />
      )}
    </div>
  );
}

function SessionColumn({ id }: { id: string }) {
  const session = useSession(id);
  const submit = useSubmitPrompt(id);
  const interrupt = useInterrupt(id);
  const restart = useRestart(id);
  const steps = session.data?.steps ?? [];
  const running = steps.at(-1)?.status === "running" || submit.isPending;
  const status = useSessionStatus(id, running);

  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <KernelBanner
        kernel={status.data?.kernel}
        lastError={status.data?.last_error ?? null}
        restarting={restart.isPending}
        onRestart={() => restart.mutate()}
      />
      <div className="min-h-0 flex-1 overflow-y-auto">
        <div className="max-w-[944px]">
          {submit.isError && (
            <p className="px-8 pt-4 text-sm text-destructive">
              {submit.error.message}
            </p>
          )}
          <StepList
            steps={steps}
            renderView={(step) => (
              <ViewFrameContainer
                sessionId={id}
                step={step}
                onRepair={(repair) =>
                  submit.mutate({
                    prompt: "Fix the view so it mounts.",
                    repair,
                  })
                }
              />
            )}
          />
        </div>
      </div>
      <PromptBox
        running={running}
        onSubmit={(prompt) => submit.mutate({ prompt })}
        onStop={() => interrupt.mutate()}
      />
    </main>
  );
}
