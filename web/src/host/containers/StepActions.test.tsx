import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { CanvasCard, ProjectMeta, Step } from "@/shared/api-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { StepActions } from "./StepActions";

const meta = (canvas: CanvasCard[]): ProjectMeta => ({
  slug: "p",
  name: "Momentum",
  description: "",
  created_at: "",
  updated_at: "",
  canvas,
});

const step: Step = {
  id: "st1",
  index: 0,
  kind: "prompt",
  prompt: "show prices",
  code: "",
  status: "ok",
  error: null,
  note: "",
  stdout_tail: "",
  stderr_tail: "",
  reads: [],
  writes: [],
  defines: [],
  datasets: [],
  view: {
    component_id: "data-table",
    content_hash: "h",
    source: "",
    initial_state: {},
    datasets: ["prices"],
    snapshots: [],
  },
  created_at: "",
  duration_ms: 0,
};

const json = (body: unknown) => new Response(JSON.stringify(body));

function setup(saveFails = false) {
  const calls: string[] = [];
  const bodies = new Map<string, unknown>();
  let finishSave = () => {};
  const saved = new Promise<void>((resolve) => (finishSave = resolve));
  const fetchImpl = async (path: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    calls.push(key);
    if (init?.body !== undefined)
      bodies.set(key, JSON.parse(String(init.body)));
    if (key === "GET /projects") return json([meta([])]);
    if (key === "POST /projects/p/views") {
      await saved;
      if (saveFails) return new Response(null, { status: 500 });
      return json({ name: "closes", saved_at: "t" });
    }
    return new Response(null, { status: 404 });
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onDone = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <ApiProvider client={new ApiClient("t", fetchImpl)}>
        <StepActions sessionId="s1" step={step} onDone={onDone} />
      </ApiProvider>
    </QueryClientProvider>,
  );
  return { calls, bodies, finishSave, onDone, qc };
}

async function pin(qc: QueryClient) {
  await waitFor(() => expect(qc.getQueryData(["projects"])).toBeDefined());
  fireEvent.click(screen.getByRole("button", { name: "Pin to canvas" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Name"), {
    target: { value: "closes" },
  });
  fireEvent.click(within(dialog).getByRole("button", { name: "Save view" }));
}

describe("StepActions pin to canvas", () => {
  it("says it is saving and disables its buttons until the save ends", async () => {
    const { finishSave, onDone, qc } = setup();
    await pin(qc);
    expect(onDone).toHaveBeenLastCalledWith("Saving view closes…");
    const button = () =>
      screen.getByRole<HTMLButtonElement>("button", { name: "Pin to canvas" });
    await waitFor(() => expect(button().disabled).toBe(true));
    finishSave();
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith("Saved view closes"),
    );
  });

  it("asks the save to pin the view and writes no canvas itself", async () => {
    const { calls, bodies, finishSave, onDone, qc } = setup();
    finishSave();
    await pin(qc);
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith("Saved view closes"),
    );
    expect(bodies.get("POST /projects/p/views")).toMatchObject({
      name: "closes",
      pin: true,
    });
    expect(calls.filter((c) => c.startsWith("PUT"))).toEqual([]);
  });

  it("marks the project stale when the save fails", async () => {
    const { finishSave, onDone, qc } = setup(true);
    // An open canvas holds the project.
    qc.setQueryData(["projects", "p"], {
      meta: meta([]),
      datasets: [],
      views: [],
    });
    finishSave();
    await pin(qc);
    await waitFor(() =>
      expect(onDone).not.toHaveBeenLastCalledWith("Saving view closes…"),
    );
    // A view save can fail after it saved the view's datasets.
    expect(qc.getQueryState(["projects", "p"])?.isInvalidated).toBe(true);
  });
});
