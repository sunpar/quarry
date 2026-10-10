import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useRef, useState } from "react";
import type { Column, QuerySpec } from "@/shared/api-types";
import type { JsonObject } from "@/shared/json";
import type { LibraryStatus, LicensedLibrary } from "@/shared/library-types";
import { useApi } from "../api/context";
import { useLibraries } from "../api/hooks";
import { keys } from "../api/keys";
import { HostBridge } from "../bridge/HostBridge";
import type { SharedStateHub } from "../bridge/SharedStateHub";
import { ViewFrame } from "../components/ViewFrame";

interface ViewHostProps {
  viewId: string;
  sessionId: string;
  /** Remounts the view when it changes: a step view's content hash, a saved view's saved_at. */
  contentKey: string;
  source: string;
  initialState: JsonObject;
  datasets: string[];
  /** Restored into the mounted view each time it changes; null or absent restores nothing. */
  restoreState?: JsonObject | null;
  /** Changes whenever kernel data may have: a step finished or a new kernel started. */
  dataVersion: string;
  title: string;
  hub?: SharedStateHub;
  disabled?: boolean;
  fill?: boolean;
  onStateChanged?: (state: JsonObject, queries: QuerySpec[]) => void;
  /** Repairs the error the overlay shows; without it the overlay has no Fix button. */
  onFix?: (error: string) => void;
}

export function ViewHost(props: ViewHostProps) {
  const {
    viewId,
    sessionId,
    contentKey,
    restoreState,
    dataVersion,
    title,
    hub,
    disabled,
    fill,
    onFix,
  } = props;
  const api = useApi();
  const queryClient = useQueryClient();
  const frameRef = useRef<HTMLIFrameElement>(null);
  // The frame loads once, as soon as it is committed; the bridge arrives later, in the effect.
  const loaded = useRef(false);
  const bridgeRef = useRef<HostBridge | null>(null);
  const [error, setError] = useState<string | null>(null);
  // Callers rebuild the view and callbacks every render (snapshots append on every poll), so the
  // effect keys on contentKey and reads the source, initial state, datasets and callbacks here.
  const latest = useRef(props);
  latest.current = props;
  // The view mounts once, after the first libraries answer, error or not: `isFetched` never
  // turns back, so a later refetch cannot remount the view and reset its state.
  const { data: statuses, isFetched } = useLibraries();
  const licensed = useRef<LicensedLibrary[]>([]);
  licensed.current = toLicensed(statuses ?? []);

  // One bridge per iframe for its lifetime; the window listener is the effect's only job.
  useEffect(() => {
    const frame = frameRef.current;
    if (frame === null || !isFetched) return;
    const { source, initialState, datasets } = latest.current;
    // Schemas come from the live kernel, as queries do: a later step may have redefined the
    // name. Fetched fresh so a view never sees a list from before its step ran.
    const schemaFor = async (dataset: string): Promise<Column[]> => {
      const all = await queryClient.fetchQuery({
        queryKey: keys.datasets(sessionId),
        queryFn: () => api.datasets(sessionId),
        staleTime: 0,
      });
      const match = all.find((d) => d.name === dataset);
      if (match === undefined) throw new Error(`unknown dataset ${dataset}`);
      return match.schema;
    };
    const bridge = new HostBridge({
      viewId,
      frame: {
        postMessage: (m, origin) => frame.contentWindow?.postMessage(m, origin),
      },
      isFrame: (s) => s === frame.contentWindow,
      onQuery: (spec) => api.query(sessionId, spec),
      onSchema: schemaFor,
      onStateChanged: (state, queries) => {
        hub?.report(viewId, state);
        latest.current.onStateChanged?.(state, queries);
      },
      onError: setError,
    });
    const stop = bridge.listen(window);
    bridgeRef.current = bridge;
    const unregister = hub?.register(viewId, initialState, (state) =>
      bridge.restore(state),
    );
    setError(null);
    bridge.mount({
      source,
      initialState,
      datasets,
      licensed: licensed.current,
    });
    // The runtime posts `ready` once while loading, which can beat this listener; a frame
    // that has already loaded is listening, so mount now.
    if (loaded.current) bridge.frameLoaded();
    return () => {
      unregister?.();
      stop();
      bridgeRef.current = null;
    };
  }, [api, queryClient, sessionId, viewId, contentKey, hub, isFetched]);

  // A mounted view caches its answers; later steps and restarts change what the kernel holds.
  const seenVersion = useRef(dataVersion);
  useEffect(() => {
    if (seenVersion.current === dataVersion) return;
    seenVersion.current = dataVersion;
    bridgeRef.current?.refresh();
  }, [dataVersion]);

  useEffect(() => {
    if (restoreState) bridgeRef.current?.restore(restoreState);
  }, [restoreState]);

  return (
    <ViewFrame
      ref={frameRef}
      title={title}
      error={error}
      disabled={disabled}
      fill={fill}
      onFix={
        onFix === undefined ? undefined : () => error !== null && onFix(error)
      }
      onLoad={() => {
        loaded.current = true;
        bridgeRef.current?.frameLoaded();
      }}
    />
  );
}

function toLicensed(statuses: LibraryStatus[]): LicensedLibrary[] {
  return statuses.flatMap(({ id, enabled, entry, license }) =>
    enabled && entry !== null ? [{ id, entry, license }] : [],
  );
}
