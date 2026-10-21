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

const viewDialog = (
  list: ProjectMeta[] | undefined,
  onSave: () => void,
  error: string | null = null,
) => (
  <SaveDialog
    open
    kind="view"
    projects={list}
    error={error}
    defaultName="step-3-view"
    onClose={() => undefined}
    onSave={onSave}
  />
);
const saveButton = () =>
  screen.getByRole<HTMLButtonElement>("button", { name: "Save view" });
const projectSelect = () => screen.getByLabelText<HTMLSelectElement>("Project");

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
    fireEvent.click(saveButton());
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
      target: { value: "!!!" },
    });
    expect(saveButton().disabled).toBe(true);
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "My Closes!" },
    });
    fireEvent.click(saveButton());
    expect(onSave).toHaveBeenCalledWith(
      expect.objectContaining({ name: "my-closes" }),
    );
  });

  it("says Loading, not the create hint, while the list loads", () => {
    render(viewDialog(undefined, vi.fn()));
    screen.getByText("Loading");
    expect(
      screen.queryByText("Create a project in the rail first."),
    ).toBeNull();
    expect(saveButton().disabled).toBe(true);
  });

  it("shows why the list failed to load", () => {
    render(viewDialog(undefined, vi.fn(), "boom"));
    screen.getByText("boom");
    expect(
      screen.queryByText("Create a project in the rail first."),
    ).toBeNull();
  });

  it("chooses the first project when the list arrives after opening", () => {
    const onSave = vi.fn();
    const { rerender } = render(viewDialog([], onSave));
    expect(saveButton().disabled).toBe(true);
    rerender(viewDialog(projects, onSave));
    expect(projectSelect().value).toBe("p");
    fireEvent.click(saveButton());
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ slug: "p" }));
  });

  it("keeps the shown project when a refetch puts another first", () => {
    const onSave = vi.fn();
    const { rerender } = render(viewDialog(projects, onSave));
    rerender(
      viewDialog([{ ...momentum, slug: "a", name: "Alpha" }, momentum], onSave),
    );
    fireEvent.click(saveButton());
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
    fireEvent.click(saveButton());
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ slug: "q" }));
  });
});
