import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ProjectMeta, Step } from "@/shared/api-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { StepActions } from "./StepActions";

const meta: ProjectMeta = {
  slug: "p",
  name: "Momentum",
  description: "",
  created_at: "",
  updated_at: "",
  canvas: [],
};

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

function setup(saveFails = false, shown = step, picked?: string) {
  const calls: string[] = [];
  const bodies = new Map<string, unknown>();
  let finishSave = () => {};
  const saved = new Promise<void>((resolve) => (finishSave = resolve));
  const fetchImpl = async (path: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    calls.push(key);
    if (init?.body !== undefined)
      bodies.set(key, JSON.parse(String(init.body)));
    if (key === "GET /projects") return json([meta]);
    if (key === "POST /projects/p/views") {
      await saved;
      if (saveFails) return new Response(null, { status: 500 });
      return json({ name: "closes", saved_at: "t" });
    }
    return new Response(null, { status: 404 });
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onDone = vi.fn();
  const api = new ApiClient("t", fetchImpl);
  const tree = (s: Step, p?: string) => (
    <QueryClientProvider client={qc}>
      <ApiProvider client={api}>
        <StepActions sessionId="s1" step={s} picked={p} onDone={onDone} />
      </ApiProvider>
    </QueryClientProvider>
  );
  const { rerender } = render(tree(shown, picked));
  return {
    calls,
    bodies,
    finishSave,
    onDone,
    qc,
    rerender: (s: Step, p?: string) => rerender(tree(s, p)),
  };
}

async function pin() {
  fireEvent.click(screen.getByRole("button", { name: "Pin to canvas" }));
  const dialog = screen.getByRole("dialog");
  // The dialog opens before the project list arrives.
  within(dialog).getByText("Create a project in the rail first.");
  fireEvent.change(within(dialog).getByLabelText("Name"), {
    target: { value: "closes" },
  });
  const save = within(dialog).getByRole<HTMLButtonElement>("button", {
    name: "Save view",
  });
  await waitFor(() => expect(save.disabled).toBe(false));
  fireEvent.click(save);
}

describe("StepActions pin to canvas", () => {
  it("says it is saving and disables its buttons until the save ends", async () => {
    const { finishSave, onDone } = setup();
    await pin();
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
    const { calls, bodies, finishSave, onDone } = setup();
    finishSave();
    await pin();
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith("Saved view closes"),
    );
    expect(bodies.get("POST /projects/p/views")).toMatchObject({
      name: "closes",
      pin: true,
    });
    expect(calls.filter((c) => c.startsWith("PUT"))).toEqual([]);
  });

  it.each([
    ["picked", "t0", "t0"],
    ["latest", undefined, "t2"],
  ])(
    "saves the %s snapshot shown when the button was pressed",
    async (_, picked, shown) => {
      const withSnapshots = (count: number): Step => ({
        ...step,
        view: step.view && {
          ...step.view,
          snapshots: Array.from({ length: count }, (_, n) => ({
            ts: `t${n}`,
            state: { n },
            queries: [],
          })),
        },
      });
      const { bodies, finishSave, onDone, rerender } = setup(
        false,
        withSnapshots(3),
        picked,
      );
      finishSave();
      fireEvent.click(screen.getByRole("button", { name: "Save view" }));
      // A report while the dialog is open adds a snapshot and drops any pick.
      rerender(withSnapshots(4));
      const dialog = screen.getByRole("dialog");
      fireEvent.change(within(dialog).getByLabelText("Name"), {
        target: { value: "closes" },
      });
      const save = within(dialog).getByRole<HTMLButtonElement>("button", {
        name: "Save view",
      });
      await waitFor(() => expect(save.disabled).toBe(false));
      fireEvent.click(save);
      await waitFor(() =>
        expect(onDone).toHaveBeenCalledWith("Saved view closes"),
      );
      expect(bodies.get("POST /projects/p/views")).toMatchObject({
        pin: false,
        snapshot_ts: shown,
      });
    },
  );

  it("marks the project stale when the save fails", async () => {
    const { finishSave, onDone, qc } = setup(true);
    // An open canvas holds the project.
    qc.setQueryData(["projects", "p"], {
      meta,
      datasets: [],
      views: [],
    });
    finishSave();
    await pin();
    await waitFor(() =>
      expect(onDone).not.toHaveBeenLastCalledWith("Saving view closes…"),
    );
    // A view save can fail after it saved the view's datasets.
    expect(qc.getQueryState(["projects", "p"])?.isInvalidated).toBe(true);
  });
});
