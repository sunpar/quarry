import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { SessionMeta, SessionStatus, Step } from "@/shared/api-types";
import { readSession } from "../api/auth";
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

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

function renderPage(
  fetchImpl: (path: string, init?: RequestInit) => Promise<Response>,
) {
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

// A server with the one session, holding `steps` and reporting `current`.
const routes =
  (steps: Step[], current: SessionStatus) => async (path: string) => {
    if (path === "/sessions") return json([meta]);
    if (path === "/sessions/s1") return json({ meta, steps });
    if (path === "/sessions/s1/status") return json(current);
    if (path === "/projects") return json([]);
    return new Response(null, { status: 404 });
  };

function setup(
  busy: boolean,
  runningStep: string | null = null,
  steps: Step[] = [],
) {
  return renderPage(routes(steps, status(busy, runningStep)));
}

describe("SessionPage prompt box", () => {
  // Interrupt stops only a step, so there is nothing for Stop to do.
  it("locks without Stop while the server holds the session for a save or restart", async () => {
    setup(true);
    const box = await screen.findByRole("textbox");
    await waitFor(() =>
      expect((box as HTMLTextAreaElement).disabled).toBe(true),
    );
    expect(screen.queryByRole("button", { name: "Stop" })).toBeNull();
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Run" }).disabled,
    ).toBe(true);
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
    // Interrupt stops it wherever it began.
    expect(screen.getByRole("button", { name: "Stop" })).toBeTruthy();
  });
});

describe("SessionPage project rail", () => {
  it("shows why the projects did not load", async () => {
    renderPage(async (path) => {
      if (path === "/sessions") return json([]);
      if (path === "/projects") return json({ detail: "db locked" }, 500);
      return new Response(null, { status: 404 });
    });
    expect(await screen.findByText("500: db locked")).toBeTruthy();
    expect(
      screen.queryByText("Create a project to save datasets and views into."),
    ).toBeNull();
  });
});

