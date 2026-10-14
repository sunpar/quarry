import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { useLayoutEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Project, SavedView } from "@/shared/api-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { keys } from "../api/keys";
import { HostBridge } from "../bridge/HostBridge";
import { CanvasPage } from "./CanvasPage";

afterEach(() => vi.restoreAllMocks());

vi.mock("react-grid-layout", async (importOriginal) => ({
  ...(await importOriginal<typeof import("react-grid-layout")>()),
  useContainerWidth: () => ({
    width: 1200,
    mounted: true,
    containerRef: { current: null },
  }),
}));

const saved: SavedView = {
  meta: {
    name: "table",
    description: "",
    datasets: [],
    component_id: "inline",
    saved_at: "t1",
    source_session: "first",
    source_step: "step",
  },
  source: "export default () => null",
  state: {},
  queries: [],
};
const project: Project = {
  meta: {
    slug: "p",
    name: "p",
    description: "",
    created_at: "",
    updated_at: "",
    canvas: [{ view: "table", x: 0, y: 0, w: 6, h: 8 }],
  },
  datasets: [],
  views: [saved.meta],
};

describe("canvas host identity", () => {
  it("connects and mounts a replacement frame that loads before the previous host cleanup", async () => {
    const connect = vi.spyOn(HostBridge.prototype, "connect");
    const qc = new QueryClient();
    const status = {
      kernel: { status: "idle", pid: 100, replay_needed: false },
      busy: false,
      running_step: null,
      last_error: null,
    };
    const session = {
      meta: {
        id: "first",
        title: "",
        created_at: "",
        provider: { name: "fake", model: "fake" },
      },
      steps: [],
    };
    qc.setQueryData(keys.libraries(), []);
    qc.setQueryData(keys.savedView("p", "table"), saved);
    for (const id of ["first", "next"]) {
      qc.setQueryData(keys.session(id), session);
      qc.setQueryData(keys.status(id), status);
      qc.setQueryData([...keys.datasets(id), "0:100"], []);
    }
    const api = new ApiClient(
      "t",
      async (url) =>
        new Response(
          JSON.stringify(
            url.endsWith("/status")
              ? status
              : url.endsWith("/datasets") || url === "/libraries"
                ? []
                : url.startsWith("/projects")
                  ? saved
                  : session,
          ),
        ),
    );
    function Caller({ sessionId }: { sessionId: string }) {
      useLayoutEffect(() => {
        screen.getByTitle("Canvas card table").dispatchEvent(new Event("load"));
      }, [sessionId]);
      return <CanvasPage project={project} sessionId={sessionId} />;
    }
    const tree = (sessionId: string) => (
      <QueryClientProvider client={qc}>
        <ApiProvider client={api}>
          <Caller sessionId={sessionId} />
        </ApiProvider>
      </QueryClientProvider>
    );
    const view = render(tree("first"));
    const first = connect.mock.instances[0];
    const oldFrame = screen.getByTitle("Canvas card table");
    view.rerender(tree("next"));
    const frame = screen.getByTitle("Canvas card table") as HTMLIFrameElement;
    expect(frame).not.toBe(oldFrame);
    expect(connect).toHaveBeenCalledTimes(2);
    expect(connect.mock.instances[1]).not.toBe(first);
    const posted: unknown[] = [];
    vi.spyOn(frame.contentWindow as Window, "postMessage").mockImplementation(
      (m: unknown) => posted.push(m),
    );
    await act(async () =>
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "ready" },
          source: frame.contentWindow,
        }),
      ),
    );
    expect(posted).toEqual([
      expect.objectContaining({ type: "mount", viewId: "canvas:table" }),
    ]);
    connect.mockRestore();
  });
});
