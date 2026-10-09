import { describe, expect, it } from "vitest";
import { loadComponent, type ModuleTable } from "./loader";

const table: ModuleTable = {
  react: () => import("react").then((m) => ({ __esModule: true, ...m })),
  "react/jsx-runtime": () =>
    import("react/jsx-runtime").then((m) => ({ __esModule: true, ...m })),
  "@quarry/hooks": async () => ({
    __esModule: true,
    useQuery: () => ({ status: "loading" }),
  }),
};

describe("loadComponent", () => {
  it("transpiles TSX and returns the default export", async () => {
    const source = `
      import { useQuery } from "@quarry/hooks";
      export default function V({ datasets }: { datasets: string[] }) {
        const q = useQuery({ dataset: datasets[0] });
        return <div>{q.status}</div>;
      }`;
    const component = await loadComponent(source, table);
    expect(typeof component).toBe("function");
  });

  it("accepts a memoised or forwarded default export", async () => {
    const source = `
      import { memo } from "react";
      export default memo(function V() { return <div>memo</div>; });`;
    const component = await loadComponent(source, table);
    expect(typeof component).toBe("object");
  });

  it("refuses imports outside the allowlist with a clear message", async () => {
    const source = `import axios from "axios"; export default () => null;`;
    await expect(loadComponent(source, table)).rejects.toThrow(
      '"axios" is not available in views',
    );
  });

  it("ignores import-like text in strings and comments", async () => {
    const source = `
      // require("fs")
      export default function V() { return <pre>{"require('fs')"}</pre>; }`;
    const component = await loadComponent(source, table);
    expect(typeof component).toBe("function");
  });

  it("refuses names inherited from Object.prototype", async () => {
    const source = `import x from "constructor"; export default () => null;`;
    await expect(loadComponent(source, table)).rejects.toThrow(
      '"constructor" is not available in views',
    );
  });

  it("requires a default export", async () => {
    await expect(loadComponent(`export const x = 1;`, table)).rejects.toThrow(
      "export default",
    );
  });

  it("reports syntax errors", async () => {
    await expect(loadComponent(`const a = (`, table)).rejects.toThrow(
      /Unexpected token/,
    );
  });
});
