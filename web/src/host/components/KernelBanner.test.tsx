import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { KernelStatus, ReplayReport } from "@/shared/api-types";
import { KernelBanner } from "./KernelBanner";

const kernel = (
  status: KernelStatus["status"],
  replay_needed = false,
): KernelStatus => ({ status, pid: 1, replay_needed });

interface Overrides {
  kernel?: KernelStatus;
  restarting?: boolean;
  replay?: ReplayReport | null;
  onRestart?: () => void;
}

function renderBanner(overrides: Overrides) {
  return render(
    <KernelBanner
      kernel={overrides.kernel ?? kernel("idle")}
      lastError="boom"
      restarting={overrides.restarting ?? false}
      restartError={null}
      replay={overrides.replay ?? null}
      onRestart={overrides.onRestart ?? (() => undefined)}
    />,
  );
}

describe("KernelBanner", () => {
  it("is hidden while the kernel is idle", () => {
    const { container } = renderBanner({});
    expect(container.innerHTML).toBe("");
  });

  it("shows on a dead kernel with the last error", () => {
    renderBanner({ kernel: kernel("dead") });
    expect(screen.getByText("The Python kernel stopped: boom")).toBeTruthy();
  });

  it("shows when a respawned kernel needs a replay", () => {
    renderBanner({ kernel: kernel("idle", true) });
    expect(
      screen.getByText("The kernel restarted without this session's steps."),
    ).toBeTruthy();
  });

  it("shows where a replay stopped and keeps the button", () => {
    renderBanner({
      replay: { replayed: 1, failed_step: 1, error: "NameError: x" },
    });
    expect(
      screen.getByText("Replay stopped at step 2: NameError: x"),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "Restart kernel" })).toBeTruthy();
  });

  it("disables the button while restarting", () => {
    renderBanner({ kernel: kernel("dead"), restarting: true });
    expect(
      screen.getByRole("button", { name: "Restart kernel" }),
    ).toHaveProperty("disabled", true);
  });

  it("calls onRestart on click", () => {
    const onRestart = vi.fn();
    renderBanner({ kernel: kernel("dead"), onRestart });
    fireEvent.click(screen.getByRole("button", { name: "Restart kernel" }));
    expect(onRestart).toHaveBeenCalled();
  });
});
