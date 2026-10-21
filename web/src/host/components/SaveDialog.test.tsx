import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ProjectMeta } from "@/shared/api-types";
import { SaveDialog } from "./SaveDialog";

const momentum: ProjectMeta = {
  slug: "p",
  name: "Momentum",
  description: "",
  created_at: "",
  updated_at: "",
  canvas: [],
};
const projects = [momentum];

const viewDialog = (list: ProjectMeta[], onSave: () => void) => (
  <SaveDialog
    open
    kind="view"
    projects={list}
    defaultName="step-3-view"
    onClose={() => undefined}
    onSave={onSave}
  />
);

describe("SaveDialog", () => {
  it("submits project, name, mode and description", () => {
    const onSave = vi.fn();
    render(viewDialog(projects, onSave));
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "closes" },
    });
    fireEvent.click(screen.getByLabelText("Pinned copy"));
    fireEvent.change(screen.getByLabelText("Description"), {
      target: { value: "daily" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));
    expect(onSave).toHaveBeenCalledWith({
      slug: "p",
      name: "closes",
      mode: "pinned",
      description: "daily",
    });
  });

  it("slugifies the name and blocks empty names", () => {
    const onSave = vi.fn();
    render(viewDialog(projects, onSave));
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "My Closes!" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ name: "my-closes" }),
    );
  });

  it("chooses the first project when the list arrives after opening", () => {
    const onSave = vi.fn();
    const { rerender } = render(viewDialog([], onSave));
    rerender(viewDialog(projects, onSave));
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ slug: "p" }));
  });

  it("keeps the picked project across a rerender", () => {
    const onSave = vi.fn();
    const two = [momentum, { ...momentum, slug: "q", name: "Value" }];
    const { rerender } = render(viewDialog(two, onSave));
    fireEvent.change(screen.getByLabelText("Project"), {
      target: { value: "q" },
    });
    rerender(viewDialog([...two], onSave));
    fireEvent.click(screen.getByRole("button", { name: "Save view" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ slug: "q" }));
  });
});
