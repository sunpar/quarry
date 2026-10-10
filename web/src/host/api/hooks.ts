import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import type {
  CanvasCard,
  Project,
  QuerySpec,
  RecallRequest,
  SaveDatasetRequest,
  SaveViewRequest,
  Session,
  SessionStatus,
  Step,
  StepRequest,
} from "@/shared/api-types";
import type { SaveComponentRequest } from "@/shared/component-types";
import type { ApiClient } from "./client";
import { useApi } from "./context";
import { keys } from "./keys";

const POLL_MS = 750;

export const sessionRunning = (session: Session | undefined): boolean =>
  session?.steps.at(-1)?.status === "running";

/** Changes whenever kernel data may have: a step finished or a new kernel started. */
export const dataVersion = (steps: Step[], pid: number | null | undefined) =>
  `${steps.filter((s) => s.status !== "running").length}:${pid ?? ""}`;

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

export function useSubmitManual(id: string) {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (code: string) => api.postManualStep(id, code),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.session(id) }),
  });
}

export function useToCode(sessionId: string) {
  const api = useApi();
  return useMutation({
    mutationFn: (queries: QuerySpec[]) => api.toCode(sessionId, queries),
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
    onSuccess: () =>
      Promise.all([
        qc.invalidateQueries({ queryKey: keys.session(id) }),
        qc.invalidateQueries({ queryKey: keys.status(id) }),
      ]),
  });
}

export function useProjects() {
  const api = useApi();
  return useQuery({
    queryKey: keys.projects(),
    queryFn: () => api.listProjects(),
  });
}

export const projectQuery = (api: ApiClient, slug: string) => ({
  queryKey: keys.project(slug),
  queryFn: () => api.getProject(slug),
});

export function useProject(slug: string) {
  const api = useApi();
  return useQuery(projectQuery(api, slug));
}

export function useCreateProject() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (name: string) => api.createProject(name),
    onSuccess: () =>
      qc.invalidateQueries({ queryKey: keys.projects(), exact: true }),
  });
}

/** Asked once per app: the server reads its library config only at startup. */
export function useLibraries() {
  const api = useApi();
  return useQuery({
    queryKey: keys.libraries(),
    queryFn: () => api.libraries(),
    staleTime: Infinity,
    // Views wait for this answer before they mount, so a failure must not hold them in retries.
    retry: false,
  });
}

export function useComponents() {
  const api = useApi();
  return useQuery({
    queryKey: keys.components(),
    queryFn: () => api.listComponents(),
  });
}

export function useSaveComponent() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: SaveComponentRequest) => api.saveComponent(body),
    onSuccess: () => qc.invalidateQueries({ queryKey: keys.components() }),
  });
}

export function useSavedView(slug: string, name: string) {
  const api = useApi();
  return useQuery({
    queryKey: keys.savedView(slug, name),
    queryFn: () => api.getSavedView(slug, name),
  });
}

// The project is chosen inside the save dialog, so the slug travels with the mutation.
export function useSaveDataset() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, body }: { slug: string; body: SaveDatasetRequest }) =>
      api.saveDataset(slug, body),
    onSuccess: (_meta, { slug }) =>
      qc.invalidateQueries({ queryKey: keys.project(slug) }),
  });
}

export function useSaveView() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, body }: { slug: string; body: SaveViewRequest }) =>
      api.saveView(slug, body),
    onSuccess: (_meta, { slug }) =>
      qc.invalidateQueries({ queryKey: keys.project(slug) }),
  });
}

export function useSetCanvas() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ slug, cards }: { slug: string; cards: CanvasCard[] }) =>
      api.setCanvas(slug, cards),
    onSuccess: (meta, { slug }) =>
      qc.setQueryData(keys.project(slug), (old: Project | undefined) =>
        old ? { ...old, meta } : old,
      ),
  });
}

interface RecallVariables extends RecallRequest {
  sessionId: string;
}

// The session travels with the mutation, as the slug does for saves: the rail has none until
// one is chosen.
export function useRecall() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: ({ sessionId, ...body }: RecallVariables) =>
      api.recall(sessionId, body),
    onSuccess: (_step, { sessionId }) =>
      qc.invalidateQueries({ queryKey: keys.session(sessionId) }),
  });
}
