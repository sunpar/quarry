import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import type { ComponentProps } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { HostToRuntime } from "@/shared/bridge-types";
import type { JsonObject } from "@/shared/json";
import type { LibraryStatus } from "@/shared/library-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
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
) {
  const fetchImpl = vi.fn(async (url: string) =>
    url === "/libraries" && libraries !== undefined
      ? libraries()
      : new Response("[]", { status: 200 }),
  );
  const qc = new QueryClient();
  // Every view after the app's first finds the libraries answer already cached.
  if (libraries === undefined) qc.setQueryData(keys.libraries(), []);
  // One client for every render: `api` is a mount dependency, so a new one would remount.
  const api = new ApiClient("t", fetchImpl);
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
  const iframe = screen.getByTitle("card") as HTMLIFrameElement;
  const win = iframe.contentWindow;
  if (win === null) throw new Error("no frame window");
  win.postMessage = (m: HostToRuntime) => posted.push(m);
  const send = (data: unknown) =>
    window.dispatchEvent(new MessageEvent("message", { data, source: win }));
  const rerender = (next: Partial<Props>) =>
    view.rerender(tree({ ...overrides, ...next }));
  // Once the frame has loaded, a remounted bridge posts its mount straight away.
  const load = () => iframe.dispatchEvent(new Event("load"));
  const mounts = () => posted.filter((m) => m.type === "mount");
  return { posted, send, rerender, load, mounts, qc, unmount: view.unmount };
}

describe("ViewHost", () => {
  it("mounts after ready and forwards stateChanged", async () => {
    const onStateChanged = vi.fn();
    const { posted, send } = mount({ onStateChanged });
    await act(async () => send({ type: "ready" }));
    expect(posted[0]).toMatchObject({
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
    const { posted, send, rerender, load, mounts } = mount();
    await act(async () => send({ type: "ready" }));
    await act(async () => load());
    rerender({ restoreState: { k: 2 } });
    expect(posted.at(-1)).toMatchObject({
      type: "restore",
      viewId: "v1",
      state: { k: 2 },
    });
    expect(mounts()).toHaveLength(1);
  });

  it("remounts on a new contentKey only, with the latest source", async () => {
    const { send, rerender, load, mounts } = mount();
    await act(async () => send({ type: "ready" }));
    await act(async () => load());
    rerender({
      source: "export default () => 1",
      initialState: { a: 1 },
      datasets: ["df"],
    });
    expect(mounts()).toHaveLength(1);
    rerender({ source: "export default () => 2", contentKey: "h2" });
    expect(mounts()).toHaveLength(2);
    expect(mounts()[1]).toMatchObject({ source: "export default () => 2" });
  });

  it("fans shared keys out through the hub, both ways", async () => {
    const hub = new SharedStateHub();
    const otherRestore = vi.fn();
    hub.register("other", { mine: true }, otherRestore);
    const { posted, send } = mount({ hub });
    await act(async () => send({ type: "ready" }));
    await act(async () =>
      send({
        type: "stateChanged",
        viewId: "v1",
        state: { "shared:k": 1 },
        queries: [],
      }),
    );
    expect(otherRestore).toHaveBeenCalledWith({ mine: true, "shared:k": 1 });
    hub.report("other", { "shared:k": 2 });
    expect(posted.at(-1)).toMatchObject({
      type: "restore",
      viewId: "v1",
      state: { "shared:k": 2 },
    });
  });

  it("leaves the hub when it unmounts", async () => {
    const hub = new SharedStateHub();
    hub.register("other", {}, () => undefined);
    // Watched on the bridge, not the frame: an unmounted iframe has no window to post to.
    const restore = vi.spyOn(HostBridge.prototype, "restore");
    const { send, unmount } = mount({ hub });
    await act(async () => send({ type: "ready" }));
    hub.report("other", { "shared:k": 1 });
    expect(restore).toHaveBeenCalledTimes(1);
    unmount();
    hub.report("other", { "shared:k": 2 });
    expect(restore).toHaveBeenCalledTimes(1);
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
    rerender({ contentKey: "h2" });
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
