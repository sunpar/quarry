import type { ViewerConfigUpdate } from "@finos/perspective-viewer";
import type { Agg, Column, Filter, QuerySpec, Sort } from "@/shared/api-types";

const OPS: Record<string, Filter["op"]> = {
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
  "is null": "is_null",
  "is not null": "not_null",
};

// No `stddev`: Perspective's is the population figure, the kernel's `std` the sample one.
const AGGS: Record<string, Agg["fn"]> = {
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
};

// Perspective sums integers and floats by default; Decimal and Int128 arrive as floats.
const NUMERIC = /^(Int|UInt|Float|Decimal)/;

export interface MappedSpec {
  spec: QuerySpec;
  dropped: string[];
}

/**
 * Perspective's saved config as a query spec; what the spec cannot say is listed in `dropped`.
 * `schema` picks each column's default aggregate as Perspective does; unknown columns count.
 */
export function perspectiveToSpec(
  dataset: string,
  config: ViewerConfigUpdate,
  schema: Column[] = [],
): MappedSpec {
  const dropped: string[] = [];
  const expressions = new Set(Object.keys(config.expressions ?? {}));
  for (const name of expressions) dropped.push(`expression ${name}`);
  const columns = (config.columns ?? []).filter(
    (c): c is string => c !== null && !expressions.has(c),
  );
  // Under "or", one filter reads the same as under "and"; more cannot join the spec's AND list.
  const given = config.filter ?? [];
  const anyOf = config.filter_op === "or" && given.length > 1;
  if (anyOf) dropped.push('filter_op "or"');
  const filters: Filter[] = [];
  for (const [col, op, term] of anyOf ? [] : given) {
    const mapped = OPS[op];
    if (mapped === undefined || expressions.has(col)) {
      dropped.push(`filter ${col} "${op}"`);
      continue;
    }
    if (mapped === "is_null" || mapped === "not_null")
      filters.push({ col, op: mapped });
    else filters.push({ col, op: mapped, value: term });
  }
  const sort: Sort[] = [];
  for (const [col, dir] of config.sort ?? []) {
    if ((dir === "asc" || dir === "desc") && !expressions.has(col))
      sort.push(dir === "desc" ? { col, desc: true } : { col });
    else dropped.push(`sort ${col} "${dir}"`);
  }
  const spec: QuerySpec = { dataset };
  if (filters.length > 0) spec.filters = filters;
  if (sort.length > 0) spec.sort = sort;
  const groupBy = config.group_by ?? [];
  if (groupBy.length === 0) {
    if (columns.length > 0) spec.select = columns;
    return { spec, dropped };
  }
  const aggs: Agg[] = [];
  for (const col of columns) {
    if (groupBy.includes(col)) continue;
    const dtype = schema.find((c) => c.name === col)?.dtype ?? "";
    const chosen =
      config.aggregates?.[col] ?? (NUMERIC.test(dtype) ? "sum" : "count");
    const name = typeof chosen === "string" ? chosen : chosen[0];
    const fn = AGGS[name];
    if (fn === undefined) dropped.push(`aggregate ${col} "${name}"`);
    else aggs.push({ col, fn });
  }
  const splitBy = config.split_by ?? [];
  const single = splitBy[0];
  const first = aggs[0];
  if (
    splitBy.length === 1 &&
    single !== undefined &&
    aggs.length === 1 &&
    first !== undefined
  ) {
    spec.pivot = {
      index: groupBy,
      columns: single,
      values: first.col,
      agg: first.fn,
    };
    return { spec, dropped };
  }
  if (splitBy.length > 0) dropped.push(`split_by ${splitBy.join(", ")}`);
  spec.group_by = groupBy;
  spec.aggs = aggs.length > 0 ? aggs : [{ col: groupBy[0] ?? "", fn: "count" }];
  return { spec, dropped };
}
