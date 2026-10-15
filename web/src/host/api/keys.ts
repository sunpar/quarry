import type { QuerySpec } from "@/shared/api-types";

export const keys = {
  sessions: () => ["sessions"] as const,
  session: (id: string) => ["sessions", id] as const,
  status: (id: string) => ["sessions", id, "status"] as const,
  datasets: (id: string) => ["sessions", id, "datasets"] as const,
  query: (id: string, version: string, spec: QuerySpec) =>
    ["sessions", id, "queries", version, spec] as const,
  projects: () => ["projects"] as const,
  project: (slug: string) => ["projects", slug] as const,
  savedView: (slug: string, name: string) =>
    ["projects", slug, "views", name] as const,
  libraries: () => ["libraries"] as const,
};
