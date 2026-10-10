import type { ViewerConfigUpdate } from "@finos/perspective-viewer";
import type { Agg, Column, QuerySpec, Sort } from "@/shared/api-types";
import { mapFilters } from "./filters";

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
 * `schema` types filter terms and picks default aggregates as Perspective does.
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
  const dtypes = new Map(schema.map((c) => [c.name, c.dtype]));
  const spec: QuerySpec = { dataset };
  const filters = mapFilters(config, expressions, dtypes, dropped);
  if (filters.length > 0) spec.filters = filters;
  const groupBy = keys(config.group_by, "group_by", expressions, dropped);
  const splitBy = keys(config.split_by, "split_by", expressions, dropped);
  // Sorts run on the output, so each names an output column or is dropped.
  let output = (col: string): string | undefined =>
    expressions.has(col) ? undefined : col;
  if (groupBy.length === 0) {
    if (splitBy.length > 0) dropped.push(`split_by ${splitBy.join(", ")}`);
    if (columns.length > 0) spec.select = columns;
  } else {
    const aggs: Agg[] = [];
    for (const col of columns) {
      if (groupBy.includes(col)) continue;
      const dtype = dtypes.get(col) ?? "";
      const chosen =
        config.aggregates?.[col] ?? (NUMERIC.test(dtype) ? "sum" : "count");
      const name = typeof chosen === "string" ? chosen : chosen[0];
      const fn = AGGS[name];
      if (fn === undefined) dropped.push(`aggregate ${col} "${name}"`);
      else aggs.push({ col, fn });
    }
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
      output = (col) => (groupBy.includes(col) ? col : undefined);
    } else {
      if (splitBy.length > 0) dropped.push(`split_by ${splitBy.join(", ")}`);
      spec.group_by = groupBy;
      spec.aggs =
        aggs.length > 0 ? aggs : [{ col: groupBy[0] ?? "", fn: "count" }];
      // Grouped columns are named as the kernel names them (`Agg.name`).
      output = (col) => {
        if (groupBy.includes(col)) return col;
        const agg = aggs.find((a) => a.col === col);
        return agg === undefined ? undefined : `${agg.col}_${agg.fn}`;
      };
    }
  }
  const sort: Sort[] = [];
  for (const [col, dir] of config.sort ?? []) {
    const name = output(col);
    if ((dir === "asc" || dir === "desc") && name !== undefined)
      sort.push(dir === "desc" ? { col: name, desc: true } : { col: name });
    else dropped.push(`sort ${col} "${dir}"`);
  }
  if (sort.length > 0) spec.sort = sort;
  return { spec, dropped };
}

/** Group or split keys the dataset has; an expression key is listed instead. */
function keys(
  given: string[] | undefined,
  role: string,
  expressions: Set<string>,
  dropped: string[],
): string[] {
  const kept: string[] = [];
  for (const col of given ?? [])
    if (expressions.has(col)) dropped.push(`${role} ${col}`);
    else kept.push(col);
  return kept;
}
