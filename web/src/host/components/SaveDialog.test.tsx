import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SaveDialog } from "./SaveDialog";

const projects = [
  {
    slug: "p",
    name: "Momentum",
    description: "",
    created_at: "",
    updated_at: "",
    canvas: [],
  },
];

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
});
