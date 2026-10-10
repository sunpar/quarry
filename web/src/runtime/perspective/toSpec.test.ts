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
      "==": "eq",
      "!=": "ne",
      "<": "lt",
      "<=": "le",
      ">": "gt",
      ">=": "ge",
      in: "in",
      "not in": "not_in",
      contains: "contains",
      "begins with": "starts_with",
    }),
  )("maps the %s filter to %s", (op, mapped) => {
    const { spec } = perspectiveToSpec("t", { filter: [["a", op, 1]] });
    expect(spec.filters).toEqual([{ col: "a", op: mapped, value: 1 }]);
  });

  it("maps a not-null filter without a value", () => {
    const { spec } = perspectiveToSpec("t", {
      filter: [["a", "is not null", null]],
    });
    expect(spec.filters).toEqual([{ col: "a", op: "not_null" }]);
  });

  it.each(
    Object.entries({
      sum: "sum",
      avg: "mean",
      min: "min",
      max: "max",
      count: "count",
      median: "median",
      stddev: "std",
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
});
