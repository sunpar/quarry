import { describe, expect, it } from "vitest";
import { decodeBase64 } from "./base64";

describe("decodeBase64", () => {
  it("decodes to the original bytes", () => {
    const bytes = new Uint8Array(decodeBase64("AAEC/w=="));
    expect([...bytes]).toEqual([0, 1, 2, 255]);
  });
  it("returns an empty buffer for an empty string", () => {
    expect(decodeBase64("").byteLength).toBe(0);
  });
});
