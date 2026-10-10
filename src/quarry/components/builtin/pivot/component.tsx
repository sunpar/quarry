import { useMemo } from "react";
import { useDatasetSchema, useQuery, useViewState } from "@quarry/hooks";
import {
  PerspectiveViewer,
  perspectiveToSpec,
  type ViewerConfigUpdate,
} from "@quarry/perspective";
import type { JsonObject } from "@/shared/json";

interface Props {
  datasets: string[];
}

const ROWS = 50000;

export default function Pivot({ datasets }: Props) {
  const dataset = datasets[0] ?? "";
  // View state holds JSON; Perspective's types allow `undefined`, which JSON never carries.
  const [stored, setConfig] = useViewState<JsonObject | null>(
    "perspective",
    null,
  );
  const config = stored as ViewerConfigUpdate | null;
  const [dropped, setDropped] = useViewState<string[]>("dropped", []);
  const data = useQuery({ dataset, format: "arrow", limit: ROWS });
  // Default aggregates follow the column types, as Perspective's do.
  const schema = useDatasetSchema(dataset);
  const mapped = useMemo(
    () => perspectiveToSpec(dataset, config ?? {}, schema ?? []),
    [dataset, config, schema],
  );
  // One-row probe: the kernel validates the mapped spec and it is recorded for "to code".
  const probe = useQuery({ ...mapped.spec, limit: 1 });

  if (data.status === "loading")
    return <p className="p-4 text-sm text-muted-foreground">Loading</p>;
  if (data.status === "error" || data.arrow === null)
    return (
      <pre className="p-4 font-mono text-sm text-destructive">
        {data.status === "error" ? data.message : "no arrow data"}
      </pre>
    );

  const onConfig = (next: ViewerConfigUpdate) => {
    setConfig(next as JsonObject);
    const nextDropped = perspectiveToSpec(dataset, next, schema ?? []).dropped;
    if (nextDropped.join("\n") !== dropped.join("\n")) setDropped(nextDropped);
  };

  return (
    <div className="flex h-full flex-col">
      {(data.truncated ||
        mapped.dropped.length > 0 ||
        probe.status === "error") && (
        <p className="border-b border-border px-3 py-1 text-sm text-muted-foreground">
          {data.truncated &&
            `Showing the first ${ROWS.toLocaleString()} of ${data.rowCount.toLocaleString()} rows. `}
          {mapped.dropped.length > 0 &&
            `To code will leave out: ${mapped.dropped.join(", ")}. `}
          {probe.status === "error" &&
            `This layout cannot run as a query: ${probe.message}`}
        </p>
      )}
      <PerspectiveViewer
        arrow={data.arrow}
        config={config ?? undefined}
        onConfig={onConfig}
        className="min-h-0 flex-1"
      />
    </div>
  );
}
