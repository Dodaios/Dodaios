import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AgentMemoryFiles, LearnedInstructions } from "./AgentKnowledge";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useUiLanguage: () => "en" }));
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });
const json = (data: unknown, status = 200) => new Response(JSON.stringify(data), { status });

it("keeps memory readable while an older backend waits for the next app start", async () => {
  const fetcher = vi.fn(async (url: string) => {
    if (url.endsWith("/knowledge")) return json({}, 404);
    if (url === "/api/wiki/tree") return json({ ok: true, folders: [
      { name: "society/scout", files: [{ slug: "memory", mtime: 1, size: 50 }] },
      { name: "society/scout-other", files: [{ slug: "private", mtime: 1, size: 50 }] },
    ] });
    return json({ path: "society/scout/memory.md", content: "Existing memory", updated_ms: 1 });
  });
  vi.stubGlobal("fetch", fetcher);
  render(<QueryClientProvider client={new QueryClient()}><AgentMemoryFiles agentId="scout" sample={false} /></QueryClientProvider>);
  await screen.findByText("Existing memory");
  expect(screen.getByText("society.profile_card.runtime_pending")).toBeTruthy();
  expect(screen.queryByText("private.md")).toBeNull();
  expect(fetcher).toHaveBeenCalledWith("/api/society/memory/file?path=society%2Fscout%2Fmemory.md", expect.anything());
});

it("refreshes revised working instructions without presenting a pending review as completed", async () => {
  let corrected = false;
  vi.stubGlobal("fetch", vi.fn(async () => json({ files: [], learned_instructions: [corrected ? "Use dated sources." : "Check sources."], reviews: { pending: 2, done: 4 }, last_review: { state: "pending", updated_ms: 1000 } })));
  render(<QueryClientProvider client={new QueryClient()}><LearnedInstructions agentId="scout" sample={false} /></QueryClientProvider>);
  await screen.findByText("Check sources.");
  expect(screen.getByRole("status").textContent).toContain("review_pending");
  corrected = true;
  fireEvent.click(screen.getByRole("button", { name: "society.profile_card.refresh" }));
  await screen.findByText("Use dated sources.");
  expect(screen.queryByText("Check sources.")).toBeNull();
});

it("shows separate user and experience notebooks and loads each agent-qualified file", async () => {
  const fetcher = vi.fn(async (url: string) => url.endsWith("/knowledge") ? json({
    files: [
      { path: "memory/USER.md", name: "USER.md", kind: "memory", updated_ms: 1, size: 50 },
      { path: "memory/MEMORY.md", name: "MEMORY.md", kind: "memory", updated_ms: 2, size: 50 },
    ], learned_instructions: [], reviews: { pending: 0, done: 0 }, last_review: null,
  }) : json({ content: url.includes("USER.md") ? "Prefers concise replies." : "The project uses PostgreSQL." }));
  vi.stubGlobal("fetch", fetcher);
  render(<QueryClientProvider client={new QueryClient()}><AgentMemoryFiles agentId="scout" sample={false} /></QueryClientProvider>);
  await screen.findByText("Prefers concise replies.");
  expect(screen.getByRole("button", { name: "USER.md society.profile_card.user_book" })).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "MEMORY.md society.profile_card.memory_book" }));
  await screen.findByText("The project uses PostgreSQL.");
  expect(screen.queryByText("Prefers concise replies.")).toBeNull();
  expect(fetcher).toHaveBeenCalledWith("/api/society/agents/scout/knowledge/file?path=memory%2FMEMORY.md", expect.anything());
});

it("says why the last review is waiting and when one was dropped", async () => {
  let record: Record<string, unknown> = { state: "pending", updated_ms: 1000, reason_code: "api_key_seat", provider: "gemini", reason: "server sentence" };
  let counts = { pending: 1, done: 0 };
  vi.stubGlobal("fetch", vi.fn(async () => json({ files: [], learned_instructions: [], reviews: counts, last_review: record })));
  render(<QueryClientProvider client={new QueryClient()}><LearnedInstructions agentId="scout" sample={false} /></QueryClientProvider>);
  expect((await screen.findByTestId("review-wait-reason")).textContent).toBe("society.profile_card.review_reason_api_key_seat");
  record = { state: "dropped", updated_ms: 2000, attempts: 4, reason_code: "seat_failed" };
  counts = { pending: 0, done: 0 };
  fireEvent.click(screen.getByRole("button", { name: "society.profile_card.refresh" }));
  await screen.findByText("society.profile_card.review_reason_seat_failed");
  expect(screen.getByRole("status").textContent).toBe("society.profile_card.review_dropped");
});

it("falls back to the server sentence for a reason without a known code", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ files: [], learned_instructions: [], reviews: { pending: 1, done: 0 }, last_review: { state: "pending", updated_ms: 1, reason: "a subscription is connected" } })));
  render(<QueryClientProvider client={new QueryClient()}><LearnedInstructions agentId="scout" sample={false} /></QueryClientProvider>);
  expect((await screen.findByTestId("review-wait-reason")).textContent).toBe("a subscription is connected");
});

it("shows no reason once a review is done", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({ files: [], learned_instructions: ["Check sources."], reviews: { pending: 0, done: 1 }, last_review: { state: "done", updated_ms: 1 } })));
  render(<QueryClientProvider client={new QueryClient()}><LearnedInstructions agentId="scout" sample={false} /></QueryClientProvider>);
  await screen.findByText("Check sources.");
  expect(screen.queryByTestId("review-wait-reason")).toBeNull();
});
