import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
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

function renderCanvas(listed: string[]) {
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
  const fetchImpl = async (path: string) =>
    new Response(JSON.stringify(answers[path] ?? {}));
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ApiProvider client={new ApiClient("t", fetchImpl)}>
        <CanvasPage project={project} sessionId="s1" />
      </ApiProvider>
    </QueryClientProvider>,
  );
  return qc;
}

describe("CanvasPage availability", () => {
  it("offers Load when the kernel no longer holds a dataset a step wrote", async () => {
    const qc = renderCanvas([]);
    // Every query answers first: before the session loads, any card lacks its datasets.
    await waitFor(() => expect(qc.isFetching()).toBe(0));
    expect(screen.getByRole("button", { name: "Load" })).toBeDefined();
    expect(screen.queryByText("Canvas card table mounted")).toBeNull();
  });

  it("mounts the view when the kernel holds its datasets", async () => {
    renderCanvas(["df"]);
    expect(await screen.findByText("Canvas card table mounted")).toBeDefined();
    expect(screen.queryByRole("button", { name: "Load" })).toBeNull();
  });
});
