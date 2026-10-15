import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { QueryResult } from "@/shared/api-types";
import type { HostToRuntime } from "@/shared/bridge-types";
import type { JsonObject } from "@/shared/json";
import type { LibraryStatus } from "@/shared/library-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { dataVersion, useRestart, useSessionStatus } from "../api/hooks";
import { keys } from "../api/keys";
import { HostBridge } from "../bridge/HostBridge";
import { SharedStateHub } from "../bridge/SharedStateHub";
import { ViewHost } from "./ViewHost";

type Props = ComponentProps<typeof ViewHost>;

const INITIAL: JsonObject = { a: 1 };
const DATASETS = ["df"];

afterEach(() => vi.restoreAllMocks());

function mount(
  overrides: Partial<Props> = {},
  libraries?: () => Promise<Response>,
  readyOnConnect = true,
  client?: { qc: QueryClient; api: ApiClient },
) {
  const fetchImpl = vi.fn(async (url: string) =>
    url === "/libraries" && libraries !== undefined
      ? libraries()
      : new Response("[]", { status: 200 }),
  );
  const qc = client?.qc ?? new QueryClient();
  // Every view after the app's first finds the libraries answer already cached.
  if (libraries === undefined) qc.setQueryData(keys.libraries(), []);
  // One client for every render: `api` is a mount dependency, so a new one would remount.
  const api = client?.api ?? new ApiClient("t", fetchImpl);
  const posted: HostToRuntime[] = [];
  const tree = (props: Partial<Props>) => (
    <QueryClientProvider client={qc}>
      <ApiProvider client={api}>
        <ViewHost
          viewId="v1"
          sessionId="s"
          contentKey="h"
          source="export default () => null"
          initialState={INITIAL}
          datasets={DATASETS}
          restoreState={null}
          dataVersion="1"
          title="card"
          {...props}
        />
      </ApiProvider>
    </QueryClientProvider>
  );
  const view = render(tree(overrides));
  const iframe = screen.getByTitle(
    overrides.title ?? "card",
  ) as HTMLIFrameElement;
  const win = iframe.contentWindow;
  if (win === null) throw new Error("no frame window");
  win.postMessage = (m: HostToRuntime) => {
    posted.push(m);
    if (m.type === "connect" && readyOnConnect)
      queueMicrotask(() => send({ type: "ready", id: m.id }));
  };
  const send = (data: unknown) =>
    window.dispatchEvent(new MessageEvent("message", { data, source: win }));
  const rerender = (next: Partial<Props>) =>
    view.rerender(tree({ ...overrides, ...next }));
  // Once the frame has loaded, a remounted bridge posts its mount straight away.
  const load = () => iframe.dispatchEvent(new Event("load"));
  const mounts = () => posted.filter((m) => m.type === "mount");
  const ready = () => {
    const connection = posted.findLast((m) => m.type === "connect");
    if (connection?.type !== "connect") throw new Error("not connected");
    send({ type: "ready", id: connection.id });
  };
  return {
    posted,
    send,
    ready,
    rerender,
    load,
    mounts,
    qc,
    unmount: view.unmount,
  };
}

