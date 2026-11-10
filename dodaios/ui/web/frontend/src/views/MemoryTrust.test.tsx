import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { loadLocaleChunk, setUiLanguage } from "@/i18n";
import { MemoryView } from "@/views/MemoryView";
import { useEventStore } from "@/store/events";

/**
 * Memory trust on the Memory page: where a memory came from, work / private,
 * one export of everything, and importing another assistant's memories.
 */

const NOW = "2026-11-02T10:00:00+00:00";

function memory(id: string, text: string, extra: Record<string, unknown> = {}) {
  return {
    id,
    kind: "profile",
    text,
    entities: [],
    scope: "global",
    origin: "inferred",
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
  memory("m1", "I live in Berlin.", {
    source: { via: "review", session_id: "lead", turn_id: "t9", message_seq: 41, evidence: "I live in Berlin" },
  }),
  memory("m2", "I lead the design team.", { scope: "work" }),
  memory("m3", "My sister is called Lea.", { scope: "private", origin: "imported", source: { via: "import", file: "m.txt" } }),
];

const OVERVIEW = {
  path: "vault.db",
  stats: { current: 3, by_kind: { profile: 3 }, all_versions: 3, forgotten: 0, entities: 0 },
  kinds: ["profile"],
  prompt_block: "",
  in_mind_ids: [],
  budget_chars: 2400,
  used_chars: 0,
  imported: true,
};

const READING = {
  candidates: [
    { text: "Has a dog called Bruno.", kind: "relationship", exists: false, extracted: false },
    { text: "I live in Berlin.", kind: "profile", exists: true, extracted: false },
  ],
  shape: "list",
  messages: 0,
  model_missing: false,
};

let calls: Array<{ url: string; init?: RequestInit }> = [];

function stubFetch() {
  calls = [];
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    calls.push({ url, init });
    const body = url.endsWith("/api/memory/vault")
      ? OVERVIEW
      : url.includes("/history")
        ? { versions: [] }
        : url.includes("/import/read")
          ? READING
          : url.includes("/import/save")
            ? { added: 1, existing: 0, refused: 0, failed: 0 }
            : url.includes("/items") && (!init || !init.method)
              ? { items: ITEMS, count: ITEMS.length }
              : { ok: true, scope: "work" };
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

describe("Memory trust", () => {
  it("filters by work and private and marks the rows", async () => {
    stubFetch();
    renderView();
    expect(await screen.findByText("I live in Berlin.")).toBeTruthy();
    expect(screen.getAllByTestId("vault-row-scope").map((el) => el.textContent)).toEqual(["Work", "Private"]);
    fireEvent.click(screen.getByTestId("vault-space-work"));
    expect(screen.getAllByTestId("vault-row")).toHaveLength(1);
    expect(screen.getByText("I lead the design team.")).toBeTruthy();
    fireEvent.click(screen.getByTestId("vault-space-private"));
    expect(screen.getByText("My sister is called Lea.")).toBeTruthy();
    fireEvent.click(screen.getByTestId("vault-space-all"));
    expect(screen.getAllByTestId("vault-row")).toHaveLength(3);
  });

  it("marks a memory work with one control", async () => {
    stubFetch();
    renderView();
    fireEvent.click(await screen.findByText("I live in Berlin."));
    const [inspector] = await screen.findAllByTestId("vault-inspector");
    expect(within(inspector).getByTestId("vault-scope-global").getAttribute("aria-checked")).toBe("true");
    fireEvent.click(within(inspector).getByTestId("vault-scope-work"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/items/m1/scope") && c.init?.method === "PUT")).toBe(true));
    const put = calls.find((c) => c.url.endsWith("/items/m1/scope"));
    expect(JSON.parse(String(put?.init?.body))).toEqual({ scope: "work" });
  });

  it("links a learned memory to its message and an imported one to nothing", async () => {
    stubFetch();
    useEventStore.setState({ activeSection: "memory" });
    renderView();
    fireEvent.click(await screen.findByText("I live in Berlin."));
    const [inspector] = await screen.findAllByTestId("vault-inspector");
    fireEvent.click(within(inspector).getByTestId("vault-source-link"));
    expect(useEventStore.getState().activeSection).toBe("chats");

    cleanup();
    renderView();
    fireEvent.click(await screen.findByText("My sister is called Lea."));
    const [imported] = await screen.findAllByTestId("vault-inspector");
    expect(within(imported).queryByTestId("vault-source-link")).toBeNull();
    expect(within(imported).getByText("m.txt")).toBeTruthy();
  });

  it("exports everything with one link", async () => {
    stubFetch();
    renderView();
    const link = await screen.findByTestId("vault-export-all");
    expect(link.getAttribute("href")).toBe("/api/memory/vault/export?format=all");
    expect(link.textContent).toContain("Export all memories");
  });

  it("imports another assistant's memories after a review", async () => {
    stubFetch();
    renderView();
    fireEvent.click(await screen.findByTestId("vault-import-foreign"));
    const sheet = await screen.findByTestId("vault-foreign-import");
    const input = within(sheet).getByTestId("vault-foreign-file") as HTMLInputElement;
    const file = new File(["- Has a dog called Bruno.\n- I live in Berlin.\n"], "memories.md", { type: "text/markdown" });
    Object.defineProperty(file, "text", { value: async () => "- Has a dog called Bruno.\n- I live in Berlin.\n" });
    fireEvent.change(input, { target: { files: [file] } });
    const rows = await within(sheet).findAllByTestId("vault-foreign-row");
    // A line already in memory is shown but not kept by default.
    expect(rows.map((row) => (row as HTMLInputElement).checked)).toEqual([true, false]);
    fireEvent.click(within(sheet).getByTestId("vault-foreign-save"));
    await waitFor(() => expect(calls.some((c) => c.url.endsWith("/import/save"))).toBe(true));
    const save = calls.find((c) => c.url.endsWith("/import/save"));
    expect(JSON.parse(String(save?.init?.body))).toEqual({
      name: "memories.md",
      items: [{ text: "Has a dog called Bruno.", kind: "relationship", extracted: false }],
    });
    const read = calls.find((c) => c.url.endsWith("/import/read"));
    expect(JSON.parse(String(read?.init?.body)).name).toBe("memories.md");
    expect(await screen.findByRole("status")).toBeTruthy();
  });
});
