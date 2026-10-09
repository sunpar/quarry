export const keys = {
  sessions: () => ["sessions"] as const,
  session: (id: string) => ["sessions", id] as const,
  status: (id: string) => ["sessions", id, "status"] as const,
  datasets: (id: string) => ["sessions", id, "datasets"] as const,
};
