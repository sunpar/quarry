import type { ViewerConfigUpdate } from "@finos/perspective-viewer";
import type { Filter } from "@/shared/api-types";
import type { Json } from "@/shared/json";

type Term = string | number | boolean | null;

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

const DAY = /^\d{4}-\d{2}-\d{2}$/;

/**
 * Perspective's filters as spec filters the kernel accepts and compares as Perspective
 * means them. Each one the spec cannot say is pushed to `dropped`.
 */
export function mapFilters(
  config: ViewerConfigUpdate,
  expressions: Set<string>,
  dtypes: Map<string, string>,
  dropped: string[],
): Filter[] {
  // Filters the spec could never carry are listed first and leave the "or" count:
  // one with no term yet, as a column just dropped on the filter bar has, and a list
  // that is missing, empty or holds a null.
  const candidates: (Filter | string)[] = [];
  for (const [col, op, term] of config.filter ?? []) {
    const label = `filter ${col} "${op}"`;
    const mapped = OPS[op];
    const list = mapped === "in" || mapped === "not_in";
    const valued = mapped !== "is_null" && mapped !== "not_null";
    if (
      (mapped !== undefined && valued && term === null) ||
      (list &&
        !(Array.isArray(term) && term.length > 0 && !term.includes(null)))
    ) {
      dropped.push(label);
      continue;
    }
    const filter =
      mapped === undefined || expressions.has(col)
        ? undefined
        : toFilter(col, mapped, term, dtypes.get(col));
    candidates.push(filter ?? label);
  }
  // The spec's filters all apply; under "or", one filter reads the same as under "and".
  if (config.filter_op === "or" && candidates.length > 1) {
    dropped.push('filter_op "or"');
    return [];
  }
  const filters: Filter[] = [];
  for (const c of candidates)
    if (typeof c === "string") dropped.push(c);
    else filters.push(c);
  return filters;
}

function toFilter(
  col: string,
  op: Filter["op"],
  term: Term | Term[],
  dtype: string | undefined,
): Filter | undefined {
  if (op === "is_null" || op === "not_null") return { col, op };
  if (op === "in" || op === "not_in") {
    // polars `is_in` refuses Float64 items against a Decimal column.
    if (!Array.isArray(term) || dtype?.startsWith("Decimal")) return undefined;
    const value: Json[] = [];
    for (const item of term) {
      const coerced = coerceTerm(item, dtype);
      if (coerced === undefined) return undefined;
      value.push(coerced);
    }
    return { col, op, value };
  }
  if (Array.isArray(term)) return undefined;
  const value = coerceTerm(term, dtype);
  if (value === undefined) return undefined;
  if ((op === "contains" || op === "starts_with") && typeof value !== "string")
    return undefined;
  return { col, op, value };
}

/**
 * A term as a literal the kernel compares with `dtype` as Perspective's engine does;
 * undefined when that cannot be exact. The viewer writes `in` lists as strings, a date
 * as "YYYY-MM-DD" and a datetime as epoch milliseconds (`str_to_utc_posix`).
 */
function coerceTerm(term: Term, dtype: string | undefined): Json | undefined {
  if (term === null) return undefined;
  if (dtype === undefined) return term;
  if (/^(Int|UInt)/.test(dtype)) {
    const n = toNumber(term);
    return Number.isInteger(n) ? n : undefined;
  }
  if (/^(Float|Decimal)/.test(dtype)) {
    const n = toNumber(term);
    return Number.isFinite(n) ? n : undefined;
  }
  // The engine reads a string as `val == "true"` and a number as `val == 1`.
  if (dtype === "Boolean")
    return typeof term === "string"
      ? term === "true"
      : term === true || term === 1;
  if (dtype === "String") return typeof term === "string" ? term : undefined;
  // A datetime string is dropped: the kernel and the engine parse offsets differently.
  if (dtype.startsWith("Datetime"))
    return typeof term === "number" ? utcIso(term)?.slice(0, -1) : undefined;
  // The engine reads milliseconds as their UTC calendar day (`gmtime`).
  if (dtype === "Date") {
    if (typeof term === "number") return utcIso(term)?.slice(0, 10);
    return typeof term === "string" && DAY.test(term) ? term : undefined;
  }
  return term;
}

/** Naive datetime columns hold UTC wall clocks, and the kernel reads a naive string as UTC. */
function utcIso(ms: number): string | undefined {
  const time = new Date(ms);
  return Number.isNaN(time.getTime()) ? undefined : time.toISOString();
}

function toNumber(term: Exclude<Term, null>): number {
  if (typeof term === "number") return term;
  return typeof term === "string" && term.trim() !== "" ? Number(term) : NaN;
}
