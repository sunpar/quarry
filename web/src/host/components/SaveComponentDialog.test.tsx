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

  it("says why an id with no letter or digit cannot be saved", () => {
    const hint = "An id needs a letter or a digit.";
    render(
      <SaveComponentDialog
        open
        defaultId=""
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Mine" },
    });
    expect(screen.queryByText(hint)).toBeNull();
    for (const value of ["日本語", "___", "!!!"]) {
      fireEvent.change(screen.getByLabelText("Id"), { target: { value } });
      expect(screen.getByText(hint)).toBeTruthy();
      expect(
        screen.getByRole<HTMLButtonElement>("button", {
          name: "Save to library",
        }).disabled,
      ).toBe(true);
    }
    fireEvent.change(screen.getByLabelText("Id"), { target: { value: "  " } });
    expect(screen.queryByText(hint)).toBeNull();
  });

  it("only ever saves an id the server accepts", () => {
    render(
      <SaveComponentDialog
        open
        defaultId=""
        onClose={() => undefined}
        onSave={() => undefined}
      />,
    );
    const inputs = [
      `--${"a".repeat(70)}`,
      "a-".repeat(40),
      "  Ünïcode  ",
      "___",
    ];
    const shown = inputs.map((value) => {
      fireEvent.change(screen.getByLabelText("Id"), { target: { value } });
      return (
        screen.queryByText(/^Saved as/)?.querySelector("code")?.textContent ??
        ""
      );
    });
    const valid = expect.stringMatching(/^[a-z0-9][a-z0-9-]{0,63}$/);
    expect(shown).toEqual([valid, valid, valid, ""]);
  });

  it("shows the last save's refusal until the id is edited", () => {
    const refusal = "component 'my-scatter' already exists";
    const props = {
      open: true,
      defaultId: "my-scatter",
      onClose: () => undefined,
      onSave: () => undefined,
    };
    const saveButton = () =>
      screen.getByRole<HTMLButtonElement>("button", {
        name: "Save to library",
      });
    const { rerender } = render(<SaveComponentDialog {...props} />);
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "My scatter" },
    });
    fireEvent.click(saveButton());
    rerender(<SaveComponentDialog {...props} pending />);
    expect(saveButton().disabled).toBe(true);
    rerender(<SaveComponentDialog {...props} error={refusal} />);
    expect(screen.getByText(refusal)).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Name"), {
      target: { value: "Another name" },
    });
    fireEvent.change(screen.getByLabelText("Tags"), {
      target: { value: "scatter" },
    });
    expect(screen.getByText(refusal)).toBeTruthy();
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
