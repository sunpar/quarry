import { useState } from "react";
import type { Column, Filter } from "@/shared/api-types";
import type { Json } from "@/shared/json";

export type TableFilter = { col: string; op: Filter["op"]; value?: Json };

const LABELS: Partial<Record<Filter["op"], string>> = {
  eq: "equals",
  ne: "does not equal",
  lt: "less than",
  le: "at most",
  gt: "greater than",
  ge: "at least",
  contains: "contains",
  starts_with: "starts with",
  is_null: "is null",
  not_null: "is not null",
};
const NULL_OPS: Filter["op"][] = ["is_null", "not_null"];
const COMPARISONS: Filter["op"][] = ["eq", "ne", "lt", "le", "gt", "ge"];

function operators(dtype: string): Filter["op"][] {
  if (dtype === "String")
    return ["eq", "ne", "contains", "starts_with", ...NULL_OPS];
  if (/^(Int|UInt|Float)/.test(dtype) || dtype === "Date")
    return [...COMPARISONS, ...NULL_OPS];
  return NULL_OPS;
}

function matches(filter: TableFilter, dtype: string): boolean {
  if (!operators(dtype).includes(filter.op)) return false;
  if (NULL_OPS.includes(filter.op))
    return filter.value === undefined || filter.value === null;
  if (/^(Int|UInt|Float)/.test(dtype))
    return (
      typeof filter.value === "number" &&
      Number.isFinite(filter.value) &&
      (!/^(Int|UInt)/.test(dtype) || Number.isSafeInteger(filter.value))
    );
  return typeof filter.value === "string";
}

interface Props {
  schema: Column[] | null;
  filters: TableFilter[];
  onChange: (filters: TableFilter[]) => void;
  sort: { col: string; desc: boolean } | null;
  onClearSort: () => void;
}

export function TableFilters({
  schema,
  filters,
  onChange,
  sort,
  onClearSort,
}: Props) {
  const [selected, setSelected] = useState("");
  const [op, setOp] = useState<Filter["op"]>("eq");
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const column = schema?.find((c) => c.name === selected) ?? schema?.[0];
  const options = operators(column?.dtype ?? "");
  const operator = options.includes(op) ? op : options[0]!;
  const valued = !NULL_OPS.includes(operator);

  function apply() {
    if (column === undefined) return;
    let term: Json = value;
    if (valued && /^(Int|UInt|Float)/.test(column.dtype)) {
      term = Number(value);
      if (value.trim() === "" || !Number.isFinite(term)) {
        setError("Enter a finite number.");
        return;
      }
      if (
        !Number.isSafeInteger(term) &&
        (/^(Int|UInt)/.test(column.dtype) || Number.isInteger(term))
      ) {
        setError(
          "Enter a safe integer between -9007199254740991 and 9007199254740991.",
        );
        return;
      }
    }
    if (valued && column.dtype === "Date") {
      const date = new Date(`${value}T00:00:00Z`);
      if (
        !/^\d{4}-\d{2}-\d{2}$/.test(value) ||
        Number.isNaN(date.getTime()) ||
        date.toISOString().slice(0, 10) !== value
      ) {
        setError("Enter a date as YYYY-MM-DD.");
        return;
      }
    }
    setError(null);
    onChange([
      ...filters,
      { col: column.name, op: operator, ...(valued ? { value: term } : {}) },
    ]);
  }

  return (
    <div className="border-b border-border px-3 py-2 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <label className="flex items-center gap-1 text-muted-foreground">
          Column
          <select
            aria-label="Filter column"
            value={column?.name ?? ""}
            disabled={!schema?.length}
            className="max-w-48 bg-transparent text-foreground"
            onChange={(event) => {
              setSelected(event.target.value);
              setOp("eq");
              setValue("");
              setError(null);
            }}
          >
            {(schema ?? []).map((c) => (
              <option key={c.name} value={c.name}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <select
          aria-label="Filter operator"
          value={operator}
          className="bg-transparent text-foreground"
          onChange={(event) => {
            setOp(event.target.value as Filter["op"]);
            setError(null);
          }}
        >
          {options.map((choice) => (
            <option key={choice} value={choice}>
              {LABELS[choice]}
            </option>
          ))}
        </select>
        {valued && (
          <input
            aria-label="Filter value"
            value={value}
            type={column?.dtype === "Date" ? "date" : "text"}
            className="w-40 rounded border border-border bg-transparent px-2 py-1 text-foreground"
            onChange={(event) => {
              setValue(event.target.value);
              setError(null);
            }}
          />
        )}
        <button
          type="button"
          onClick={apply}
          disabled={column === undefined}
          className="rounded border border-border px-2 py-1 disabled:opacity-50"
        >
          Apply filter
        </button>
        {sort !== null && (
          <button
            type="button"
            onClick={onClearSort}
            className="text-muted-foreground underline"
          >
            Clear sort ({sort.col})
          </button>
        )}
      </div>
      {column !== undefined && options.length === NULL_OPS.length && (
        <p className="mt-1 text-muted-foreground">
          Only null filters are available for {column.dtype}.
        </p>
      )}
      {error !== null && (
        <p role="alert" className="mt-1 text-destructive">
          {error}
        </p>
      )}
      {filters.length > 0 && (
        <ul aria-label="Active filters" className="mt-2 flex flex-wrap gap-2">
          {filters.map((filter, index) => {
            const dtype = schema?.find((c) => c.name === filter.col)?.dtype;
            const issue =
              schema === null
                ? null
                : dtype === undefined
                  ? "column unavailable"
                  : !matches(filter, dtype)
                    ? `filter does not match ${dtype}`
                    : null;
            return (
              <li
                key={index}
                className="flex items-center gap-2 rounded border border-border px-2 py-1"
              >
                <span>
                  {filter.col} {LABELS[filter.op] ?? filter.op}
                  {NULL_OPS.includes(filter.op)
                    ? ""
                    : ` ${JSON.stringify(filter.value)}`}
                </span>
                {issue !== null && (
                  <span className="text-destructive">
                    {filter.col}: {issue}
                  </span>
                )}
                <button
                  type="button"
                  aria-label={`Remove ${filter.col} filter ${index + 1}`}
                  className="text-muted-foreground underline"
                  onClick={() =>
                    onChange(filters.filter((_, i) => i !== index))
                  }
                >
                  Remove
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
