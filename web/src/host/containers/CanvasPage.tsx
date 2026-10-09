import { useEffect, useRef, useState } from "react";
import GridLayout, { useContainerWidth, type Layout } from "react-grid-layout";
import type { CanvasCard, Project } from "@/shared/api-types";
import {
  useRecall,
  useSavedView,
  useSession,
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
  const recall = useRecall(sessionId);
  const setCanvas = useSetCanvas();
  const [hub] = useState(() => new SharedStateHub());
  const [layout, setLayout] = useState<Layout>(() =>
    cardsToLayout(project.meta.canvas),
  );
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
  const running = steps.at(-1)?.status === "running";
  const dataVersion = String(
    steps.filter((s) => s.status !== "running").length,
  );
  const present = new Set(steps.flatMap((s) => s.writes));
  const error = recall.error ?? setCanvas.error;

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
              const missing = view.datasets.filter((d) => !present.has(d));
              return (
                <div key={item.i}>
                  <CanvasCardFrame
                    title={view.name}
                    missing={missing}
                    loading={recall.isPending || running}
                    onLoad={() =>
                      recall.mutate({
                        project: slug,
                        kind: "view",
                        name: view.name,
                      })
                    }
                    onRemove={() => remove(view.name)}
                  >
                    <CanvasCardView
                      slug={slug}
                      view={view.name}
                      sessionId={sessionId}
                      dataVersion={dataVersion}
                      hub={hub}
                    />
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
      viewId={`canvas:${view}`}
      sessionId={sessionId}
      contentKey={saved.data.meta.saved_at}
      source={saved.data.source}
      initialState={saved.data.state}
      datasets={saved.data.meta.datasets}
      restoreState={null}
      dataVersion={dataVersion}
      title={`Canvas card ${view}`}
      hub={hub}
      fill
    />
  );
}
