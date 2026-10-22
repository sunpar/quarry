import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { Project } from "@/shared/api-types";
import { ProjectBrowser } from "./ProjectBrowser";

const project: Project = {
  meta: {
    slug: "p",
    name: "Momentum",
    description: "",
    created_at: "",
    updated_at: "",
    canvas: [],
  },
  datasets: [
    {
      name: "prices",
      description: "",
      backing: "polars",
      schema: [],
      rows: 3,
      mode: "live",
      saved_at: "",
      source_session: "s",
      source_step: "t",
      validated: false,
      validation_error: "rows differ",
    },
  ],
  views: [
    {
      name: "table",
      description: "",
      datasets: ["prices"],
      component_id: "data-table",
      saved_at: "",
      source_session: "s",
      source_step: "t",
    },
  ],
};

describe("ProjectBrowser", () => {
  it("lists projects, expands to items, recalls and opens", () => {
    const onRecall = vi.fn();
    const onOpen = vi.fn();
    render(
      <ProjectBrowser
        projects={[project]}
        error={null}
        expanded="p"
        onToggle={() => undefined}
        onOpen={onOpen}
        onRecall={onRecall}
        onCreate={() => undefined}
      />,
    );
    expect(screen.getByText("Momentum")).toBeTruthy();
    expect(screen.getByTitle("Not validated: rows differ")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Recall prices" }));
    expect(onRecall).toHaveBeenCalledWith("p", "dataset", "prices");
    fireEvent.click(screen.getByRole("button", { name: "Recall table" }));
    expect(onRecall).toHaveBeenCalledWith("p", "view", "table");
    fireEvent.click(screen.getByRole("button", { name: "Open Momentum" }));
    expect(onOpen).toHaveBeenCalledWith("p");
  });

  const createHint = "Create a project to save datasets and views into.";
  it.each([
    ["loading", "Loading", undefined, null],
    ["the list fails", "boom", undefined, "boom"],
    // A failed refetch keeps the last list.
    ["a refetch fails", "boom", [], "boom"],
    ["a refetch fails with some kept", "boom", [project], "boom"],
    ["there are none", createHint, [], null],
    ["there are some", null, [project], null],
  ])("when %s, says %s", (_, shown, list, error) => {
    render(
      <ProjectBrowser
        projects={list}
        error={error}
        expanded={null}
        onToggle={() => undefined}
        onOpen={() => undefined}
        onRecall={() => undefined}
        onCreate={() => undefined}
      />,
    );
    for (const hint of ["Loading", "boom", createHint])
      expect(screen.queryByText(hint) !== null, hint).toBe(hint === shown);
    if (error !== null)
      expect(screen.getByText(error).className).toContain("text-destructive");
  });
});
