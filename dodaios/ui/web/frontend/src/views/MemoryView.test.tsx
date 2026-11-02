import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { loadLocaleChunk, setUiLanguage } from "@/i18n";
import { MemoryView } from "@/views/MemoryView";

/**
 * The Memory section shows the personal memory vault: one row per memory,
 * grouped by kind, the exact block the assistant carries into every
 * conversation, and the export links. Writes go to /api/memory/vault.
 */

const NOW = "2026-11-02T10:00:00+00:00";

function memory(id: string, kind: string, text: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    kind,
    text,
    entities: [],
    scope: "global",
    origin: "user",
    recorded_at: NOW,
    valid_from: NOW,
    valid_to: null,
    expired_at: null,
    supersedes_id: null,
    source: {},
    confidence: 1,
    sensitivity: "normal",
    pinned: false,
    use_count: 0,
    last_used_at: null,
    current: true,
    ...extra,
  };
}

const ITEMS = [
  memory("m1", "profile", "I live in Berlin.", { supersedes_id: "m0" }),
  memory("m2", "relationship", "Lea is my sister.", { pinned: true, origin: "inferred" }),
];

const OVERVIEW = {
  path: "vault.db",
  stats: { current: 2, by_kind: { profile: 1, relationship: 1 }, all_versions: 3, forgotten: 0, entities: 0 },
  kinds: ["profile", "relationship"],
  prompt_block: "## What you know\nUse it.\nPinned:\n- Lea is my sister.",
  imported: true,
};

let calls: Array<{ url: string; init?: RequestInit }> = [];

function stubFetch() {
  calls = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = url.endsWith("/api/memory/vault")
      ? OVERVIEW
      : url.includes("/activity")
        ? { entries: [{ seq: 1, at: NOW, action: "add", memory_id: "m1", text: "I live in Berlin." }] }
        : url.includes("/history")
          ? {
              versions: [
                memory("m0", "profile", "I live in Hamburg.", { current: false }),
                memory("m1", "profile", "I live in Berlin."),
              ],
            }
          : url.includes("/items") && (!init || !init.method)
            ? { items: ITEMS, count: ITEMS.length }
            : { action: "added", item: ITEMS[0], ok: true, forgotten: 1 };
    return { ok: true, status: 200, json: async () => body } as Response;
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
}

function renderView() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <MemoryView />
    </QueryClientProvider>,
  );
}

beforeAll(async () => {
  setUiLanguage("en");
  await loadLocaleChunk("memory");
});

afterEach(cleanup);

describe("MemoryView", () => {
  it("groups memories by kind and shows what is always in mind", async () => {
    stubFetch();
    renderView();
    const profile = await screen.findByTestId("vault-group-profile");
    expect(within(profile).getByText("I live in Berlin.")).toBeTruthy();
    expect(within(screen.getByTestId("vault-group-relationship")).getByText("Lea is my sister.")).toBeTruthy();
    expect(screen.getByTestId("vault-prompt-block").textContent).toContain("Lea is my sister.");
    expect(screen.getByTestId("vault-export-bundle").getAttribute("href")).toBe(
      "/api/memory/vault/export?format=bundle",
    );
  });

  it("saves a new memory from the composer", async () => {
    stubFetch();
    renderView();
    const composer = await screen.findByTestId("vault-composer");
    fireEvent.change(within(composer).getByRole("textbox"), { target: { value: "I like jazz." } });
    fireEvent.submit(composer);
    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST" && c.url.endsWith("/items"))).toBe(true));
    const post = calls.find((c) => c.init?.method === "POST" && c.url.endsWith("/items"));
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ text: "I like jazz.", kind: "" });
  });

  it("shows earlier versions of a changed memory", async () => {
    stubFetch();
    renderView();
    await screen.findByText("I live in Berlin.");
    fireEvent.click(screen.getByRole("button", { name: "Earlier versions" }));
    const versions = await screen.findByTestId("vault-versions");
    expect(await within(versions).findByText("I live in Hamburg.")).toBeTruthy();
  });

  it("asks before forgetting and then deletes", async () => {
    stubFetch();
    renderView();
    await screen.findByText("I live in Berlin.");
    fireEvent.click(screen.getAllByRole("button", { name: "Forget" })[0]);
    expect(await screen.findByText("Forget this for good?")).toBeTruthy();
    const dialog = screen.getByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Forget" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "DELETE")).toBe(true));
  });
});
