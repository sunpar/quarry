import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SnapshotScrubber } from "./SnapshotScrubber";

const snapshots = [
  { ts: "2026-10-08T00:00:00Z", state: { n: 1 }, queries: [] },
  { ts: "2026-10-08T00:01:00Z", state: { n: 2 }, queries: [] },
  { ts: "2026-10-08T00:02:00Z", state: { n: 3 }, queries: [] },
];

describe("SnapshotScrubber", () => {
  it("renders nothing for fewer than two snapshots", () => {
    const { container } = render(
      <SnapshotScrubber
        snapshots={snapshots.slice(0, 1)}
        reports={0}
        onPick={() => undefined}
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("picks a snapshot's state by position", () => {
    const onPick = vi.fn();
    render(
      <SnapshotScrubber snapshots={snapshots} reports={0} onPick={onPick} />,
    );
    fireEvent.change(screen.getByRole("slider"), { target: { value: "1" } });
    expect(onPick).toHaveBeenCalledWith({ n: 2 });
    expect(screen.getByText("2 of 3")).toBeTruthy();
  });

  it("starts at the latest snapshot once snapshots arrive", () => {
    const { rerender } = render(
      <SnapshotScrubber snapshots={[]} reports={0} onPick={() => undefined} />,
    );
    rerender(
      <SnapshotScrubber
        snapshots={snapshots}
        reports={0}
        onPick={() => undefined}
      />,
    );
    expect(screen.getByText("3 of 3")).toBeTruthy();
  });

  it("follows the latest snapshot when a new one arrives after a pick", () => {
    const { rerender } = render(
      <SnapshotScrubber
        snapshots={snapshots}
        reports={0}
        onPick={() => undefined}
      />,
    );
    fireEvent.change(screen.getByRole("slider"), { target: { value: "1" } });
    const more = [
      ...snapshots,
      { ts: "2026-10-08T00:03:00Z", state: { n: 4 }, queries: [] },
    ];
    rerender(
      <SnapshotScrubber
        snapshots={more}
        reports={0}
        onPick={() => undefined}
      />,
    );
    expect(screen.getByText("4 of 4")).toBeTruthy();
  });

  it("follows the latest on a new report and keeps the focused input", () => {
    const { rerender } = render(
      <SnapshotScrubber
        snapshots={snapshots}
        reports={0}
        onPick={() => undefined}
      />,
    );
    const slider = screen.getByRole("slider");
    slider.focus();
    fireEvent.change(slider, { target: { value: "0" } });
    // A report that replaced the last snapshot: the count holds, the view left the pick.
    rerender(
      <SnapshotScrubber
        snapshots={snapshots}
        reports={1}
        onPick={() => undefined}
      />,
    );
    expect(screen.getByText("3 of 3")).toBeTruthy();
    expect(document.activeElement).toBe(slider);
  });
});
