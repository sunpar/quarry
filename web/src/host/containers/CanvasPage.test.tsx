import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { DatasetMeta, Project, Session, Step } from "@/shared/api-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { CanvasPage, cardsToLayout, layoutToCards } from "./CanvasPage";

// jsdom measures nothing, so the grid gets a width; the frame is ViewHost's own business.
vi.mock("react-grid-layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-grid-layout")>()),
  useContainerWidth: () => ({
    width: 1200,
    mounted: true,
    containerRef: { current: null },
  }),
}));
vi.mock("./ViewHost", () => ({
  ViewHost: ({ title }: { title: string }) => <p>{title} mounted</p>,
}));

describe("canvas layout mapping", () => {
  it("round-trips cards through the grid layout", () => {
    const cards = [
      { view: "a", x: 0, y: 0, w: 6, h: 8 },
      { view: "b", x: 6, y: 0, w: 6, h: 4 },
    ];
    const layout = cardsToLayout(cards);
    expect(layout[0]).toMatchObject({
      i: "a",
      x: 0,
      y: 0,
      w: 6,
      h: 8,
      minW: 3,
      minH: 3,
    });
    expect(layoutToCards(layout)).toEqual(cards);
  });
});

const project: Project = {
  meta: {
    slug: "p",
    name: "Momentum",
    description: "",
    created_at: "",
    updated_at: "",
    canvas: [{ view: "table", x: 0, y: 0, w: 6, h: 8 }],
  },
  datasets: [],
  views: [
    {
      name: "table",
      description: "",
      datasets: ["df"],
      component_id: "data-table",
      saved_at: "t1",
      source_session: "s1",
      source_step: "st1",
    },
  ],
};

// The step that wrote `df` is still on the record, whatever the kernel holds now.
const wrote: Partial<Step> = {
  id: "st1",
  index: 0,
  status: "ok",
  writes: ["df"],
};
const session: Session = {
  meta: {
    id: "s1",
    title: "",
    created_at: "",
    provider: { name: "fake", model: "fake" },
  },
  steps: [wrote as Step],
};

// A path in `refused` answers 500 with its detail.
function renderCanvas(
  listed: string[],
  shown: Project = project,
  refused: Record<string, string> = {},
) {
  const datasets: Partial<DatasetMeta>[] = listed.map((name) => ({ name }));
  const answers: Record<string, unknown> = {
    "/sessions/s1": session,
    "/sessions/s1/status": {
      session_id: "s1",
      running_step: null,
      busy: false,
      kernel: { status: "idle", pid: 1, replay_needed: false },
      last_error: null,
    },
    "/sessions/s1/datasets": datasets,
    "/projects/p/views/table": {
      meta: project.views[0],
      source: "",
      state: {},
      queries: [],
    },
  };
  const puts: string[] = [];
  const fetchImpl = async (path: string, init?: RequestInit) => {
    if (init?.method === "PUT") puts.push(`${path} ${String(init.body)}`);
    if (path in refused)
      return new Response(JSON.stringify({ detail: refused[path] }), {
        status: 500,
      });
    return new Response(JSON.stringify(answers[path] ?? {}));
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const page = (p: Project) => (
    <QueryClientProvider client={qc}>
      <ApiProvider client={new ApiClient("t", fetchImpl)}>
        <CanvasPage project={p} sessionId="s1" />
      </ApiProvider>
    </QueryClientProvider>
  );
  const { rerender } = render(page(shown));
  return Object.assign(qc, { puts, show: (p: Project) => rerender(page(p)) });
}

describe("CanvasPage availability", () => {
  it("offers Load when the kernel no longer holds a dataset a step wrote", async () => {
    const qc = renderCanvas([]);
    // Every query answers first: before the session loads, any card lacks its datasets.
    await waitFor(() => expect(qc.isFetching()).toBe(0));
    expect(screen.getByRole("button", { name: "Load" })).toBeDefined();
    expect(screen.queryByText("Canvas card table mounted")).toBeNull();
  });

  it("adds a card pinned after the canvas opened", async () => {
    const empty = { ...project, meta: { ...project.meta, canvas: [] } };
    const canvas = renderCanvas(["df"], empty);
    expect(screen.queryByText("Canvas card table mounted")).toBeNull();
    canvas.show(project); // the pin's refetch brings the card
    expect(await screen.findByText("Canvas card table mounted")).toBeDefined();
  });

  it("mounts the view when the kernel holds its datasets", async () => {
    renderCanvas(["df"]);
    expect(await screen.findByText("Canvas card table mounted")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Load" })).toBeNull();
  });
});

describe("CanvasPage failures", () => {
  it("shows a saved view's load failure inside its card", async () => {
    renderCanvas(["df"], project, {
      "/projects/p/views/table": "view file unreadable",
    });
    expect(await screen.findByText("500: view file unreadable")).toBeDefined();
    expect(screen.queryByText("Canvas card table mounted")).toBeNull();
  });

  it("lets a card whose view left the project be removed", async () => {
    const card = { view: "gone", x: 6, y: 0, w: 6, h: 8 };
    const shown = {
      ...project,
      meta: { ...project.meta, canvas: [...project.meta.canvas, card] },
    };
    const canvas = renderCanvas(["df"], shown);
    fireEvent.click(
      await screen.findByRole("button", { name: "Remove gone from canvas" }),
    );
    expect(screen.queryByText("gone")).toBeNull();
    await waitFor(() =>
      expect(canvas.puts).toEqual([
        `/projects/p/canvas ${JSON.stringify(project.meta.canvas)}`,
      ]),
    );
  });

  it("dismisses a failed recall", async () => {
    renderCanvas([], project, { "/sessions/s1/recall": "kernel died" });
    fireEvent.click(await screen.findByRole("button", { name: "Load" }));
    expect(await screen.findByText("500: kernel died")).toBeDefined();
    fireEvent.click(screen.getByRole("button", { name: "Dismiss" }));
    await waitFor(() =>
      expect(screen.queryByText("500: kernel died")).toBeNull(),
    );
  });
});
