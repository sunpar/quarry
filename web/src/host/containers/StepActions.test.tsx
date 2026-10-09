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

const card = (view: string, y: number): CanvasCard => ({
  view,
  x: 0,
  y,
  w: 6,
  h: 8,
});

const json = (body: unknown) => new Response(JSON.stringify(body));

// The list says the canvas is empty; only the project detail holds `canvas`.
function setup(canvas: CanvasCard[]) {
  const calls: string[] = [];
  const puts: CanvasCard[][] = [];
  let finishSave = () => {};
  const saved = new Promise<void>((resolve) => (finishSave = resolve));
  const fetchImpl = async (path: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    calls.push(key);
    if (key === "GET /projects") return json([meta([])]);
    if (key === "GET /projects/p")
      return json({ meta: meta(canvas), datasets: [], views: [] });
    if (key === "POST /projects/p/views") {
      await saved;
      return json({ name: "closes", saved_at: "t" });
    }
    if (key === "PUT /projects/p/canvas") {
      const cards = JSON.parse(String(init?.body)) as CanvasCard[];
      puts.push(cards);
      return json(meta(cards));
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
  return { calls, puts, finishSave, onDone, qc };
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
    const { finishSave, onDone, qc } = setup([]);
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

  it("appends a card below the project's cards", async () => {
    const { puts, finishSave, qc } = setup([card("other", 0)]);
    finishSave();
    await pin(qc);
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toEqual([card("other", 0), card("closes", 8)]);
  });

  it("leaves the canvas alone when the view already has a card", async () => {
    const { calls, puts, finishSave, onDone, qc } = setup([card("closes", 0)]);
    finishSave();
    await pin(qc);
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith("Saved view closes"),
    );
    // Either the pin read the project and stopped, or it wrote the canvas.
    await waitFor(() =>
      expect(
        calls.some((c) => c === "GET /projects/p" || c.startsWith("PUT")),
      ).toBe(true),
    );
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(puts).toEqual([]);
  });
});
