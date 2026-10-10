import { describe, expect, it } from "vitest";
import { perspectiveToSpec } from "./toSpec";

describe("perspectiveToSpec", () => {
  it("maps columns, filters and sorts for a flat view", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      columns: ["a", "b", null],
      filter: [
        ["a", ">", 1],
        ["b", "in", ["x", "y"]],
        ["b", "begins with", "x"],
        ["b", "ends with", "y"],
        ["a", "is null", null],
      ],
      sort: [
        ["a", "desc"],
        ["b", "col asc"],
      ],
    });
    expect(spec).toEqual({
      dataset: "t",
      select: ["a", "b"],
      filters: [
        { col: "a", op: "gt", value: 1 },
        { col: "b", op: "in", value: ["x", "y"] },
        { col: "b", op: "starts_with", value: "x" },
        { col: "a", op: "is_null" },
      ],
      sort: [{ col: "a", desc: true }],
    });
    expect(dropped).toEqual(['filter b "ends with"', 'sort b "col asc"']);
  });

  it("maps group_by with aggregates, and one split_by to a pivot", () => {
    const grouped = perspectiveToSpec("t", {
      group_by: ["k"],
      columns: ["v", "w"],
      aggregates: { v: "sum", w: "avg" },
    });
    expect(grouped.spec).toEqual({
      dataset: "t",
      group_by: ["k"],
      aggs: [
        { col: "v", fn: "sum" },
        { col: "w", fn: "mean" },
      ],
    });
    const pivot = perspectiveToSpec("t", {
      group_by: ["k"],
      split_by: ["c"],
      columns: ["v"],
      aggregates: { v: "sum" },
    });
    expect(pivot.spec).toEqual({
      dataset: "t",
      pivot: { index: ["k"], columns: "c", values: "v", agg: "sum" },
    });
    expect(pivot.dropped).toEqual([]);
  });

  it("drops what the spec cannot express and says so", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      group_by: ["k"],
      split_by: ["c", "d"],
      columns: ["v", "w"],
      aggregates: { v: "distinct count", w: "sum" },
      expressions: { e: '"v" * 2' },
    });
    expect(spec).toEqual({
      dataset: "t",
      group_by: ["k"],
      aggs: [{ col: "w", fn: "sum" }],
    });
    expect(dropped).toEqual([
      "expression e",
      'aggregate v "distinct count"',
      "split_by c, d",
    ]);
  });

  it.each(
    Object.entries({
      sum: "sum",
      avg: "mean",
      mean: "mean",
      min: "min",
      low: "min",
      max: "max",
      high: "max",
      count: "count",
      median: "median",
      first: "first",
      last: "last",
    }),
  )("maps the %s aggregate to %s", (aggregate, fn) => {
    const { spec } = perspectiveToSpec("t", {
      group_by: ["k"],
      columns: ["v"],
      aggregates: { v: aggregate },
    });
    expect(spec.aggs).toEqual([{ col: "v", fn }]);
  });

  it("drops stddev, which Perspective takes over the population", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      group_by: ["k"],
      columns: ["v"],
      aggregates: { v: "stddev" },
    });
    expect(spec.aggs).toEqual([{ col: "k", fn: "count" }]);
    expect(dropped).toEqual(['aggregate v "stddev"']);
  });

  it("leaves expression columns out of select, filters and sorts", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      columns: ["a", "e"],
      expressions: { e: '"a" + 1' },
      filter: [["e", ">", 1]],
      sort: [["e", "asc"]],
    });
    expect(spec).toEqual({ dataset: "t", select: ["a"] });
    expect(dropped).toEqual(["expression e", 'filter e ">"', 'sort e "asc"']);
  });

  it("counts the first key when every column is a group key", () => {
    const { spec } = perspectiveToSpec("t", {
      group_by: ["k"],
      columns: ["k"],
    });
    expect(spec.aggs).toEqual([{ col: "k", fn: "count" }]);
  });

  it("defaults the aggregate to count when none is set", () => {
    const { spec } = perspectiveToSpec("t", {
      group_by: ["k"],
      columns: ["v"],
    });
    expect(spec.aggs).toEqual([{ col: "v", fn: "count" }]);
  });

  it("sums numeric columns by default, as Perspective does", () => {
    const { spec } = perspectiveToSpec(
      "t",
      { group_by: ["k"], columns: ["i", "p", "d", "s", "gone"] },
      [
        { name: "i", dtype: "Int64" },
        { name: "p", dtype: "Decimal(38, 2)" },
        { name: "d", dtype: "Date" },
        { name: "s", dtype: "String" },
      ],
    );
    expect(spec.aggs).toEqual([
      { col: "i", fn: "sum" },
      { col: "p", fn: "sum" },
      { col: "d", fn: "count" },
      { col: "s", fn: "count" },
      { col: "gone", fn: "count" },
    ]);
  });

  it("sorts a grouped view by its keys and aggregated outputs only", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      group_by: ["k"],
      columns: ["v", "w"],
      aggregates: { v: "sum", w: "distinct count" },
      sort: [
        ["v", "desc"],
        ["k", "asc"],
        ["w", "asc"],
        ["x", "asc"],
      ],
    });
    expect(spec.sort).toEqual([{ col: "v_sum", desc: true }, { col: "k" }]);
    expect(dropped).toEqual([
      'aggregate w "distinct count"',
      'sort w "asc"',
      'sort x "asc"',
    ]);
  });

  it("sorts a pivot by its index keys only", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      group_by: ["k"],
      split_by: ["c"],
      columns: ["v"],
      aggregates: { v: "sum" },
      sort: [
        ["k", "desc"],
        ["v", "asc"],
      ],
    });
    expect(spec.sort).toEqual([{ col: "k", desc: true }]);
    expect(dropped).toEqual(['sort v "asc"']);
  });

  it("lists a split_by without group_by", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      columns: ["a"],
      split_by: ["c"],
    });
    expect(spec).toEqual({ dataset: "t", select: ["a"] });
    expect(dropped).toEqual(["split_by c"]);
  });

  it("leaves expression columns out of group_by and split_by", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      group_by: ["e", "k"],
      split_by: ["e"],
      columns: ["v"],
      aggregates: { v: "sum" },
      expressions: { e: '"v" * 2' },
    });
    expect(spec).toEqual({
      dataset: "t",
      group_by: ["k"],
      aggs: [{ col: "v", fn: "sum" }],
    });
    expect(dropped).toEqual(["expression e", "group_by e", "split_by e"]);
  });
});
