import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SaveComponentDialog } from "./SaveComponentDialog";

describe("SaveComponentDialog", () => {
  it("normalises the id and splits tags without repeats", () => {
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
      target: { value: "scatter, returns ,, scatter" },
    });
    expect(screen.getByText("my-scatter")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save to library" }));
    expect(onSave).toHaveBeenCalledWith({
      id: "my-scatter",
      name: "My scatter",
      description: "",
      tags: ["scatter", "returns"],
    });
    expect(document.body.contains(dialog)).toBe(true);
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

  it("cuts a long id to the server's 64 characters", () => {
    const onSave = vi.fn();
    render(
      <SaveComponentDialog
        open
        defaultId=""
        onClose={() => undefined}
        onSave={onSave}
      />,
    );
    const short = "x".repeat(63);
    fireEvent.change(screen.getByLabelText("Id"), {
      target: { value: `${short}-yyyyyy` },
    });
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Long" },
    });
    expect(screen.getByText(short)).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Save to library" }));
    expect(onSave).toHaveBeenCalledWith(expect.objectContaining({ id: short }));
  });

  it("shows the server's refusal for the id it was about", () => {
    const refusal = "component 'my-scatter' already exists";
    const props = {
      open: true,
      defaultId: "my-scatter",
      onClose: () => undefined,
      onSave: () => undefined,
    };
    const { rerender } = render(<SaveComponentDialog {...props} />);
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "My scatter" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Save to library" }));
    rerender(<SaveComponentDialog {...props} pending error={refusal} />);
    expect(screen.getByText(refusal)).toBeTruthy();
    expect(
      screen.getByRole<HTMLButtonElement>("button", { name: "Save to library" })
        .disabled,
    ).toBe(true);
    fireEvent.change(screen.getByLabelText("Id"), {
      target: { value: "my-other-scatter" },
    });
    expect(screen.queryByText(refusal)).toBeNull();
    fireEvent.change(screen.getByLabelText("Id"), {
      target: { value: "My Scatter" },
    });
    expect(screen.getByText(refusal)).toBeTruthy();
  });
});
