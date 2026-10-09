import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Step } from "@/shared/api-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { keys } from "../api/keys";
import { ViewFrameContainer } from "./ViewFrameContainer";

const step: Step = {
  id: "s1",
  index: 0,
  kind: "prompt",
  prompt: "p",
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
    component_id: "inline",
    content_hash: "h",
    source: "export default () => null",
    initial_state: {},
    datasets: ["df"],
    snapshots: [],
  },
  created_at: "",
  duration_ms: 0,
};

function mount(onRepair = vi.fn()) {
  const fetchImpl = vi.fn(async (url: string) => {
    if (url.endsWith("/snapshots"))
      return new Response(JSON.stringify({ count: 1 }), { status: 200 });
    if (url.endsWith("/query"))
      return new Response(
        JSON.stringify({
          schema: [],
          rows: [],
          arrow_base64: null,
          row_count: 0,
          truncated: false,
        }),
        { status: 200 },
      );
    return new Response("[]", { status: 200 });
  });
  const qc = new QueryClient();
  const api = new ApiClient("t", fetchImpl);
  const tree = (dataVersion: string) => (
    <QueryClientProvider client={qc}>
      <ApiProvider client={api}>
        <ViewFrameContainer
          sessionId="sess"
          step={step}
          running={false}
          dataVersion={dataVersion}
          onRepair={onRepair}
        />
      </ApiProvider>
    </QueryClientProvider>
  );
  const { rerender } = render(tree("1:100"));
  const iframe = screen.getByTitle("View for step 1") as HTMLIFrameElement;
  const send = (data: unknown) =>
    window.dispatchEvent(
      new MessageEvent("message", { data, source: iframe.contentWindow }),
    );
  const setVersion = (v: string) => rerender(tree(v));
  return { fetchImpl, send, onRepair, iframe, setVersion, qc };
}

describe("ViewFrameContainer", () => {
  it("tells the view to refetch when kernel data may have changed", async () => {
    const { iframe, setVersion } = mount();
    const posted: unknown[] = [];
    vi.spyOn(iframe.contentWindow as Window, "postMessage").mockImplementation(
      (m: unknown) => posted.push(m),
    );
    setVersion("1:100");
    expect(posted).toEqual([]);
    setVersion("2:100");
    expect(posted).toEqual([{ type: "refresh", viewId: "s1" }]);
  });

  it("mounts on the frame's load when ready never arrives", async () => {
    const { iframe } = mount();
    const posted: unknown[] = [];
    vi.spyOn(iframe.contentWindow as Window, "postMessage").mockImplementation(
      (m: unknown) => posted.push(m),
    );
    await act(async () => {
      iframe.dispatchEvent(new Event("load"));
    });
    expect(posted).toEqual([
      expect.objectContaining({ type: "mount", viewId: "s1" }),
    ]);
  });

  it("posts snapshots for stateChanged", async () => {
    const { fetchImpl, send } = mount();
    await act(async () => {
      send({
        type: "stateChanged",
        viewId: "s1",
        state: { k: 1 },
        queries: [],
      });
    });
    await vi.waitFor(() =>
      expect(
        fetchImpl.mock.calls.some(
          ([u]) => u === "/sessions/sess/steps/s1/snapshots",
        ),
      ).toBe(true),
    );
  });

  it("refetches the session, and only the session, once a snapshot is saved", async () => {
    const { send, qc } = mount();
    qc.setQueryData(keys.session("sess"), {});
    qc.setQueryData(keys.status("sess"), {});
    await act(async () => {
      send({
        type: "stateChanged",
        viewId: "s1",
        state: { k: 1 },
        queries: [],
      });
    });
    await vi.waitFor(() =>
      expect(qc.getQueryState(keys.session("sess"))?.isInvalidated).toBe(true),
    );
    expect(qc.getQueryState(keys.status("sess"))?.isInvalidated).toBe(false);
  });

  it("shows the error overlay and starts a repair", async () => {
    const { send, onRepair } = mount();
    await act(async () => {
      send({
        type: "error",
        viewId: "s1",
        message: '"d3" is not available in views',
      });
    });
    expect(screen.getByText('"d3" is not available in views')).toBeTruthy();
    screen.getByRole("button", { name: "Fix this view" }).click();
    expect(onRepair).toHaveBeenCalledWith({
      step_id: "s1",
      error: '"d3" is not available in views',
    });
  });
});
