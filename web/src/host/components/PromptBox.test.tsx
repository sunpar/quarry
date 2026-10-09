import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PromptBox } from "./PromptBox";

describe("PromptBox", () => {
  it("submits on Enter and clears", () => {
    const onSubmit = vi.fn();
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
    expect((box as HTMLTextAreaElement).value).toBe("");
  });

  it("disables input and offers Stop while running", () => {
    const onStop = vi.fn();
    render(<PromptBox running onSubmit={() => undefined} onStop={onStop} />);
    expect(screen.getByRole("textbox")).toHaveProperty("disabled", true);
    fireEvent.click(screen.getByRole("button", { name: "Stop" }));
    expect(onStop).toHaveBeenCalled();
  });
});
