import { useEffect, useRef, useState } from "react";
import GridLayout, { useContainerWidth, type Layout } from "react-grid-layout";
import type { CanvasCard, Project } from "@/shared/api-types";
import {
  dataVersion,
  sessionRunning,
  useDatasets,
  useRecall,
  useSavedView,
  useSession,
  useSessionStatus,
  useSetCanvas,
} from "../api/hooks";
import { SharedStateHub } from "../bridge/SharedStateHub";
import { CanvasCardFrame } from "../components/CanvasCardFrame";
import { ViewHost } from "./ViewHost";

const COLS = 12;
const ROW_HEIGHT = 40;
const SAVE_DELAY_MS = 500;

export function cardsToLayout(cards: CanvasCard[]): Layout {
  return cards.map((c) => ({
    i: c.view,
    x: c.x,
    y: c.y,
    w: c.w,
    h: c.h,
    minW: 3,
    minH: 3,
  }));
}

export function layoutToCards(layout: Layout): CanvasCard[] {
  return layout.map((l) => ({ view: l.i, x: l.x, y: l.y, w: l.w, h: l.h }));
}

interface CanvasPageProps {
  project: Project;
  sessionId: string;
}

export function CanvasPage({ project, sessionId }: CanvasPageProps) {
  // Measured before the grid mounts; otherwise cards open at a default 1280px and shrink.
  const { width, containerRef, mounted } = useContainerWidth({
    measureBeforeMount: true,
  });
  const session = useSession(sessionId);
  const recall = useRecall();
  const setCanvas = useSetCanvas();
  const [hub] = useState(() => new SharedStateHub());
  const [layout, setLayout] = useState<Layout>(() =>
    cardsToLayout(project.meta.canvas),
  );
  // A card the project gained elsewhere, as a pin that finished after this page opened, joins
  // the layout; one only this page removed stays removed.
  const [seenCanvas, setSeenCanvas] = useState(project.meta.canvas);
  if (project.meta.canvas !== seenCanvas) {
    const before = new Set(seenCanvas.map((c) => c.view));
    const added = project.meta.canvas.filter(
      (c) => !before.has(c.view) && !layout.some((l) => l.i === c.view),
    );
    setSeenCanvas(project.meta.canvas);
    if (added.length > 0) setLayout([...layout, ...cardsToLayout(added)]);
  }
  const slug = project.meta.slug;
  // Layout writes are debounced so a drag does not PUT on every frame.
  const pending = useRef<CanvasCard[] | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const flush = () => {
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = null;
    if (pending.current === null) return;
    setCanvas.mutate({ slug, cards: pending.current });
    pending.current = null;
  };
  // Leaving the page mid-debounce still saves the last drag. The first render's flush is
  // enough: it reads refs, the slug is fixed by ProjectPage's key, and mutate is stable.
  useEffect(() => flush, []);

  const steps = session.data?.steps ?? [];
  const running = sessionRunning(session.data);
  const status = useSessionStatus(sessionId, running || recall.isPending);
  const version = dataVersion(steps, status.data?.kernel.pid);
  // What the kernel holds now: a step's writes can be deleted or rebound since, and a reopened
  // session's kernel holds nothing until its steps replay.
  const datasets = useDatasets(sessionId, version);
  const present =
    datasets.data === undefined
      ? undefined
      : new Set(datasets.data.map((d) => d.name));
  const error = recall.error ?? setCanvas.error ?? datasets.error;

  // react-grid-layout fires onLayoutChange once on mount after compaction; only a real
  // change in positions or sizes is worth a PUT.
  const onLayoutChange = (next: Layout) => {
    const cards = layoutToCards(next);
    if (JSON.stringify(cards) === JSON.stringify(layoutToCards(layout))) return;
    setLayout(next);
    pending.current = cards;
    if (timer.current !== null) clearTimeout(timer.current);
    timer.current = setTimeout(flush, SAVE_DELAY_MS);
  };

  // Written at once, replacing any pending drag, which still holds the removed card.
  const remove = (view: string) => {
    const next = layout.filter((l) => l.i !== view);
    setLayout(next);
    pending.current = layoutToCards(next);
    flush();
  };

  // The measured box has no padding: its computed width would count it under border-box.
  return (
    <div className="min-h-0 flex-1 overflow-y-auto p-4">
      <div ref={containerRef}>
        {layout.length === 0 && (
          <p className="text-sm text-muted-foreground">
            Pin a view from a step to start the canvas.
          </p>
        )}
        {error !== null && (
          <p className="text-sm text-destructive">{error.message}</p>
        )}
        {mounted && (
          <GridLayout
            width={width}
            layout={layout}
            gridConfig={{ cols: COLS, rowHeight: ROW_HEIGHT, margin: [12, 12] }}
            dragConfig={{ handle: ".card-handle", cancel: "button" }}
            onLayoutChange={onLayoutChange}
          >
            {layout.map((item) => {
              const view = project.views.find((v) => v.name === item.i);
              if (view === undefined) return <div key={item.i} />;
              // Until the kernel answers, a card shows neither its view nor "Load".
              const missing =
                present === undefined
                  ? []
                  : view.datasets.filter((d) => !present.has(d));
              return (
                <div key={item.i}>
                  <CanvasCardFrame
                    title={view.name}
                    missing={missing}
                    loading={recall.isPending || running}
                    onLoad={() =>
                      recall.mutate({
                        sessionId,
                        project: slug,
                        kind: "view",
                        name: view.name,
                      })
                    }
                    onRemove={() => remove(view.name)}
                  >
                    {present !== undefined && (
                      <CanvasCardView
                        slug={slug}
                        view={view.name}
                        sessionId={sessionId}
                        dataVersion={version}
                        hub={hub}
                      />
                    )}
                  </CanvasCardFrame>
                </div>
              );
            })}
          </GridLayout>
        )}
      </div>
    </div>
  );
}

interface CanvasCardViewProps {
  slug: string;
  view: string;
  sessionId: string;
  dataVersion: string;
  hub: SharedStateHub;
}

function CanvasCardView({
  slug,
  view,
  sessionId,
  dataVersion,
  hub,
}: CanvasCardViewProps) {
  const saved = useSavedView(slug, view);
  if (saved.data === undefined) return null;
  return (
    <ViewHost
      key={JSON.stringify([sessionId, `canvas:${view}`])}
      viewId={`canvas:${view}`}
      sessionId={sessionId}
      contentKey={saved.data.meta.saved_at}
      source={saved.data.source}
      initialState={saved.data.state}
      datasets={saved.data.meta.datasets}
      dataVersion={dataVersion}
      title={`Canvas card ${view}`}
      hub={hub}
      fill
    />
  );
}
