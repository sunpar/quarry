import { describe, expect, it } from "vitest";
import type { Column } from "@/shared/api-types";
import { perspectiveToSpec } from "./toSpec";

const schema: Column[] = [
  { name: "i", dtype: "Int64" },
  { name: "f", dtype: "Float64" },
  { name: "b", dtype: "Boolean" },
  { name: "s", dtype: "String" },
  { name: "d", dtype: "Date" },
  { name: "t", dtype: "Datetime(time_unit='us', time_zone=None)" },
  { name: "z", dtype: "Datetime(time_unit='ns', time_zone='UTC')" },
  { name: "p", dtype: "Decimal(precision=38, scale=2)" },
];

describe("perspectiveToSpec filters", () => {
  it.each(
    Object.entries({
      "==": "eq",
      "<": "lt",
      "<=": "le",
      ">": "gt",
      ">=": "ge",
      in: "in",
      contains: "contains",
      "begins with": "starts_with",
    }),
  )("maps the %s filter to %s", (op, mapped) => {
    const term = op === "in" ? ["x"] : "x";
    const { spec } = perspectiveToSpec("t", { filter: [["a", op, term]] });
    expect(spec.filters).toEqual([{ col: "a", op: mapped, value: term }]);
  });

  it("drops != and not in, which keep null rows the kernel would skip", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      filter: [
        ["a", "!=", "x"],
        ["a", "not in", ["x"]],
      ],
    });
    expect(spec.filters).toBeUndefined();
    expect(dropped).toEqual(['filter a "!="', 'filter a "not in"']);
  });

  it("maps a not-null filter without a value", () => {
    const { spec } = perspectiveToSpec("t", {
      filter: [["a", "is not null", null]],
    });
    expect(spec.filters).toEqual([{ col: "a", op: "not_null" }]);
  });

  it("drops every filter under or, but not a lone one", () => {
    const either = perspectiveToSpec("t", {
      filter_op: "or",
      filter: [
        ["a", ">", 1],
        ["b", "ends with", "x"],
      ],
      sort: [["a", "asc"]],
    });
    expect(either.spec).toEqual({ dataset: "t", sort: [{ col: "a" }] });
    expect(either.dropped).toEqual(['filter_op "or"']);
    const lone = perspectiveToSpec("t", {
      filter_op: "or",
      filter: [["a", ">", 1]],
    });
    expect(lone.spec.filters).toEqual([{ col: "a", op: "gt", value: 1 }]);
    expect(lone.dropped).toEqual([]);
  });

  it("lists filters the kernel would refuse, and leaves them out of the or count", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      filter_op: "or",
      filter: [
        ["a", "==", null],
        ["b", "in", []],
        ["c", "in", ["x", null]],
        ["d", "in", "x"],
        ["e", ">", 1],
      ],
    });
    expect(spec.filters).toEqual([{ col: "e", op: "gt", value: 1 }]);
    expect(dropped).toEqual([
      'filter a "=="',
      'filter b "in"',
      'filter c "in"',
      'filter d "in"',
    ]);
  });

  it("lists a scalar filter given a list and a text filter given a number", () => {
    const { spec, dropped } = perspectiveToSpec("t", {
      filter: [
        ["a", "==", ["x"]],
        ["a", "contains", 1],
      ],
    });
    expect(spec.filters).toBeUndefined();
    expect(dropped).toEqual(['filter a "=="', 'filter a "contains"']);
  });

  it("reads the viewer's string lists as the column's type", () => {
    const { spec, dropped } = perspectiveToSpec(
      "t",
      {
        filter: [
          ["i", "in", ["1", " 2"]],
          ["f", "in", ["1.5"]],
          ["b", "in", ["true", "no"]],
          ["s", "in", ["1"]],
          ["i", "in", ["1.5"]],
          ["i", "in", ["1e3"]],
          ["i", "in", ["0x10"]],
          ["i", "in", ["12abc"]],
          ["f", "in", ["", "x"]],
          ["p", "in", ["1.5"]],
        ],
      },
      schema,
    );
    expect(spec.filters).toEqual([
      { col: "i", op: "in", value: [1, 2] },
      { col: "f", op: "in", value: [1.5] },
      { col: "b", op: "in", value: [true, false] },
      { col: "s", op: "in", value: ["1"] },
    ]);
    // The engine reads integer items with `stoll`, which `Number()` matches only on plain
    // digits. The kernel cannot match a Decimal column against a list of numbers.
    expect(dropped).toEqual([
      'filter i "in"',
      'filter i "in"',
      'filter i "in"',
      'filter i "in"',
      'filter f "in"',
      'filter p "in"',
    ]);
  });

  it("turns epoch milliseconds into the UTC time the kernel reads", () => {
    const { spec, dropped } = perspectiveToSpec(
      "t",
      {
        filter: [
          ["t", ">", Date.UTC(2024, 0, 1)],
          ["z", "<=", Date.UTC(2024, 0, 1, 9, 30, 0, 250)],
          ["t", "==", "2024-01-01"],
          ["t", ">", 1e20],
        ],
      },
      schema,
    );
    expect(spec.filters).toEqual([
      { col: "t", op: "gt", value: "2024-01-01T00:00:00.000" },
      { col: "z", op: "le", value: "2024-01-01T09:30:00.250" },
    ]);
    expect(dropped).toEqual(['filter t "=="', 'filter t ">"']);
  });

  it("keeps the viewer's date strings and turns milliseconds into a UTC date", () => {
    const { spec, dropped } = perspectiveToSpec(
      "t",
      {
        filter: [
          ["d", "==", "2024-03-01"],
          ["d", ">", Date.UTC(2024, 2, 1, 23)],
          ["d", "<", "2024-03-01T00:00"],
        ],
      },
      schema,
    );
    expect(spec.filters).toEqual([
      { col: "d", op: "eq", value: "2024-03-01" },
      { col: "d", op: "gt", value: "2024-03-01" },
    ]);
    expect(dropped).toEqual(['filter d "<"']);
  });

  it("lists dates outside the years 1 to 9999 the kernel can parse", () => {
    // `Date.UTC` reads years 0 to 99 as 1900 to 1999.
    const year0 = new Date(0).setUTCFullYear(0);
    const year1 = new Date(0).setUTCFullYear(1);
    const { spec, dropped } = perspectiveToSpec(
      "t",
      {
        filter: [
          ["t", "<", Date.UTC(10000, 0, 1)],
          ["t", ">", year0],
          ["d", "<", Date.UTC(10000, 0, 1)],
          ["d", ">", year0],
          ["d", "==", "0000-01-01"],
          ["d", "<=", Date.UTC(9999, 11, 31)],
          ["d", ">=", year1],
        ],
      },
      schema,
    );
    expect(spec.filters).toEqual([
      { col: "d", op: "le", value: "9999-12-31" },
      { col: "d", op: "ge", value: "0001-01-01" },
    ]);
    expect(dropped).toEqual([
      'filter t "<"',
      'filter t ">"',
      'filter d "<"',
      'filter d ">"',
      'filter d "=="',
    ]);
  });
});
