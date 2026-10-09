import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { readSession, sessionHash } from "../api/auth";
import { ApiError } from "../api/client";
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
import { ProjectRail } from "./ProjectRail";
import { StepActions } from "./StepActions";
import { StepList } from "./StepList";
import { ViewFrameContainer } from "./ViewFrameContainer";

interface SessionPageProps {
  token: string;
  onOpenProject: (slug: string) => void;
}

export function SessionPage({ token, onOpenProject }: SessionPageProps) {
  const sessions = useSessions();
  const create = useCreateSession();
  const [activeId, setActiveId] = useState(() =>
    readSession(window.location.hash),
  );
  // A pasted link for another session on this server changes only the fragment.
  useEffect(() => {
    const onHashChange = () => setActiveId(readSession(window.location.hash));
    window.addEventListener("hashchange", onHashChange);
    return () => window.removeEventListener("hashchange", onHashChange);
  }, []);
  const current = activeId ?? sessions.data?.[0]?.id ?? null;
  const select = (id: string) => {
    setActiveId(id);
    history.replaceState(null, "", sessionHash(token, id));
  };

  if (sessions.error instanceof ApiError && sessions.error.status === 401)
    return (
      <main className="mx-auto max-w-[560px] px-8 py-16 text-sm text-destructive">
        The token was rejected. Open the link that quarry serve printed.
      </main>
    );

  return (
    <div className="flex h-screen">
      <SessionRail
        sessions={sessions.data ?? []}
        activeId={current}
        onSelect={select}
        onCreate={() =>
          create.mutate("Untitled", {
            onSuccess: (meta) => select(meta.id),
          })
        }
      >
        <ProjectRail sessionId={current} onOpen={onOpenProject} />
      </SessionRail>
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
  const finished = steps.filter((s) => s.status !== "running").length;
  const dataVersion = `${finished}:${status.data?.kernel.pid ?? ""}`;
  const [notice, setNotice] = useState<string | null>(null);

  return (
    <main className="flex min-w-0 flex-1 flex-col">
      <KernelBanner
        kernel={status.data?.kernel}
        lastError={status.data?.last_error ?? null}
        restarting={restart.isPending}
        restartError={restart.error?.message ?? null}
        replay={restart.data ?? null}
        onRestart={() => restart.mutate()}
      />
      {notice !== null && (
        <div
          role="status"
          className="flex items-center gap-4 border-b border-border bg-card px-8 py-2 text-sm"
        >
          <span>{notice}</span>
          <Button variant="ghost" size="xs" onClick={() => setNotice(null)}>
            Dismiss
          </Button>
        </div>
      )}
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
                running={running}
                dataVersion={dataVersion}
                onRepair={(repair) =>
                  submit.mutate({
                    prompt: "Fix the view so it mounts.",
                    repair,
                  })
                }
                actions={
                  <StepActions sessionId={id} step={step} onDone={setNotice} />
                }
              />
            )}
            renderDatasetAction={(step, name) => (
              <StepActions
                sessionId={id}
                step={step}
                dataset={name}
                onDone={setNotice}
              />
            )}
          />
        </div>
      </div>
      <PromptBox
        running={running}
        kernelDead={status.data?.kernel.status === "dead"}
        onSubmit={(prompt) => submit.mutateAsync({ prompt })}
        onStop={() => interrupt.mutate()}
      />
    </main>
  );
}
