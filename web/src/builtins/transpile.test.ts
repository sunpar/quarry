import { describe, expect, it } from "vitest";
import { transpile } from "@/runtime/loader";
import { MODULES } from "@/runtime/modules";

// Vitest compiles built-ins with Vite; the runtime compiles them with Sucrase.
const sources = import.meta.glob<string>("@builtin/*/component.tsx", {
  query: "?raw",
  import: "default",
  eager: true,
});

describe("built-ins under the runtime's transform", () => {
  it("finds every built-in", () => {
    const ids = Object.keys(sources).map((path) => path.split("/").at(-2));
    expect(ids).toEqual(
      expect.arrayContaining(["data-table", "time-series", "pivot"]),
    );
  });

  it.each(Object.entries(sources))(
    "%s imports only modules the runtime serves",
    (_path, source) => {
      const { names } = transpile(source);
      expect(names.filter((name) => !Object.hasOwn(MODULES, name))).toEqual([]);
    },
  );
});
