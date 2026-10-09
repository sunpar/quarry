import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient, ApiError } from "./client";

function fakeFetch(status: number, body: unknown) {
  return vi.fn<(input: string, init?: RequestInit) => Promise<Response>>(
    async () => new Response(JSON.stringify(body), { status }),
  );
}

afterEach(() => vi.restoreAllMocks());

describe("ApiClient", () => {
  it("sends the bearer token", async () => {
    const fetch = fakeFetch(200, []);
    const client = new ApiClient("tok", fetch);
    await client.listSessions();
    const init = fetch.mock.calls[0]?.[1] as RequestInit;
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer tok");
  });

  it("maps error responses to ApiError with the detail", async () => {
    const client = new ApiClient("tok", fakeFetch(409, { detail: "busy" }));
    await expect(client.postStep("s1", { prompt: "x" })).rejects.toMatchObject<
      Partial<ApiError>
    >({
      status: 409,
      detail: "busy",
    });
  });

  it("posts query specs as JSON", async () => {
    const fetch = fakeFetch(200, {
      schema: [],
      rows: [],
      arrow_base64: null,
      row_count: 0,
      truncated: false,
    });
    const client = new ApiClient("tok", fetch);
    await client.query("s1", { dataset: "df", limit: 5 });
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/sessions/s1/query");
    expect(init.body).toBe(JSON.stringify({ dataset: "df", limit: 5 }));
  });

  it("puts canvas cards as a bare array", async () => {
    const fetch = fakeFetch(200, {
      slug: "p",
      name: "p",
      description: "",
      created_at: "",
      updated_at: "",
      canvas: [],
    });
    const client = new ApiClient("tok", fetch);
    await client.setCanvas("p", [{ view: "v", x: 0, y: 0, w: 6, h: 8 }]);
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/projects/p/canvas");
    expect(init.method).toBe("PUT");
    expect(init.body).toBe(
      JSON.stringify([{ view: "v", x: 0, y: 0, w: 6, h: 8 }]),
    );
  });
});