describe("SessionPage session choice", () => {
  const second: SessionMeta = { ...meta, id: "s2", title: "second" };
  const unlisted: SessionMeta = { ...meta, id: "s3", title: "unlisted" };

  // A server listing `listed`, to which a create adds, that also has the `unlisted` session;
  // and the paths the page fetched. `stale` is listed only on the first request, and later
  // list requests wait for `hold`.
  function serve(
    listed: SessionMeta[],
    {
      listing = 200,
      stale = [],
      hold,
    }: { listing?: number; stale?: SessionMeta[]; hold?: Promise<void> } = {},
  ) {
    const fetched: string[] = [];
    const fetchImpl = async (path: string, init?: RequestInit) => {
      fetched.push(path);
      if (path === "/sessions" && init?.method === "POST") {
        listed.push(second);
        return json(second);
      }
      if (path === "/sessions" && listing !== 200)
        return new Response(null, { status: listing });
      if (path === "/sessions" && fetched.indexOf(path) < fetched.length - 1)
        await hold;
      if (path === "/sessions") return json([...stale.splice(0), ...listed]);
      const session = [...listed, unlisted].find(
        (s) => path === `/sessions/${s.id}`,
      );
      if (session !== undefined) return json({ meta: session, steps: [] });
      if (path.endsWith("/status") && !path.includes("gone"))
        return json(status(false, null));
      if (path === "/projects") return json([]);
      return new Response(null, { status: 404 });
    };
    renderPage(fetchImpl);
    return fetched;
  }

  afterEach(() => history.replaceState(null, "", "/"));

  it("opens another session when the linked one is gone", async () => {
    history.replaceState(null, "", "#token=t&session=gone");
    serve([meta]);
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "t" }).ariaCurrent).toBe(
        "page",
      ),
    );
    expect(readSession(window.location.hash)).toBe("s1");
  });

  it("skips sessions a stale list still names", async () => {
    history.replaceState(null, "", "#token=t&session=gone");
    const goneToo: SessionMeta = { ...meta, id: "gone-too", title: "gone too" };
    serve([meta], { stale: [{ ...meta, id: "gone", title: "gone" }, goneToo] });
    await waitFor(() => expect(readSession(window.location.hash)).toBe("s1"));
    expect(screen.getByRole("button", { name: "t" }).ariaCurrent).toBe("page");
  });

  it("keeps a session picked while the fallback waits for the list", async () => {
    history.replaceState(null, "", "#token=t&session=gone");
    let release = () => {};
    const hold = new Promise<void>((resolve) => (release = resolve));
    const fetched = serve([meta, second], { hold });
    fireEvent.click(await screen.findByRole("button", { name: "second" }));
    await waitFor(() =>
      expect(fetched.filter((p) => p === "/sessions")).toHaveLength(2),
    );
    await waitFor(() => expect(fetched).toContain("/sessions/s2"));
    release();
    // Time for the fallback to run, had it not stepped aside.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(readSession(window.location.hash)).toBe("s2");
    expect(fetched).not.toContain("/sessions/s1");
  });

  it("clears the link when no other session is left", async () => {
    history.replaceState(null, "", "#token=t&session=gone");
    const fetched = serve([]);
    await waitFor(() =>
      expect(fetched.filter((p) => p === "/sessions")).toHaveLength(2),
    );
    await waitFor(() => expect(window.location.hash).toBe("#token=t"));
  });

  it("stays on a gone session when the list fails to load again", async () => {
    history.replaceState(null, "", "#token=t&session=gone");
    const fetched = serve([meta], { listing: 500 });
    await waitFor(() =>
      expect(fetched.filter((p) => p === "/sessions")).toHaveLength(2),
    );
    // Time for the fallback to run, had it not stepped aside.
    await new Promise((resolve) => setTimeout(resolve, 100));
    expect(readSession(window.location.hash)).toBe("gone");
  });

  it("keeps a linked session the list does not show yet", async () => {
    history.replaceState(null, "", "#token=t&session=s3");
    const fetched = serve([meta]);
    await screen.findByRole("textbox");
    const listedButton = await screen.findByRole("button", { name: "t" });
    expect(listedButton.ariaCurrent).toBe(null);
    expect(fetched).toContain("/sessions/s3");
    expect(readSession(window.location.hash)).toBe("s3");
  });

  it("keeps a linked session when the list fails", async () => {
    history.replaceState(null, "", "#token=t&session=s1");
    serve([meta], { listing: 500 });
    await screen.findByRole("textbox");
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

  it("says the token was rejected when the list answers 401", async () => {
    serve([meta], { listing: 401 });
    expect(
      await screen.findByText(
        "The token was rejected. Open the link that quarry serve printed.",
      ),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "New session" })).toBeNull();
  });
});

describe("SessionPage kernel banner", () => {
  it("drops a replay failure once a later restart succeeds", async () => {
    const replays = [
      { replayed: 0, failed_step: 0, error: "boom" },
      { replayed: 1, failed_step: null, error: null },
    ];
    // Each restart answers once released, so the test sees it pending and then done.
    let release = () => {};
    const page = routes([finished], {
      ...status(false, null),
      kernel: { status: "idle", pid: 1, replay_needed: true },
    });
    renderPage(async (path, init) => {
      if (path === "/sessions/s1/restart" && init?.method === "POST") {
        await new Promise<void>((resolve) => (release = resolve));
        return json(replays.shift());
      }
      return page(path);
    });
    const button = () =>
      screen.getByRole<HTMLButtonElement>("button", { name: "Restart kernel" });
    // A pending restart already hides the last report, so wait for this one to finish.
    const restart = async () => {
      fireEvent.click(button());
      await waitFor(() => expect(button().disabled).toBe(true));
      release();
      await waitFor(() => expect(button().disabled).toBe(false));
    };
    await screen.findByRole("button", { name: "Restart kernel" });
    await restart();
    expect(screen.getByText("Replay stopped at step 1: boom")).toBeTruthy();
    await restart();
    expect(screen.queryByText("Replay stopped at step 1: boom")).toBeNull();
  });
});
