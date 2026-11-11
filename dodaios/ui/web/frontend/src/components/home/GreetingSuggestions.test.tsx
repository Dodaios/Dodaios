import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { writeDraft } = vi.hoisted(() => ({ writeDraft: vi.fn() }));

vi.mock("@/i18n", () => ({
  useT: () => (key: string) => ({
    "design.greeting.due": "Prepare: {text}",
  }[key] ?? key),
  fill: (text: string, values: Record<string, string>) =>
    text.replace(/\{(\w+)\}/g, (_, name: string) => values[name] ?? `{${name}}`),
}));
vi.mock("@/components/agentchat/composerDrafts", () => ({ writeComposerDraft: writeDraft }));
vi.mock("@/store/agentChat", () => ({
  useAgentChatStore: { getState: () => ({ activeSessionId: "lead-1" }) },
}));

import GreetingSuggestions from "./GreetingSuggestions";

function answer(items: unknown[]) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ items }) }) as Response));
}

beforeEach(() => {
  writeDraft.mockReset();
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("GreetingSuggestions", () => {
  it("renders nothing on a quiet day", async () => {
    answer([]);
    const { container } = render(<GreetingSuggestions />);
    await waitFor(() => expect(fetch).toHaveBeenCalledWith("/api/memory/vault/upcoming?days=3"));
    expect(container.innerHTML).toBe("");
  });

  it("offers what falls due", async () => {
    answer([{ id: "m1", text: "Dentist", due_at: "2026-11-11T09:00" }]);
    render(<GreetingSuggestions />);
    await waitFor(() => expect(screen.getAllByTestId("greeting-suggestion")).toHaveLength(1));
    const chips = screen.getAllByTestId("greeting-suggestion");
    expect(chips.map((chip) => chip.textContent)).toEqual(["Prepare: Dentist"]);
  });

  it("puts the sentence into the composer and sends nothing", async () => {
    answer([{ id: "m1", text: "Dentist", due_at: "2026-11-11" }]);
    render(<GreetingSuggestions />);
    fireEvent.click(await screen.findByTestId("greeting-suggestion"));
    expect(writeDraft).toHaveBeenCalledWith(expect.anything(), "lead-1", { text: "Prepare: Dentist", choices: [] });
    // Only the one read: a tap never posts a message.
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
