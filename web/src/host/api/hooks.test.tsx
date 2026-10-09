import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it } from "vitest";
import { ApiProvider } from "./context";
import { ApiClient } from "./client";
import { useSession } from "./hooks";

function wrapper(client: ApiClient) {
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={qc}>
      <ApiProvider client={client}>{children}</ApiProvider>
    </QueryClientProvider>
  );
}

describe("useSession", () => {
  it("polls while the last step is running", async () => {
    let calls = 0;
    const fetchImpl = async () => {
      calls += 1;
      const status = calls < 3 ? "running" : "ok";
      const body = {
        meta: {
          id: "s1",
          title: "t",
          created_at: "",
          provider: { name: "f", model: "m" },
        },
        steps: [
          {
            id: "x",
            index: 0,
            kind: "prompt",
            prompt: "p",
            code: "",
            status,
            error: null,
            note: "",
            stdout_tail: "",
            stderr_tail: "",
            reads: [],
            writes: [],
            defines: [],
            datasets: [],
            view: null,
            created_at: "",
            duration_ms: 0,
          },
        ],
      };
      return new Response(JSON.stringify(body), { status: 200 });
    };
    const { result } = renderHook(() => useSession("s1"), {
      wrapper: wrapper(new ApiClient("t", fetchImpl)),
    });
    await waitFor(
      () => expect(result.current.data?.steps[0]?.status).toBe("ok"),
      { timeout: 5000 },
    );
    expect(calls).toBeGreaterThanOrEqual(3);
  });
});
