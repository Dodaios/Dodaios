import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { roster, writeDraft } = vi.hoisted(() => ({
  roster: { data: undefined as unknown },
  writeDraft: vi.fn(),
}));

vi.mock("@/i18n", () => ({
  useT: () => (key: string) => ({
    "design.greeting.due": "Prepare: {text}",
    "design.greeting.agent_working": "What is {agent} doing?",
    "design.greeting.agent_waiting": "What does {agent} need?",
  }[key] ?? key),
  fill: (text: string, values: Record<string, string>) =>
    text.replace(/\{(\w+)\}/g, (_, name: string) => values[name] ?? `{${name}}`),
}));
vi.mock("@/components/society/data", () => ({ useSocietyRoster: () => roster }));
vi.mock("@/components/agentchat/composerDrafts", () => ({ writeComposerDraft: writeDraft }));
vi.mock("@/store/agentChat", () => ({
  useAgentChatStore: { getState: () => ({ activeSessionId: "lead-1" }) },
}));

import GreetingSuggestions from "./GreetingSuggestions";

function answer(items: unknown[]) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, json: async () => ({ items }) }) as Response));
}

beforeEach(() => {
  roster.data = undefined;
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

  it("offers what falls due and an agent at work", async () => {
    answer([{ id: "m1", text: "Dentist", due_at: "2026-11-11T09:00" }]);
    roster.data = {
      sample: false,
      agents: [
        { agentId: "a1", name: "Scout", state: "working", tier: "worker", lifecycle: "active" },
        { agentId: "lead", name: "Lead", state: "working", tier: "lead", lifecycle: "active" },
        { agentId: "old", name: "Old", state: "waiting", tier: "worker", lifecycle: "archived" },
      ],
    };
    render(<GreetingSuggestions />);
    await waitFor(() => expect(screen.getAllByTestId("greeting-suggestion")).toHaveLength(2));
    const chips = screen.getAllByTestId("greeting-suggestion");
    expect(chips.map((chip) => chip.textContent)).toEqual(["Prepare: Dentist", "What is Scout doing?"]);
  });

  it("ignores the sample roster a fresh install shows", async () => {
    answer([]);
    roster.data = { sample: true, agents: [{ agentId: "s", name: "Sample", state: "working", tier: "worker", lifecycle: "active" }] };
    const { container } = render(<GreetingSuggestions />);
    await waitFor(() => expect(fetch).toHaveBeenCalled());
    expect(container.innerHTML).toBe("");
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
