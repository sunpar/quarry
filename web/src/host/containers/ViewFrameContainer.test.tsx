import {
  QueryClient,
  QueryClientProvider,
  skipToken,
  useQuery,
} from "@tanstack/react-query";
import { act, fireEvent, render, screen } from "@testing-library/react";
import { StrictMode, useLayoutEffect } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Session, Snapshot, Step } from "@/shared/api-types";
import type { HostToRuntime } from "@/shared/bridge-types";
import type { JsonObject } from "@/shared/json";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { keys } from "../api/keys";
import { HostBridge } from "../bridge/HostBridge";
import { ViewFrameContainer } from "./ViewFrameContainer";

afterEach(() => vi.restoreAllMocks());

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

const cachedSession = (snapshots: Snapshot[]): Session => ({
  meta: {
    id: "sess",
    title: "t",
    created_at: "",
    provider: { name: "f", model: "m" },
  },
  steps: [{ ...step, view: step.view && { ...step.view, snapshots } }],
});

// Passes the step from the cached session once there is one, as the session page does, so
// recorded snapshots and refetches reach the scrubber.
function CachedStep(props: { dataVersion: string; onRepair: () => void }) {
  const { data } = useQuery<Session>({
    queryKey: keys.session("sess"),
    queryFn: skipToken,
  });
  return (
    <ViewFrameContainer
      sessionId="sess"
      step={data?.steps[0] ?? step}
      running={false}
      {...props}
    />
  );
}

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
  // ViewHost mounts once the libraries answer is in; these tests start with it cached.
  qc.setQueryData(keys.libraries(), []);
  const api = new ApiClient("t", fetchImpl);
  const tree = (dataVersion: string) => (
    <QueryClientProvider client={qc}>
      <ApiProvider client={api}>
        <CachedStep dataVersion={dataVersion} onRepair={onRepair} />
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
  it("mounts once under StrictMode when load precedes the passive listener", async () => {
    const qc = new QueryClient();
    qc.setQueryData(keys.libraries(), []);
    const api = new ApiClient("t", async () => new Response("[]"));
    const posted: HostToRuntime[] = [];
    const loaded = new WeakSet<Element>();
    function Caller() {
      useLayoutEffect(() => {
        const frame = screen.getByTitle("View for step 1") as HTMLIFrameElement;
        if (loaded.has(frame)) return;
        loaded.add(frame);
        (frame.contentWindow as Window).postMessage = (m) => posted.push(m);
        frame.dispatchEvent(new Event("load"));
      }, []);
      return (
        <ViewFrameContainer
          sessionId="s"
          step={step}
          running={false}
          dataVersion="1"
          onRepair={() => undefined}
        />
      );
    }
    render(
      <StrictMode>
        <QueryClientProvider client={qc}>
          <ApiProvider client={api}>
            <Caller />
          </ApiProvider>
        </QueryClientProvider>
      </StrictMode>,
    );
    const connects = posted.filter((m) => m.type === "connect");
    expect(connects).toHaveLength(2);
    expect(connects[0]?.id).not.toBe(connects[1]?.id);
    const frame = screen.getByTitle("View for step 1") as HTMLIFrameElement;
    const acknowledge = (id: string | undefined) =>
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "ready", id },
          source: frame.contentWindow,
        }),
      );
    await act(async () => acknowledge(connects[0]?.id));
    expect(posted.filter((m) => m.type === "mount")).toHaveLength(0);
    await act(async () => acknowledge(connects[1]?.id));
    expect(posted.filter((m) => m.type === "mount")).toHaveLength(1);
  });

  it("connects the replacement host when its frame loads before passive cleanup", async () => {
    const connect = vi.spyOn(HostBridge.prototype, "connect");
    const qc = new QueryClient();
    qc.setQueryData(keys.libraries(), []);
    const api = new ApiClient("t", async () => new Response("[]"));
    const posted: HostToRuntime[] = [];
    function Caller({ sessionId }: { sessionId: string }) {
      useLayoutEffect(() => {
        const frame = screen.getByTitle("View for step 1") as HTMLIFrameElement;
        (frame.contentWindow as Window).postMessage = (m) => posted.push(m);
        frame.dispatchEvent(new Event("load"));
      }, [sessionId]);
      return (
        <ViewFrameContainer
          sessionId={sessionId}
          step={step}
          running={false}
          dataVersion="1"
          onRepair={() => undefined}
        />
      );
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
    const oldFrame = screen.getByTitle("View for step 1");
    expect(first).toBeDefined();
    view.rerender(tree("next"));
    const newFrame = screen.getByTitle("View for step 1") as HTMLIFrameElement;
    expect(newFrame).not.toBe(oldFrame);
    expect(connect).toHaveBeenCalledTimes(2);
    expect(connect.mock.instances[1]).not.toBe(first);
    const connection = posted.findLast((m) => m.type === "connect");
    if (connection?.type !== "connect") throw new Error("not connected");
    posted.length = 0;
    await act(async () =>
      window.dispatchEvent(
        new MessageEvent("message", {
          data: { type: "ready", id: connection.id },
          source: newFrame.contentWindow,
        }),
      ),
    );
    expect(posted).toEqual([
      expect.objectContaining({ type: "mount", viewId: "s1" }),
    ]);
    connect.mockRestore();
  });

  it("tells the view to refetch when kernel data may have changed", async () => {
    const { iframe, setVersion } = mount();
    const posted: HostToRuntime[] = [];
    vi.spyOn(iframe.contentWindow as Window, "postMessage").mockImplementation(
      (m: HostToRuntime) => posted.push(m),
    );
    setVersion("1:100");
    expect(posted).toEqual([]);
    setVersion("2:100");
    expect(posted).toEqual([{ type: "refresh", viewId: "s1" }]);
  });

  it("connects on frame load and mounts after the acknowledgment", async () => {
    const { iframe, send } = mount();
    const posted: HostToRuntime[] = [];
    vi.spyOn(iframe.contentWindow as Window, "postMessage").mockImplementation(
      (m: HostToRuntime) => posted.push(m),
    );
    await act(async () => {
      iframe.dispatchEvent(new Event("load"));
    });
    expect(posted).toEqual([
      expect.objectContaining({ type: "connect", viewId: "s1" }),
    ]);
    const connection = posted[0];
    if (connection?.type !== "connect") throw new Error("not connected");
    await act(async () => send({ type: "ready", id: connection.id }));
    expect(posted).toEqual([
      expect.objectContaining({ type: "connect", viewId: "s1" }),
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

  it("appends a saved snapshot to the cached session without refetching", async () => {
    const { send, qc } = mount();
    qc.setQueryData(keys.session("sess"), cachedSession([]));
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
      expect(
        qc.getQueryData<Session>(keys.session("sess"))?.steps[0]?.view
          ?.snapshots,
      ).toEqual([{ ts: expect.any(String), state: { k: 1 }, queries: [] }]),
    );
    expect(qc.getQueryState(keys.session("sess"))?.isInvalidated).toBe(false);
    expect(qc.getQueryState(keys.status("sess"))?.isInvalidated).toBe(false);
  });

  it("replaces the cached last snapshot when the state repeats", async () => {
    const { send, qc } = mount();
    qc.setQueryData(
      keys.session("sess"),
      cachedSession([{ ts: "t0", state: { k: 1 }, queries: [] }]),
    );
    const cached = () =>
      qc.getQueryData<Session>(keys.session("sess"))?.steps[0]?.view?.snapshots;
    const report = (state: JsonObject) =>
      act(async () => {
        send({
          type: "stateChanged",
          viewId: "s1",
          state,
          queries: [{ dataset: "df" }],
        });
      });
    await report({ k: 1 });
    await vi.waitFor(() =>
      expect(cached()).toEqual([
        {
          ts: expect.any(String),
          state: { k: 1 },
          queries: [{ dataset: "df" }],
        },
      ]),
    );
    expect(cached()?.[0]?.ts).not.toBe("t0");
    await report({ k: true });
    await vi.waitFor(() =>
      expect(cached()?.map((s) => s.state)).toEqual([{ k: 1 }, { k: true }]),
    );
  });

  describe("after a pick in the scrubber", () => {
    const a: Snapshot = { ts: "t0", state: { k: "a" }, queries: [] };
    const b: Snapshot = { ts: "t1", state: { k: "b" }, queries: [] };
    // The query cache tells its observers on a timer, so wait one out before reading the screen.
    const cache = (qc: QueryClient, snapshots: Snapshot[]) =>
      act(async () => {
        qc.setQueryData(keys.session("sess"), cachedSession(snapshots));
        await new Promise((resolve) => setTimeout(resolve, 0));
      });
    const pickFirst = () =>
      fireEvent.change(screen.getByRole("slider"), { target: { value: "0" } });

    it("moves to the latest when the view reports the last state again", async () => {
      const { send, qc } = mount();
      await cache(qc, [a, b]);
      pickFirst();
      expect(screen.getByText("1 of 2")).toBeTruthy();
      const slider = screen.getByRole("slider");
      await act(async () => {
        send({
          type: "stateChanged",
          viewId: "s1",
          state: b.state,
          queries: [],
        });
      });
      // The report replaces the last snapshot, so the count stays 2.
      await vi.waitFor(() => {
        const cached = qc.getQueryData<Session>(keys.session("sess"));
        expect(cached?.steps[0]?.view?.snapshots[1]?.ts).not.toBe("t1");
        expect(screen.getByText("2 of 2")).toBeTruthy();
      });
      // The same input, so a report that lands mid-drag keeps the drag and focus.
      expect(screen.getByRole("slider")).toBe(slider);
    });

    it("keeps the pick when a refetch brings the same snapshots", async () => {
      const { qc } = mount();
      await cache(qc, [a, b]);
      pickFirst();
      // The server stamps its own ts, so a refetch after a recorded snapshot changes the last one's.
      await cache(qc, [a, { ...b, ts: "t1-server" }]);
      expect(screen.getByText("1 of 2")).toBeTruthy();
    });
  });

  it("leaves an uncached session uncached after a snapshot", async () => {
    const { fetchImpl, send, qc } = mount();
    await act(async () => {
      send({
        type: "stateChanged",
        viewId: "s1",
        state: { k: 1 },
        queries: [],
      });
    });
    await vi.waitFor(() =>
      expect(fetchImpl.mock.calls.some(([u]) => u.endsWith("/snapshots"))).toBe(
        true,
      ),
    );
    // Past the response and its `.then`, where a wrong write would happen.
    await act(async () => {
      await new Promise((resolve) => setTimeout(resolve, 50));
    });
    expect(qc.getQueryData(keys.session("sess"))).toBeUndefined();
  });

  it("shows the error overlay and starts a repair", async () => {
    const { send, onRepair } = mount();
    await act(async () => {
      send({
        type: "error",
        viewId: "s1",
        message: '"lodash" is not available in views',
      });
    });
    expect(screen.getByText('"lodash" is not available in views')).toBeTruthy();
    screen.getByRole("button", { name: "Fix this view" }).click();
    expect(onRepair).toHaveBeenCalledWith({
      step_id: "s1",
      error: '"lodash" is not available in views',
    });
  });
});
