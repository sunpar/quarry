import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SaveDialog } from "./SaveDialog";

const momentum = {
  slug: "p",
  name: "Momentum",
  description: "",
  created_at: "",
  updated_at: "",
  canvas: [],
};
const projects = [momentum];

const viewDialog = (list: (typeof momentum)[], onSave: () => void) => (
  <SaveDialog
    open
    kind="view"
    projects={list}
    defaultName="closes"
    onClose={() => undefined}
    onSave={onSave}
  />
);

describe("SaveDialog", () => {
  it("submits project, name, mode and description", () => {
    const onSave = vi.fn();
    render(
      <SaveDialog
        open
        kind="view"
        projects={projects}
        defaultName="step-3-view"
        onClose={() => undefined}
        onSave={onSave}
      />,
    );
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
    render(
      <SaveDialog
        open
        kind="view"
        projects={projects}
        defaultName=""
        onClose={() => undefined}
        onSave={onSave}
      />,
    );
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
