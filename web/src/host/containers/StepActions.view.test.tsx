import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Snapshot, Step, View } from "@/shared/api-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { StepActions } from "./StepActions";

const spec = {
  dataset: "df",
  group_by: ["a"],
  aggs: [{ col: "b", fn: "sum" as const }],
};
// What the pivot records: its arrow data query and a one-row probe of the mapped spec.
const pivotSnapshot: Snapshot = {
  ts: "",
  state: { spec, dropped: ["expression e"] },
  queries: [
    { dataset: "df", format: "arrow", limit: 50000 },
    { ...spec, limit: 1 },
  ],
};

const stepWith = (view: Partial<View>): Step => ({
  id: "st1",
  index: 0,
  kind: "prompt",
  prompt: "show prices",
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
    source: "export default function V() {}",
    initial_state: {},
    datasets: [],
    snapshots: [],
    ...view,
  },
  created_at: "",
  duration_ms: 0,
});

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });

function setup(step: Step, respond: (key: string) => Response) {
  const bodies = new Map<string, unknown>();
  const fetchImpl = async (path: string, init?: RequestInit) => {
    const key = `${init?.method ?? "GET"} ${path}`;
    if (init?.body !== undefined)
      bodies.set(key, JSON.parse(String(init.body)));
    if (key === "GET /projects") return json([]);
    return respond(key);
  };
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onDone = vi.fn();
  render(
    <QueryClientProvider client={qc}>
      <ApiProvider client={new ApiClient("t", fetchImpl)}>
        <StepActions sessionId="s1" step={step} onDone={onDone} />
      </ApiProvider>
    </QueryClientProvider>,
  );
  return { bodies, onDone };
}

describe("StepActions to code", () => {
  it("waits for the view to report its queries", () => {
    setup(stepWith({}), () => json({}));
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "To code" })
        .disabled,
    ).toBe(true);
  });

  it("renders the pivot's spec and runs the edited code as a step", async () => {
    const step = stepWith({
      component_id: "pivot",
      snapshots: [pivotSnapshot],
    });
    const { bodies } = setup(step, (key) =>
      key === "POST /sessions/s1/to-code"
        ? json({ code: "df_1 = df.group_by('a')" })
        : json({ ...step, id: "st2", kind: "manual" }, 202),
    );
    fireEvent.click(screen.getByRole("button", { name: "To code" }));
    const box = await screen.findByRole("textbox", { name: "Python" });
    expect(bodies.get("POST /sessions/s1/to-code")).toEqual({
      queries: [spec],
    });
    expect(screen.getByText("Left out: expression e.")).toBeTruthy();
    fireEvent.change(box, { target: { value: "df_1 = 1" } });
    fireEvent.click(screen.getByRole("button", { name: "Run as step" }));
    await waitFor(() =>
      expect(screen.queryByRole("textbox", { name: "Python" })).toBeNull(),
    );
    expect(bodies.get("POST /sessions/s1/steps/manual")).toEqual({
      code: "df_1 = 1",
    });
  });
});

async function saveToLibrary() {
  fireEvent.click(screen.getByRole("button", { name: "Save to library" }));
  const dialog = screen.getByRole("dialog");
  fireEvent.change(within(dialog).getByLabelText("Name"), {
    target: { value: "My view" },
  });
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Save to library" }),
  );
  return dialog;
}

describe("StepActions save to library", () => {
  it("is offered only for an inline view", () => {
    setup(stepWith({ component_id: "data-table" }), () => json({}));
    expect(
      screen.queryByRole("button", { name: "Save to library" }),
    ).toBeNull();
  });

  it("sends no dataset binding for a view without datasets", async () => {
    const { bodies, onDone } = setup(stepWith({}), () =>
      json({ id: "step-1-view" }, 201),
    );
    await saveToLibrary();
    await waitFor(() =>
      expect(onDone).toHaveBeenCalledWith("Saved step-1-view to your library"),
    );
    expect(bodies.get("POST /components")).toEqual({
      id: "step-1-view",
      name: "My view",
      description: "",
      tags: [],
      source: "export default function V() {}",
      session_id: null,
      dataset: null,
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("binds the view's first dataset to this session", async () => {
    const { bodies, onDone } = setup(
      stepWith({ datasets: ["prices", "volumes"] }),
      () => json({ id: "step-1-view" }, 201),
    );
    await saveToLibrary();
    await waitFor(() => expect(onDone).toHaveBeenCalled());
    expect(bodies.get("POST /components")).toMatchObject({
      session_id: "s1",
      dataset: "prices",
    });
  });

  it("shows the server's refusal in the dialog", async () => {
    const detail = "component 'step-1-view' already exists";
    const { onDone } = setup(stepWith({}), () => json({ detail }, 409));
    const dialog = await saveToLibrary();
    expect(await within(dialog).findByText(detail)).toBeTruthy();
    expect(screen.getByRole("dialog")).toBe(dialog);
    expect(onDone).not.toHaveBeenCalled();
  });
});
