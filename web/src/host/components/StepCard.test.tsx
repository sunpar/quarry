import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { Step } from "@/shared/api-types";
import { StepCard } from "./StepCard";

const base: Step = {
  id: "s1",
  index: 0,
  kind: "prompt",
  prompt: "show prices",
  code: "prices = pl.DataFrame()",
  status: "ok",
  error: null,
  note: "Loaded prices",
  stdout_tail: "",
  stderr_tail: "",
  reads: [],
  writes: ["prices"],
  defines: [],
  datasets: [
    {
      name: "prices",
      backing: "polars",
      schema: [],
      rows: 10,
      preview: [],
      error: null,
    },
  ],
  view: null,
  created_at: "2026-10-08T00:00:00Z",
  duration_ms: 1200,
};

describe("StepCard", () => {
  it("shows prompt, note, dataset chips and a collapsed code drawer", () => {
    render(<StepCard step={base} index={1} />);
    expect(screen.getByText("show prices")).toBeTruthy();
    expect(screen.getByText("Loaded prices")).toBeTruthy();
    expect(screen.getByText("prices")).toBeTruthy();
    expect(screen.queryByText("prices = pl.DataFrame()")).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Code" }));
    expect(screen.getByText("prices = pl.DataFrame()")).toBeTruthy();
  });

  it("shows the traceback on error", () => {
    const failed: Step = {
      ...base,
      status: "error",
      error: {
        type: "KeyError",
        message: "'x'",
        traceback: "Traceback...KeyError: 'x'",
      },
    };
    render(<StepCard step={failed} index={1} />);
    expect(screen.getByText(/KeyError: 'x'/)).toBeTruthy();
  });
});
