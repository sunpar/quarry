import { Button } from "@/components/ui/button";
import type { SessionMeta } from "@/shared/api-types";

interface SessionRailProps {
  sessions: SessionMeta[];
  activeId: string | null;
  onSelect: (id: string) => void;
  onCreate: () => void;
}

export function SessionRail({
  sessions,
  activeId,
  onSelect,
  onCreate,
}: SessionRailProps) {
  return (
    <nav className="flex h-full w-[232px] flex-col gap-4 border-r border-border bg-card px-4 py-5">
      <h1 className="text-xl font-semibold">Quarry</h1>
      <Button variant="outline" size="sm" onClick={onCreate}>
        New session
      </Button>
      <ul className="flex flex-col gap-0.5 overflow-y-auto">
        {sessions.map((s) => (
          <li key={s.id}>
            <button
              type="button"
              aria-current={s.id === activeId ? "page" : undefined}
              onClick={() => onSelect(s.id)}
              className="w-full truncate rounded-md px-2 py-1.5 text-left text-sm hover:bg-muted aria-[current=page]:bg-muted aria-[current=page]:text-primary"
            >
              {s.title}
            </button>
          </li>
        ))}
      </ul>
      {sessions.length === 0 && (
        <p className="text-sm text-muted-foreground">
          Start a session to explore data.
        </p>
      )}
    </nav>
  );
}
