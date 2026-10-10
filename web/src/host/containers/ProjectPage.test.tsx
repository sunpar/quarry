import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { Project } from "@/shared/api-types";
import { ApiClient } from "../api/client";
import { ApiProvider } from "../api/context";
import { ProjectPage } from "./ProjectPage";

const project: Project = {
  meta: {
    slug: "p",
    name: "Momentum",
    description: "",
    created_at: "",
    updated_at: "",
    canvas: [],
  },
  datasets: [
    {
      name: "df",
      description: "",
      backing: "polars",
      schema: [],
      rows: 3,
      mode: "live",
      saved_at: "",
      source_session: "s1",
      source_step: "st1",
      validated: true,
      validation_error: null,
    },
  ],
  views: [],
};

afterEach(() => vi.restoreAllMocks());

function setup() {
  const gets: string[] = [];
  const fetchImpl = async (path: string, init?: RequestInit) => {
    gets.push(`${path} ${new Headers(init?.headers).get("authorization")}`);
    if (path === "/projects/p") return new Response(JSON.stringify(project));
    if (path === "/projects/p/export.ipynb") return new Response("{}");
    return new Response(JSON.stringify({ detail: "no recipe" }), {
      status: 404,
    });
  };
  // jsdom has no object URLs and does not navigate, so the anchor's click is caught.
  Object.assign(URL, {
    createObjectURL: () => "blob:1",
    revokeObjectURL: vi.fn(),
  });
  const saved: string[] = [];
  vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(function (
    this: HTMLAnchorElement,
  ) {
    saved.push(this.download);
  });
  const qc = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={qc}>
      <ApiProvider client={new ApiClient("t", fetchImpl)}>
        <ProjectPage slug="p" sessionId={null} onBack={() => undefined} />
      </ApiProvider>
    </QueryClientProvider>,
  );
  return { gets, saved };
}

describe("ProjectPage downloads", () => {
  it("exports the notebook with the token", async () => {
    const { gets, saved } = setup();
    fireEvent.click(
      await screen.findByRole("button", { name: "Export notebook" }),
    );
    await waitFor(() => expect(saved).toEqual(["p.ipynb"]));
    expect(gets).toContain("/projects/p/export.ipynb Bearer t");
  });

  it("asks for a dataset's recipe and shows a failure beside its button", async () => {
    const { gets, saved } = setup();
    fireEvent.click(await screen.findByRole("tab", { name: "Saved" }));
    fireEvent.click(
      await screen.findByRole("button", { name: "Download recipe df" }),
    );
    expect(await screen.findByText("404: no recipe")).toBeTruthy();
    expect(gets).toContain("/projects/p/datasets/df/recipe.py Bearer t");
    expect(saved).toEqual([]);
  });
});
