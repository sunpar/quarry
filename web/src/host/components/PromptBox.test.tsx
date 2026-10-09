import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PromptBox } from "./PromptBox";

describe("PromptBox", () => {
  it("submits on Enter and clears once accepted", async () => {
    const onSubmit = vi.fn(() => Promise.resolve());
    render(
      <PromptBox
        running={false}
        onSubmit={onSubmit}
        onStop={() => undefined}
      />,
    );
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "show prices" } });
    fireEvent.keyDown(box, { key: "Enter" });
    expect(onSubmit).toHaveBeenCalledWith("show prices");
    await waitFor(() => expect((box as HTMLTextAreaElement).value).toBe(""));
  });

  it("keeps the text when the submit is refused", async () => {
    const onSubmit = vi.fn(() => Promise.reject(new Error("409")));
    render(
      <PromptBox
        running={false}
        onSubmit={onSubmit}
        onStop={() => undefined}
      />,
    );
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "show prices" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await Promise.resolve();
    expect(onSubmit).toHaveBeenCalled();
    expect((box as HTMLTextAreaElement).value).toBe("show prices");
  });

  it("ignores Enter while an IME composition is open", () => {
    const onSubmit = vi.fn(() => Promise.resolve());
    render(
      <PromptBox
        running={false}
        onSubmit={onSubmit}
        onStop={() => undefined}
      />,
    );
    const box = screen.getByRole("textbox");
    fireEvent.change(box, { target: { value: "株価" } });
    fireEvent.keyDown(box, { key: "Enter", isComposing: true });
    expect(onSubmit).not.toHaveBeenCalled();
  });

  it("refuses prompts while the kernel is dead", () => {
    const onSubmit = vi.fn(() => Promise.resolve());
    render(
      <PromptBox
        running={false}
        kernelDead
        onSubmit={onSubmit}
        onStop={vi.fn()}
      />,
    );
    expect(screen.getByRole("textbox")).toHaveProperty("disabled", true);
    expect(screen.getByRole("button", { name: "Run" })).toHaveProperty(
      "disabled",
      true,
    );
    expect(
      screen.getByPlaceholderText("Restart the kernel to continue"),
    ).toBeTruthy();
  });

  it("disables input and offers Stop while running", () => {
    const onStop = vi.fn();
    render(
      <PromptBox running onSubmit={() => Promise.resolve()} onStop={onStop} />,
    );
    expect(screen.getByRole("textbox")).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalled();
  });
});
