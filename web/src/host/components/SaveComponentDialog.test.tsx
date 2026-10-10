import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SaveComponentDialog } from "./SaveComponentDialog";

describe("SaveComponentDialog", () => {
  it("normalises the id and splits tags", () => {
    const onSave = vi.fn();
    render(
      <SaveComponentDialog
        open
        defaultId="step-3-view"
        onClose={() => undefined}
        onSave={onSave}
      />,
    );
    const dialog = screen.getByRole("dialog");
    fireEvent.change(screen.getByLabelText("Id"), {
      target: { value: "My Scatter!" },
    });
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "My scatter" },
    });
    fireEvent.change(screen.getByLabelText("Tags"), {
      target: { value: "scatter, returns ,, " },
    });
    expect(screen.getByText("my-scatter")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save to library" }));
    expect(onSave).toHaveBeenCalledWith({
      id: "my-scatter",
      name: "My scatter",
      description: "",
      tags: ["scatter", "returns"],
    });
    expect(dialog).toBeTruthy();
  });

  it("keeps the save button disabled until the id is valid", () => {
    render(
      <SaveComponentDialog
        open
        defaultId=""
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    );
    expect(
      (
        screen.getByRole("button", {
          name: "Save to library",
        }) as HTMLButtonElement
      ).disabled,
    ).toBe(true);
  });

  it("shows the server's refusal and holds the button while saving", () => {
    render(
      <SaveComponentDialog
        open
        defaultId="my-scatter"
        pending
        error="component 'my-scatter' already exists"
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "My scatter" },
    });
    expect(
      screen.getByText("component 'my-scatter' already exists"),
    ).toBeTruthy();
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Save to library" })
        .disabled,
    ).toBe(true);
  });
});
