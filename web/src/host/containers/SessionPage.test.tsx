import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { SessionMeta, SessionStatus } from "@/shared/api-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { SessionPage } from "./SessionPage";

const meta: SessionMeta = {
  id: "s1",
  title: "t",
  created_at: "",
  provider: { name: "f", model: "m" },
};

const status = (busy: boolean, runningStep: string | null): SessionStatus => ({
  session_id: "s1",
  running_step: runningStep,
  busy,
  kernel: { status: "idle", pid: 1, replay_needed: false },
  last_error: null,
});

const json = (body: unknown) => new Response(JSON.stringify(body));

function setup(busy: boolean, runningStep: string | null = null) {
  const fetchImpl = async (path: string) => {
    if (path === "/sessions") return json([meta]);
    if (path === "/sessions/s1") return json({ meta, steps: [] });
    if (path === "/sessions/s1/status") return json(status(busy, runningStep));
    if (path === "/projects") return json([]);
    return new Response(null, { status: 404 });
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ApiProvider client={new ApiClient("t", fetchImpl)}>
        <SessionPage token="t" />
      </ApiProvider>
    </QueryClientProvider>,
  );
  return qc;
}

describe("SessionPage prompt box", () => {
  it("locks while the server holds the session for a save or restart", async () => {
    setup(true);
    const box = await screen.findByRole("textbox");
    await waitFor(() =>
      expect((box as HTMLTextAreaElement).disabled).toBe(true),
    );
  });

  it("stays open when the session is free", async () => {
    const qc = setup(false);
    const box = await screen.findByRole("textbox");
    await waitFor(() =>
      expect(qc.getQueryData(["sessions", "s1", "status"])).toBeDefined(),
    );
    expect((box as HTMLTextAreaElement).disabled).toBe(false);
  });

  // The status poll slows once the step ends, so its last answer can predate the end.
  it("stays open on a status taken while a finished step still ran", async () => {
    const qc = setup(true, "st1");
    const box = await screen.findByRole("textbox");
    await waitFor(() =>
      expect(qc.getQueryData(["sessions", "s1", "status"])).toBeDefined(),
    );
    expect((box as HTMLTextAreaElement).disabled).toBe(false);
  });
});
