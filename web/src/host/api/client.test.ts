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

  it("gets the licensed library statuses", async () => {
    const fetch = fakeFetch(200, []);
    const client = new ApiClient("tok", fetch);
    await expect(client.libraries()).resolves.toEqual([]);
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/libraries");
    expect(init.method).toBe("GET");
  });

  it("posts the queries to render as code", async () => {
    const fetch = fakeFetch(200, { code: "x = 1" });
    const client = new ApiClient("tok", fetch);
    await expect(client.toCode("s1", [{ dataset: "df" }])).resolves.toEqual({
      code: "x = 1",
    });
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/sessions/s1/to-code");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify({ queries: [{ dataset: "df" }] }));
  });

  it("posts a component to the library", async () => {
    const fetch = fakeFetch(201, { id: "my-scatter" });
    const client = new ApiClient("tok", fetch);
    const body = {
      id: "my-scatter",
      name: "My scatter",
      description: "",
      tags: [],
      source: "export default 1",
      session_id: null,
      dataset: null,
    };
    await client.saveComponent(body);
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/components");
    expect(init.method).toBe("POST");
    expect(init.body).toBe(JSON.stringify(body));
  });

  it("fetches a download with the token and rejects a missing file", async () => {
    const fetch = vi.fn<
      (input: string, init?: RequestInit) => Promise<Response>
    >(async () => new Response("print(1)"));
    const client = new ApiClient("tok", fetch);
    const blob = await client.fetchBlob("/projects/p/datasets/df/recipe.py");
    await expect(blob.text()).resolves.toBe("print(1)");
    const [url, init] = fetch.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/projects/p/datasets/df/recipe.py");
    expect(new Headers(init.headers).get("authorization")).toBe("Bearer tok");
    const missing = new ApiClient("tok", fakeFetch(404, { detail: "no df" }));
    await expect(missing.fetchBlob("/x")).rejects.toMatchObject<
      Partial<ApiError>
    >({ status: 404, detail: "no df" });
  });
});
