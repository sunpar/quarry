import { describe, expect, it } from "vitest";
import { readSession, readToken, sessionHash } from "./auth";

describe("readToken", () => {
  it("reads token from the fragment", () => {
    expect(readToken("#token=abc123")).toBe("abc123");
  });
  it("ignores other fragments", () => {
    expect(readToken("#foo=bar")).toBeNull();
    expect(readToken("")).toBeNull();
  });
});

describe("readSession", () => {
  it("reads the session next to the token", () => {
    expect(readSession("#token=abc&session=s1")).toBe("s1");
  });
  it("is null without a session", () => {
    expect(readSession("#token=abc")).toBeNull();
    expect(readSession("#token=abc&session=")).toBeNull();
  });
});

describe("sessionHash", () => {
  it("keeps the token and names the session", () => {
    const hash = sessionHash("abc", "s1");
    expect(hash).toBe("#token=abc&session=s1");
    expect(readToken(hash)).toBe("abc");
    expect(readSession(hash)).toBe("s1");
  });
});