describe("ViewHost", () => {
  it("keeps its connection when the hub changes before ready arrives", async () => {
    const card = mount({ hub: new SharedStateHub() }, undefined, false);
    await act(async () => card.load());
    card.rerender({ hub: new SharedStateHub(), contentKey: "next" });
    await act(async () => card.ready());
    expect(card.posted.filter((m) => m.type === "connect")).toHaveLength(1);
    expect(card.mounts()).toHaveLength(1);
  });

  it("uses the new kernel generation after restart invalidates status, while the old query is pending", async () => {
    const qc = new QueryClient();
    let pid = 100;
    const requests: ((response: Response) => void)[] = [];
    const api = new ApiClient("t", (url) => {
      if (url.endsWith("/query"))
        return new Promise<Response>((resolve) => requests.push(resolve));
      if (url.endsWith("/restart")) {
        pid = 200;
        return Promise.resolve(
          new Response(
            JSON.stringify({ replayed: 0, failed_step: null, error: null }),
          ),
        );
      }
      return Promise.resolve(
        new Response(
          JSON.stringify({
            kernel: { status: "idle", pid, replay_needed: false },
          }),
        ),
      );
    });
    const hooks = renderHook(
      () => ({
        status: useSessionStatus("s", false),
        restart: useRestart("s"),
      }),
      {
        wrapper: ({ children }) => (
          <QueryClientProvider client={qc}>
            <ApiProvider client={api}>{children}</ApiProvider>
          </QueryClientProvider>
        ),
      },
    );
    await waitFor(() =>
      expect(hooks.result.current.status.data?.kernel.pid).toBe(100),
    );
    const card = mount({ dataVersion: dataVersion([], 100) }, undefined, true, {
      qc,
      api,
    });
    const ask = (id: string) =>
      card.send({ type: "query", viewId: "v1", id, spec: { dataset: "df" } });
    await act(async () => ask("old"));
    await act(async () => hooks.result.current.restart.mutateAsync());
    await waitFor(() =>
      expect(hooks.result.current.status.data?.kernel.pid).toBe(200),
    );
    card.rerender({
      dataVersion: dataVersion(
        [],
        hooks.result.current.status.data?.kernel.pid,
      ),
    });
    await act(async () => ask("new"));
    expect(requests).toHaveLength(2);
    await act(async () =>
      requests.forEach((resolve) =>
        resolve(
          new Response(
            JSON.stringify({
              schema: [],
              rows: [],
              arrow_base64: null,
              row_count: 0,
              truncated: false,
            }),
          ),
        ),
      ),
    );
    await waitFor(() =>
      expect(card.posted.filter((m) => m.type === "queryResult")).toHaveLength(
        2,
      ),
    );
  });

  it("shares concurrent card queries through one server request", async () => {
    const qc = new QueryClient();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    const result: QueryResult = {
      schema: [],
      rows: [{ a: 1 }],
      arrow_base64: null,
      row_count: 1,
      truncated: false,
    };
    const fetch = vi.fn(async () => {
      await gate;
      return new Response(JSON.stringify(result));
    });
    const api = new ApiClient("t", fetch);
    const cards = Array.from({ length: 6 }, (_, i) =>
      mount({ viewId: `v${i}`, title: `card ${i}` }, undefined, true, {
        qc,
        api,
      }),
    );
    await act(async () => {
      cards.forEach((card, i) =>
        card.send({
          type: "query",
          viewId: `v${i}`,
          id: `q${i}`,
          spec: { dataset: "df" },
        }),
      );
    });
    expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => release());
    await waitFor(() =>
      cards.forEach((card, i) =>
        expect(card.posted).toContainEqual({
          type: "queryResult",
          viewId: `v${i}`,
          id: `q${i}`,
          ok: true,
          result,
        }),
      ),
    );
    await waitFor(() =>
      expect(
        qc.getQueryCache().findAll({
          queryKey: ["sessions", "s", "queries"],
        }),
      ).toHaveLength(0),
    );
  });

  it("separates specs and sessions and starts a fresh generation while a query is pending", async () => {
    const qc = new QueryClient();
    const requests: {
      url: string;
      spec: unknown;
      resolve: (response: Response) => void;
    }[] = [];
    const api = new ApiClient(
      "t",
      (url, init) =>
        new Promise<Response>((resolve) =>
          requests.push({ url, spec: JSON.parse(String(init?.body)), resolve }),
        ),
    );
    const card = mount({}, undefined, true, { qc, api });
    const other = mount(
      { viewId: "v2", sessionId: "other", title: "other" },
      undefined,
      true,
      { qc, api },
    );
    const ask = (id: string, spec = { dataset: "df", limit: 1 }) =>
      card.send({ type: "query", viewId: "v1", id, spec });
    await act(async () => {
      ask("old");
      ask("different", { dataset: "df", limit: 2 });
      other.send({
        type: "query",
        viewId: "v2",
        id: "other",
        spec: { dataset: "df", limit: 1 },
      });
    });
    expect(requests.map((r) => r.url)).toEqual([
      "/sessions/s/query",
      "/sessions/s/query",
      "/sessions/other/query",
    ]);
    card.rerender({ dataVersion: "2" });
    expect(card.posted.at(-1)).toMatchObject({ type: "refresh" });
    await act(async () => ask("new"));
    expect(requests).toHaveLength(4);
    await act(async () =>
      requests.forEach((r, i) =>
        r.resolve(
          new Response(
            JSON.stringify({
              schema: [],
              rows: [{ a: i }],
              arrow_base64: null,
              row_count: 1,
              truncated: false,
            }),
          ),
        ),
      ),
    );
    await waitFor(() =>
      expect(card.posted).toContainEqual(
        expect.objectContaining({
          id: "new",
          result: expect.objectContaining({ rows: [{ a: 3 }] }),
        }),
      ),
    );
  });

  it("shares failures without retrying and allows a later request to recover", async () => {
    const qc = new QueryClient();
    let release: () => void = () => undefined;
    const gate = new Promise<void>((resolve) => (release = resolve));
    let calls = 0;
    const api = new ApiClient("t", async () => {
      const call = calls++;
      await gate;
      return new Response(
        JSON.stringify(
          call === 0
            ? { detail: "bad spec" }
            : {
                schema: [],
                rows: [],
                arrow_base64: null,
                row_count: 0,
                truncated: false,
              },
        ),
        { status: call === 0 ? 400 : 200 },
      );
    });
    const card = mount({}, undefined, true, { qc, api });
    const ask = (id: string) =>
      card.send({ type: "query", viewId: "v1", id, spec: { dataset: "df" } });
    await act(async () => {
      ask("a");
      ask("b");
    });
    expect(calls).toBe(1);
    await act(async () => release());
    await waitFor(() =>
      expect(card.posted.filter((m) => m.type === "queryResult")).toHaveLength(
        2,
      ),
    );
    expect(card.posted).toContainEqual({
      type: "queryResult",
      viewId: "v1",
      id: "a",
      ok: false,
      error: "400: bad spec",
    });
    await act(async () => ask("c"));
    await waitFor(() =>
      expect(card.posted).toContainEqual(
        expect.objectContaining({ id: "c", ok: true }),
      ),
    );
    expect(calls).toBe(2);
  });

  it("mounts once when ready arrives after the frame loads", async () => {
    const { ready, load, mounts } = mount({}, undefined, false);
    await act(async () => load());
    expect(mounts()).toHaveLength(0);
    await act(async () => ready());
    expect(mounts()).toHaveLength(1);
  });

  it("mounts after ready and forwards stateChanged", async () => {
    const onStateChanged = vi.fn();
    const { posted, send, load } = mount({ onStateChanged });
    await act(async () => load());
    expect(posted.find((m) => m.type === "mount")).toMatchObject({
      type: "mount",
      viewId: "v1",
      datasets: ["df"],
      initialState: { a: 1 },
    });
    await act(async () =>
      send({
        type: "stateChanged",
        viewId: "v1",
        state: { a: 2 },
        queries: [],
      }),
    );
    expect(onStateChanged).toHaveBeenCalledWith({ a: 2 }, []);
  });

  it("sends restore when restoreState changes", async () => {
    const { posted, rerender, load, mounts } = mount();
    await act(async () => load());
    rerender({ restoreState: { k: 2 } });
    expect(posted.at(-1)).toMatchObject({
      type: "restore",
      viewId: "v1",
      state: { k: 2 },
    });
    expect(mounts()).toHaveLength(1);
  });

  it("delivers a restore selected before libraries and readiness arrive", async () => {
    let release: (response: Response) => void = () => undefined;
    const libraries = new Promise<Response>((resolve) => (release = resolve));
    const card = mount({}, () => libraries, false);
    await act(async () => card.load());
    card.rerender({ restoreState: { n: 7 } });
    expect(card.posted).toHaveLength(0);
    await act(async () => release(new Response("[]")));
    await waitFor(() => expect(card.posted).toHaveLength(1));
    await act(async () => card.ready());
    expect(card.posted.map((m) => m.type)).toEqual([
      "connect",
      "mount",
      "restore",
    ]);
    expect(card.posted.at(-1)).toMatchObject({ state: { n: 7 } });
  });

  it("remounts on a new contentKey only, with the latest source", async () => {
    const { rerender, load, mounts, posted } = mount();
    const loadedMessages = () => posted.filter((m) => m.type === "connect");
    await act(async () => load());
    rerender({
      source: "export default () => 1",
      initialState: { a: 1 },
      datasets: ["df"],
    });
    expect(mounts()).toHaveLength(1);
    await act(async () =>
      rerender({ source: "export default () => 2", contentKey: "h2" }),
    );
    expect(mounts()).toHaveLength(2);
    expect(loadedMessages()).toHaveLength(1);
    expect(mounts()[1]).toMatchObject({ source: "export default () => 2" });
  });

  it("fans shared keys out through the hub, both ways", async () => {
    const hub = new SharedStateHub();
    const otherMerge = vi.fn();
    hub.register("other", {}, otherMerge);
    const { posted, send, load } = mount({ hub });
    await act(async () => load());
    await act(async () =>
      send({
        type: "stateChanged",
        viewId: "v1",
        state: { "shared:k": 1 },
        queries: [],
      }),
    );
    expect(otherMerge).toHaveBeenCalledWith({ "shared:k": 1 });
    hub.report("other", { "shared:k": 2 });
    expect(posted.at(-1)).toMatchObject({
      type: "merge",
      viewId: "v1",
      state: { "shared:k": 2 },
    });
  });

  it("leaves the hub when it unmounts", async () => {
    const hub = new SharedStateHub();
    hub.register("other", {}, () => undefined);
    // Watched on the bridge, not the frame: an unmounted iframe has no window to post to.
    const merge = vi.spyOn(HostBridge.prototype, "merge");
    const { load, unmount } = mount({ hub });
    await act(async () => load());
    hub.report("other", { "shared:k": 1 });
    expect(merge).toHaveBeenCalledTimes(1);
    unmount();
    hub.report("other", { "shared:k": 2 });
    expect(merge).toHaveBeenCalledTimes(1);
  });

  it("fills its container instead of the fixed height with fill", () => {
    mount({ fill: true });
    const iframe = screen.getByTitle("card");
    expect(iframe.className).toContain("h-full");
    expect(iframe.className).not.toContain("h-[420px]");
  });

  it("offers no repair without onFix", async () => {
    const { send } = mount();
    await act(async () =>
      send({ type: "error", viewId: "v1", message: "boom" }),
    );
    expect(screen.getByText("boom")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Fix this view" })).toBeNull();
  });

  it("mounts once, after the libraries answer, with the enabled ones", async () => {
    const highcharts: LibraryStatus = {
      id: "highcharts",
      enabled: true,
      reason: null,
      license: "hk",
      entry: "/libs/highcharts/highstock.js",
    };
    const scichart: LibraryStatus = {
      id: "scichart",
      enabled: true,
      reason: null,
      license: "sk",
      entry: "/libs/scichart/index.min.mjs",
    };
    let statuses = [highcharts, scichart];
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    const { load, mounts, rerender, qc } = mount({}, async () => {
      await held;
      return new Response(JSON.stringify(statuses));
    });
    await act(async () => load());
    expect(mounts()).toHaveLength(0);
    await act(async () => release());
    await waitFor(() => expect(mounts()).toHaveLength(1));
    // Only SciChart reads its key inside the frame.
    expect(mounts()[0]?.licensed).toEqual([
      { id: "highcharts", entry: highcharts.entry, license: null },
      { id: "scichart", entry: scichart.entry, license: "sk" },
    ]);
    // A refetch, as a refocus or another view's first mount can start, leaves this one alone.
    statuses = [{ ...highcharts, enabled: false }, scichart];
    await act(() => qc.invalidateQueries({ queryKey: keys.libraries() }));
    rerender({ source: "export default () => 1" });
    expect(mounts()).toHaveLength(1);
    // New content mounts with the latest answer.
    await act(async () => rerender({ contentKey: "h2" }));
    expect(mounts()[1]?.licensed).toEqual([
      { id: "scichart", entry: scichart.entry, license: "sk" },
    ]);
  });

  it("mounts without licensed libraries when the answer fails", async () => {
    let release: () => void = () => undefined;
    const held = new Promise<void>((resolve) => (release = resolve));
    let calls = 0;
    const { load, mounts, qc } = mount({}, async () => {
      calls += 1;
      if (calls > 1) await held;
      return new Response("{}", { status: 500 });
    });
    await act(async () => load());
    // No retries: a failed answer must not hold the view back.
    await waitFor(() => expect(mounts()).toHaveLength(1));
    expect(mounts()[0]?.licensed).toEqual([]);
    // With no data, a refetch puts the status back to pending until it answers. React Query
    // notifies on a timer, so each step waits for the render it causes.
    const settle = () => act(() => new Promise((r) => setTimeout(r, 20)));
    void qc.invalidateQueries({ queryKey: keys.libraries() });
    await settle();
    expect(qc.getQueryState(keys.libraries())?.status).toBe("pending");
    release();
    await settle();
    expect(qc.getQueryState(keys.libraries())?.status).toBe("error");
    expect(mounts()).toHaveLength(1);
  });
});
