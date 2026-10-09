import type { ComponentType } from "react";
import { transform } from "sucrase";

export interface ViewProps {
  datasets: string[];
}

export type ViewComponent = ComponentType<ViewProps>;
export type ModuleTable = Record<string, () => Promise<unknown>>;

const REQUIRE = /require\((['"])([^'"]+)\1\)/g;

export async function loadComponent(
  source: string,
  table: ModuleTable,
): Promise<ViewComponent> {
  const { code } = transform(source, {
    transforms: ["typescript", "jsx", "imports"],
    jsxRuntime: "automatic",
    production: true,
    keepUnusedImports: true,
  });
  const names = new Set([...code.matchAll(REQUIRE)].map((m) => m[2] ?? ""));
  const resolved = new Map<string, unknown>();
  for (const name of names) {
    // Own keys only: "constructor" and friends live on the prototype of every object.
    const load = Object.hasOwn(table, name) ? table[name] : undefined;
    if (load === undefined) {
      const allowed = Object.keys(table).join(", ");
      throw new Error(
        `"${name}" is not available in views. Allowed imports: ${allowed}`,
      );
    }
    resolved.set(name, await load());
  }
  const require = (name: string): unknown => {
    if (!resolved.has(name))
      throw new Error(`"${name}" is not available in views`);
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
