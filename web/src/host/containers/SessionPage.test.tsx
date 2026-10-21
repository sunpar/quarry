import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { SessionMeta, SessionStatus, Step } from "@/shared/api-types";
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

const finished: Step = {
  id: "st1",
  index: 0,
  kind: "manual",
  prompt: null,
  code: "x = 1",
  status: "ok",
  error: null,
  note: "",
  stdout_tail: "",
  stderr_tail: "",
  reads: [],
  writes: [],
  defines: [],
  datasets: [],
  view: null,
  created_at: "",
  duration_ms: 0,
};

const json = (body: unknown) => new Response(JSON.stringify(body));

function setup(
  busy: boolean,
  runningStep: string | null = null,
  steps: Step[] = [],
) {
  const fetchImpl = async (path: string) => {
    if (path === "/sessions") return json([meta]);
    if (path === "/sessions/s1") return json({ meta, steps });
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
    const qc = setup(true, "st1", [finished]);
    const box = await screen.findByRole("textbox");
    await waitFor(() =>
      expect(qc.getQueryData(["sessions", "s1", "status"])).toBeDefined(),
    );
    expect((box as HTMLTextAreaElement).disabled).toBe(false);
  });

  it("locks for a step this page has not seen, from another tab or the CLI", async () => {
    setup(true, "elsewhere", [finished]);
    const box = await screen.findByRole("textbox");
    await waitFor(() =>
      expect((box as HTMLTextAreaElement).disabled).toBe(true),
    );
  });
});

describe("SessionPage session choice", () => {
  const second: SessionMeta = { ...meta, id: "s2", title: "second" };

  // The sessions the server lists, which a create adds to, and the paths the page fetched.
  function serve(listed: SessionMeta[]) {
    const fetched: string[] = [];
    const fetchImpl = async (path: string, init?: RequestInit) => {
      fetched.push(path);
      if (path === "/sessions" && init?.method === "POST") {
        listed.push(second);
        return json(second);
      }
      if (path === "/sessions") return json(listed);
      const session = listed.find((s) => path === `/sessions/${s.id}`);
      if (session !== undefined) return json({ meta: session, steps: [] });
      if (path.endsWith("/status")) return json(status(false, null));
      if (path === "/projects") return json([]);
      return new Response(null, { status: 404 });
    };
    const qc = new QueryClient({
      defaultOptions: { queries: { retry: false } },
    });
    render(
      <QueryClientProvider client={qc}>
        <ApiProvider client={new ApiClient("t", fetchImpl)}>
          <SessionPage token="t" />
        </ApiProvider>
      </QueryClientProvider>,
    );
    return fetched;
  }

  afterEach(() => history.replaceState(null, "", "/"));

  it("opens the first session for an id the server does not list", async () => {
    history.replaceState(null, "", "#token=t&session=gone");
    const fetched = serve([meta]);
    await screen.findByRole("textbox");
    expect(screen.getByRole("button", { name: "t" }).ariaCurrent).toBe("page");
    expect(fetched).not.toContain("/sessions/gone");
  });

  it("opens a new session once it is created", async () => {
    const fetched = serve([meta]);
    await screen.findByRole("textbox");
    fireEvent.click(screen.getByRole("button", { name: "New session" }));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "second" }).ariaCurrent).toBe(
        "page",
      ),
    );
    expect(fetched).toContain("/sessions/s2");
  });
});
