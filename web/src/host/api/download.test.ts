import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClient } from "./client";
import { downloadFile } from "./download";

afterEach(() => vi.useRealTimers());

describe("downloadFile", () => {
  it("saves the fetched bytes under the filename and revokes the url later", async () => {
    vi.useFakeTimers();
    // jsdom has no object URLs.
    const createObjectURL = vi.fn(() => "blob:1");
    const revokeObjectURL = vi.fn();
    Object.assign(URL, { createObjectURL, revokeObjectURL });
    const api = new ApiClient("tok", async () => new Response("{}"));
    const save = vi.fn();
    await downloadFile(api, "/projects/p/export.ipynb", "p.ipynb", save);
    expect(createObjectURL).toHaveBeenCalledWith(expect.any(Blob));
    expect(save).toHaveBeenCalledWith("blob:1", "p.ipynb");
    expect(revokeObjectURL).not.toHaveBeenCalled();
    vi.runAllTimers();
    expect(revokeObjectURL).toHaveBeenCalledWith("blob:1");
  });
});
