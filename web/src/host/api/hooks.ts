import {
  keepPreviousData,
  type QueryClient,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
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

/** The kernel's datasets, listed again whenever `version` (see `dataVersion`) changes. */
export function useDatasets(id: string, version: string) {
  const api = useApi();
  return useQuery({
    queryKey: [...keys.datasets(id), version],
    queryFn: () => api.datasets(id),
    // The last list stays while the next loads, so a step ending does not remount every card.
    placeholderData: keepPreviousData,
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

export function useSaveComponent() {
  const api = useApi();
  return useMutation({
    mutationFn: (body: SaveComponentRequest) => api.saveComponent(body),
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

interface SaveViewVariables {
  slug: string;
  body: SaveViewRequest;
  pin?: boolean;
}

/**
 * Saves a view and, with `pin`, adds its card to the canvas, as one mutation: the step card
 * that asked can unmount before the save ends, which drops `mutate`'s own callbacks, while the
 * mutation runs on.
 */
export function useSaveView() {
  const api = useApi();
  const qc = useQueryClient();
  return useMutation({
    mutationFn: async ({ slug, body, pin }: SaveViewVariables) => {
      const meta = await api.saveView(slug, body);
      if (pin) await pinView(api, qc, slug, meta.name);
      return meta;
    },
    onSuccess: (_meta, { slug }) =>
      qc.invalidateQueries({ queryKey: keys.project(slug) }),
  });
}

// The project itself, not the list, holds the canvas this pin extends.
async function pinView(
  api: ApiClient,
  qc: QueryClient,
  slug: string,
  view: string,
): Promise<void> {
  const project = await qc.fetchQuery(projectQuery(api, slug));
  const current = project.meta.canvas;
  // The save already refreshed an existing card through its saved_at.
  if (current.some((c) => c.view === view)) return;
  const y = current.reduce((max, c) => Math.max(max, c.y + c.h), 0);
  const cards = [...current, { view, x: 0, y, w: 6, h: 8 }];
  const meta = await api.setCanvas(slug, cards);
  qc.setQueryData(keys.project(slug), (old: Project | undefined) =>
    old ? { ...old, meta } : old,
  );
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
