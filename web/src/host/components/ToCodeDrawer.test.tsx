import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ToCodeDrawer } from "./ToCodeDrawer";

describe("ToCodeDrawer", () => {
  it("shows the code, what was left out, and runs the edited text", () => {
    const onRun = vi.fn();
    const onChange = vi.fn();
    render(
      <ToCodeDrawer
        code="result = df.lazy().collect()"
        dropped={["expression e"]}
        pending={false}
        error={null}
        onChange={onChange}
        onRun={onRun}
        onClose={() => undefined}
      />,
    );
    expect(screen.getByText(/left out: expression e/i)).toBeTruthy();
    const box = screen.getByRole("textbox", { name: "Python" });
    expect((box as HTMLTextAreaElement).value).toContain("df.lazy()");
    fireEvent.change(box, { target: { value: "x = 1" } });
    expect(onChange).toHaveBeenCalledWith("x = 1");
    fireEvent.click(screen.getByRole("button", { name: "Run as step" }));
    expect(onRun).toHaveBeenCalled();
  });

  it("disables run while pending and shows an error", () => {
    render(
      <ToCodeDrawer
        code=""
        dropped={[]}
        pending
        error="kernel is dead"
        onChange={() => undefined}
        onRun={() => undefined}
        onClose={() => undefined}
      />,
    );
    expect(
      (screen.getByRole("button", { name: "Run as step" }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
    expect(screen.getByText("kernel is dead")).toBeTruthy();
  });
});
