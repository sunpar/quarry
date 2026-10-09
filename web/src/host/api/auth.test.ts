import { describe, expect, it } from "vitest";
import { readToken } from "./auth";

describe("readToken", () => {
  it("reads token from the fragment", () => {
    expect(readToken("#token=abc123")).toBe("abc123");
  });
  it("ignores other fragments", () => {
    expect(readToken("#foo=bar")).toBeNull();
    expect(readToken("")).toBeNull();
  });
});
