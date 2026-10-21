import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SnapshotScrubber } from "./SnapshotScrubber";

describe("SnapshotScrubber", () => {
  it("renders nothing for fewer than two snapshots", () => {
    const { container } = render(
      <SnapshotScrubber count={1} value={0} onPick={() => undefined} />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows the position it is given and reports a pick by position", () => {
    const onPick = vi.fn();
    render(<SnapshotScrubber count={3} value={2} onPick={onPick} />);
    expect(screen.getByText("3 of 3")).toBeTruthy();
    fireEvent.change(screen.getByRole("slider"), { target: { value: "1" } });
    expect(onPick).toHaveBeenCalledWith(1);
    // The caller decides what the pick shows.
    expect(screen.getByText("3 of 3")).toBeTruthy();
  });
});
