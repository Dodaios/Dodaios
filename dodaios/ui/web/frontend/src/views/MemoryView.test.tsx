import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { loadLocaleChunk, setUiLanguage } from "@/i18n";
import { MemoryView } from "@/views/MemoryView";

/**
 * The Memory section: a library sidebar, the memories list with an
 * inspector, the memory as files with a preview, and a drawing of what
 * reaches the model. Writes go to /api/memory/vault.
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
  memory("m2", "relationship", "Lea is my sister.", {
    pinned: true,
    origin: "inferred",
    source: { evidence: "my sister Lea is visiting" },
  }),
  memory("m3", "episode", "We hiked on Sunday."),
];

const OVERVIEW = {
  path: "vault.db",
  stats: { current: 3, by_kind: { profile: 1, relationship: 1, episode: 1 }, all_versions: 4, forgotten: 0, entities: 0 },
  kinds: ["profile", "relationship", "episode"],
  prompt_block: "## What you know\nUse it.\nPinned:\n- Lea is my sister.",
  in_mind_ids: ["m1", "m2"],
  budget_chars: 2400,
  used_chars: 600,
  imported: true,
};

const FILES = {
  files: [
    { name: "MEMORY.md", kind: "index", bytes: 120, lines: 6, content: "# My memory\n" },
    { name: "profile.md", kind: "profile", bytes: 90, lines: 8, content: "---\nkind: profile\n---\n\n# About me\n\n- I live in Berlin. <!-- m1 -->\n" },
  ],
};

let calls: Array<{ url: string; init?: RequestInit }> = [];

function stubFetch() {
  calls = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = url.endsWith("/api/memory/vault")
      ? OVERVIEW
      : url.includes("/files")
        ? FILES
        : url.includes("/history")
          ? {
              versions: [
                memory("m0", "profile", "I live in Hamburg.", { current: false, valid_to: NOW }),
                memory("m1", "profile", "I live in Berlin."),
              ],
            }
          : url.includes("/items") && (!init || !init.method)
            ? { items: ITEMS, count: ITEMS.length, total: 7, has_more: true }
            : { action: "added", item: ITEMS[0], ok: true, forgotten: 1, undo_token: "tok1", restored: 1 };
    return { ok: true, status: 200, json: async () => body } as Response;
  });
  (globalThis as unknown as { fetch: typeof fetch }).fetch = fetchMock as unknown as typeof fetch;
}

/** Opens a branded select and picks an option by its label. */
function choose(testId: string, label: string) {
  fireEvent.click(screen.getByTestId(testId));
  fireEvent.click(within(screen.getByTestId(`${testId}-panel`)).getByRole("option", { name: label }));
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
  it("groups memories by kind and inspects one with its timeline", async () => {
    stubFetch();
    renderView();
    expect(await screen.findByText("Lea is my sister.")).toBeTruthy();
    expect(screen.getAllByTestId("vault-row")).toHaveLength(3);
    expect(screen.getAllByTestId("vault-group")).toHaveLength(3);
    expect(screen.getByTestId("vault-summary").textContent).toContain("3");
    expect(screen.getByText("Pick a memory")).toBeTruthy();
    fireEvent.click(screen.getByText("I live in Berlin."));
    const [inspector] = await screen.findAllByTestId("vault-inspector");
    expect(within(inspector).getByText("Always in mind")).toBeTruthy();
    const versions = await within(inspector).findByTestId("vault-versions");
    expect(within(versions).getByText("I live in Hamburg.")).toBeTruthy();
  });

  it("filters to what is always in mind and shows the user's own words", async () => {
    stubFetch();
    renderView();
    await screen.findByText("We hiked on Sunday.");
    fireEvent.click(screen.getAllByRole("button", { name: /Always in mind/ })[0]);
    await waitFor(() => expect(screen.getAllByTestId("vault-row")).toHaveLength(2));
    fireEvent.click(screen.getAllByTestId("vault-row")[1]);
    expect((await screen.findAllByText("my sister Lea is visiting")).length).toBeGreaterThan(0);
  });

  it("adds a memory from the new-memory sheet", async () => {
    stubFetch();
    renderView();
    await screen.findByText("Lea is my sister.");
    fireEvent.click(screen.getByTestId("vault-add"));
    const sheet = await screen.findByTestId("vault-new-sheet");
    fireEvent.change(within(sheet).getByRole("textbox"), { target: { value: "I like jazz." } });
    fireEvent.click(within(sheet).getByRole("radio", { name: "Preferences" }));
    fireEvent.click(within(sheet).getByRole("button", { name: "Remember" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "POST" && c.url.endsWith("/items"))).toBe(true));
    const post = calls.find((c) => c.init?.method === "POST" && c.url.endsWith("/items"));
    expect(JSON.parse(String(post?.init?.body))).toMatchObject({ text: "I like jazz.", kind: "preference" });
  });

  it("shows the memory as files with a readable preview", async () => {
    stubFetch();
    renderView();
    fireEvent.click(await screen.findByRole("button", { name: "As files" }));
    const files = await screen.findAllByTestId("vault-file");
    fireEvent.click(files[1]);
    const preview = await screen.findByTestId("vault-quicklook");
    expect(within(preview).getByText("I live in Berlin.")).toBeTruthy();
    expect(preview.textContent).not.toContain("kind: profile");
  });

  it("draws how much of the always-on space is used", async () => {
    stubFetch();
    renderView();
    fireEvent.click(await screen.findByTestId("vault-mode-how"));
    const meter = await screen.findByRole("meter");
    expect(meter.getAttribute("aria-valuenow")).toBe("600");
  });

  it("asks before forgetting and then deletes", async () => {
    stubFetch();
    renderView();
    fireEvent.click(await screen.findByText("We hiked on Sunday."));
    const [inspector] = await screen.findAllByTestId("vault-inspector");
    fireEvent.click(within(inspector).getByRole("button", { name: "Forget" }));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Forget" }));
    await waitFor(() => expect(calls.some((c) => c.init?.method === "DELETE")).toBe(true));
  });
  it("filters by origin and date on the server and pages with Show more", async () => {
    stubFetch();
    renderView();
    await screen.findByText("Lea is my sister.");
    choose("vault-filter-origin", "Imported");
    await waitFor(() => expect(calls.some((c) => c.url.includes("origin=imported"))).toBe(true));
    choose("vault-filter-period", "Last 7 days");
    await waitFor(() => expect(calls.some((c) => /since=\d{4}-\d{2}-\d{2}/.test(c.url))).toBe(true));
    fireEvent.click(await screen.findByTestId("vault-more"));
    await waitFor(() => expect(calls.some((c) => c.url.includes("limit=400"))).toBe(true));
  });

  it("lists newest first as one flat list", async () => {
    stubFetch();
    renderView();
    await screen.findByText("Lea is my sister.");
    choose("vault-sort", "Newest first");
    await waitFor(() => expect(calls.some((c) => c.url.includes("sort=newest"))).toBe(true));
    await waitFor(() => expect(screen.getAllByTestId("vault-group")).toHaveLength(1));
    expect(screen.getAllByTestId("vault-row")).toHaveLength(3);
  });

  it("forgets a selection after asking and can undo it", async () => {
    stubFetch();
    renderView();
    await screen.findByText("Lea is my sister.");
    fireEvent.click(screen.getByTestId("vault-select"));
    fireEvent.click(screen.getByText("Lea is my sister."));
    fireEvent.click(screen.getByText("We hiked on Sunday."));
    expect(screen.getByTestId("vault-picked-count").textContent).toContain("2");
    fireEvent.click(screen.getByTestId("vault-forget-selected"));
    const dialog = await screen.findByRole("dialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "Forget" }));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/forget") && c.init?.method === "POST")).toBe(true));
    const post = calls.find((c) => c.url.endsWith("/forget"));
    expect(JSON.parse(String(post?.init?.body)).ids.sort()).toEqual(["m2", "m3"]);
    fireEvent.click(await screen.findByTestId("vault-undo"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/undo/tok1"))).toBe(true));
  });

  it("shows the profile block the lead receives, read-only, and the provider-switch note", async () => {
    stubFetch();
    renderView();
    fireEvent.click(await screen.findByTestId("vault-mode-how"));
    const block = await screen.findByTestId("vault-lead-knows-block");
    expect(block.textContent).toContain("Lea is my sister.");
    expect(screen.getByTestId("vault-portable-switch").textContent).toMatch(/switch the model/i);
  });
});
