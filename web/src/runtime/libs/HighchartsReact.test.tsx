import { act, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { HighchartsReact } from "./HighchartsReact";
import { setLicensed } from "./registry";

afterEach(() => {
  setLicensed([]);
  document.head.querySelectorAll("script").forEach((s) => s.remove());
  delete window.Highcharts;
});

describe("HighchartsReact", () => {
  it("builds the chart once Highstock loads, then updates and destroys it", async () => {
    const chart = { update: vi.fn(), destroy: vi.fn() };
    const stockChart = vi.fn(() => chart);
    setLicensed([
      {
        id: "highcharts",
        entry: "/libs/highcharts/highstock.js",
        license: null,
      },
    ]);
    const view = render(<HighchartsReact options={{ title: "first" }} />);
    // Options that change while the script loads are the ones the chart starts from.
    const loaded = { title: "loaded" };
    view.rerender(<HighchartsReact options={loaded} />);
    window.Highcharts = { stockChart, chart: vi.fn() };
    await act(async () => {
      document.querySelector("script")?.dispatchEvent(new Event("load"));
    });
    await vi.waitFor(() =>
      expect(stockChart).toHaveBeenCalledWith(
        expect.any(HTMLDivElement),
        loaded,
      ),
    );
    const later = { title: "later" };
    view.rerender(<HighchartsReact options={later} />);
    expect(chart.update).toHaveBeenCalledWith(later, true);
    expect(stockChart).toHaveBeenCalledTimes(1);
    view.unmount();
    expect(chart.destroy).toHaveBeenCalledTimes(1);
  });
});
