import type { ApiClient } from "./client";

/** Fetch with the bearer token and hand the bytes to the browser as a download. */
export async function downloadFile(
  api: ApiClient,
  path: string,
  filename: string,
  save: (url: string, filename: string) => void = saveViaAnchor,
): Promise<void> {
  const blob = await api.fetchBlob(path);
  const url = URL.createObjectURL(blob);
  save(url, filename);
  // Revoking right after click() can cancel the download; the browser needs a moment.
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

function saveViaAnchor(url: string, filename: string): void {
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
}
