import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type { Session, SessionStatus, StepRequest } from "@/shared/api-types";
import { useApi } from "./context";
import { keys } from "./keys";

const POLL_MS = 750;

const sessionRunning = (session: Session | undefined): boolean =>
  session?.steps.at(-1)?.status === "running";

export function useSessions() {
  const api = useApi();
  return useQuery({
    queryKey: keys.sessions(),
    queryFn: () => api.listSessions(),
  });
}

export function useSession(id: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.session(id),
    queryFn: () => api.getSession(id),
    refetchInterval: (query) =>
      sessionRunning(query.state.data) ? POLL_MS : false,
  });
}

export function useSessionStatus(id: string, running: boolean) {
  const api = useApi();
  return useQuery<SessionStatus>({
    queryKey: keys.status(id),
    queryFn: () => api.getStatus(id),
    refetchInterval: running ? POLL_MS : 5000,
  });
}

export function useCreateSession() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (title: string) => api.createSession(title),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.sessions() }),
  });
}

export function useSubmitPrompt(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: StepRequest) => api.postStep(id, body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.session(id) }),
  });
}

export function useInterrupt(id: string) {
  const api = useApi();
  return useMutation({ mutationFn: () => api.interrupt(id) });
}

export function useRestart(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => api.restart(id),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.session(id) }),
  });
}
