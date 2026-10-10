import type { ComponentType } from "react";
import { transform } from "sucrase";

export interface ViewProps {
  datasets: string[];
}

export type ViewComponent = ComponentType<ViewProps>;
export type ModuleTable = Record<string, () => Promise<unknown>>;

const REQUIRE = /require\((['"])([^'"]+)\1\)/g;

/** A view's source as the runtime runs it, and the module names it requires. */
export function transpile(source: string): { code: string; names: string[] } {
  const { code } = transform(source, {
    transforms: ["typescript", "jsx", "imports"],
    jsxRuntime: "automatic",
    production: true,
    keepUnusedImports: true,
  });
  // The scan only preloads allowed modules: it also matches text in strings and comments,
  // so the refusal belongs to `require`, which sees only real imports.
  const names = new Set([...code.matchAll(REQUIRE)].map((m) => m[2] ?? ""));
  return { code, names: [...names] };
}

export async function loadComponent(
  source: string,
  table: ModuleTable,
): Promise<ViewComponent> {
  const { code, names } = transpile(source);
  const resolved = new Map<string, unknown>();
  for (const name of names) {
    // Own keys only: "constructor" and friends live on the prototype of every object.
    const load = Object.hasOwn(table, name) ? table[name] : undefined;
    if (load !== undefined) resolved.set(name, await load());
  }
  const require = (name: string): unknown => {
    if (!resolved.has(name)) {
      const allowed = Object.keys(table).join(", ");
      throw new Error(
        `"${name}" is not available in views. Allowed imports: ${allowed}`,
      );
    }
    return resolved.get(name);
  };
  const module: { exports: Record<string, unknown> } = { exports: {} };
  const factory = new Function("require", "exports", "module", code) as (
    r: typeof require,
    e: Record<string, unknown>,
    m: typeof module,
  ) => void;
  factory(require, module.exports, module);
  const component = module.exports["default"];
  if (!isComponent(component)) {
    throw new Error("the view must `export default` a React component");
  }
  return component;
}

// `memo`, `forwardRef` and `lazy` wrap a component in an object tagged with `$$typeof`.
function isComponent(value: unknown): value is ViewComponent {
  if (typeof value === "function") return true;
  return typeof value === "object" && value !== null && "$$typeof" in value;
}
