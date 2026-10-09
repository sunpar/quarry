export const keys = {
  sessions: () => ["sessions"] as const,
  session: (id: string) => ["sessions", id] as const,
  status: (id: string) => ["sessions", id, "status"] as const,
  datasets: (id: string) => ["sessions", id, "datasets"] as const,
  projects: () => ["projects"] as const,
  project: (slug: string) => ["projects", slug] as const,
  savedView: (slug: string, name: string) =>
    ["projects", slug, "views", name] as const,
};
