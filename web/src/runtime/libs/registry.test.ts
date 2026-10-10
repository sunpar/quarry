import { beforeEach, describe, expect, it } from "vitest";
import { licensed, setLicensed } from "./registry";

describe("licensed library registry", () => {
  beforeEach(() => setLicensed([]));

  it("answers null until the host registers a library", () => {
    expect(licensed("highcharts")).toBeNull();
    setLicensed([
      {
        id: "highcharts",
        entry: "/libs/highcharts/highstock.js",
        license: null,
      },
    ]);
    expect(licensed("highcharts")?.entry).toBe("/libs/highcharts/highstock.js");
    expect(licensed("scichart")).toBeNull();
  });
});
