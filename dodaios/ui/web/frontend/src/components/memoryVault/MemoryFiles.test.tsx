import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";

import { MemoryFiles } from "./MemoryFiles";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("loads no remote picture a memory file names", async () => {
  const remote = "https://example.test/m.png?d=c2VjcmV0";
  const files = [{
    name: "MEMORY.md", kind: "index", bytes: 64, lines: 4,
    content: `# Memory\n\n![pin](${remote})\n\n![own](/api/media/own.png)`,
  }];
  const fetchMock = vi.fn(async () => new Response(JSON.stringify({ files }), { headers: { "Content-Type": "application/json" } }));
  vi.stubGlobal("fetch", fetchMock);
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  render(<QueryClientProvider client={client}><MemoryFiles /></QueryClientProvider>);

  fireEvent.click(await screen.findByTestId("vault-file"));
  const preview = screen.getByTestId("vault-quicklook");
  expect(within(preview).getByRole("heading", { name: "Memory" })).toBeTruthy();
  // What the app serves is drawn; the remote address is a link, as in a chat message.
  expect(Array.from(preview.querySelectorAll("img")).map((image) => image.getAttribute("src"))).toEqual(["/api/media/own.png"]);
  expect(within(preview).getByRole("link", { name: /pin/ }).getAttribute("href")).toBe(remote);
  // Only the file list was asked for.
  expect(fetchMock).toHaveBeenCalledTimes(1);
});
