/**
 * The workspace wires the frame together: roster, header and chat in one
 * grid, the brain picker handed from the composer to the header, and the
 * keyboard shortcuts live only while the section is on screen.
 */
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import type { SocietyAgent } from "../data";
import { useHeaderModelSlot } from "./headerModelSlot";
import { AgentCardOverlay } from "./AgentCardOverlay";

vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useLocaleChunk: () => true, useUiLanguage: () => "en" }));
vi.mock("./OptionsRail", () => ({ OptionsRail: ({ agent }: { agent: SocietyAgent }) => <aside aria-label="Details">{agent.name}</aside> }));
vi.mock("../chat/AgentModelPicker", () => ({ AgentModelPicker: () => <button type="button">brain</button> }));
const renders = vi.hoisted(() => ({ chat: 0 }));
vi.mock("../chat/AgentChatPanel", async () => {
  const { create } = await import("zustand");
  const store = create(() => ({ busy: false, activeSessionId: null, sessions: [], loadSessions: async () => undefined }));
  function ChatProbe({ agent }: { agent: SocietyAgent }) {
    renders.chat += 1;
    const slot = useHeaderModelSlot();
    return <div data-testid="chat-probe" data-header-picker={slot ? "yes" : "no"}>{agent.name}</div>;
  }
  return { AgentChatPanel: ChatProbe, useSocietyChatStore: store };
});

function agent(over: Partial<SocietyAgent> & Pick<SocietyAgent, "agentId" | "name">): SocietyAgent {
  return {
    title: "Title", description: "", tier: "specialist", provider: "", providerLabel: "", model: "", effort: "",
    figure: null, palette: { primary: "#000", secondary: "#111", accent: "#222" }, grantMode: "all", toolGrants: [],
    focus: [], denies: [], approvalRules: { requireApproval: [], alwaysAllow: [] }, permissionCeiling: "ask",
    dailyBudgetUsd: 0, checkpoint: "idle", state: "idle", lifecycle: "active", createdMs: 0, maxConcurrentRuns: 1,
    workspaceDir: "", wikiNamespace: "", chatSessionId: null, routines: [],
    stats: { runs: 0, totalCostUsd: 0, spentTodayUsd: 0, lastActiveMs: null },
    ...over,
  };
}

afterEach(() => {
  cleanup();
  localStorage.clear();
  vi.unstubAllGlobals();
});

function mount(props: Partial<Parameters<typeof AgentCardOverlay>[0]> = {}) {
  vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ providers: [] }) })));
  const roster = [agent({ agentId: "lead", name: "Lead", tier: "lead" }), agent({ agentId: "a", name: "Alpha" }), agent({ agentId: "b", name: "Beta" })];
  const onSelectAgent = vi.fn();
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>
    <AgentCardOverlay embedded agent={roster[1]} roster={roster} onSelectAgent={onSelectAgent} onClose={() => undefined} {...props} />
  </QueryClientProvider>);
  return { onSelectAgent };
}

describe("AgentCardOverlay", () => {
  it("renders roster, header, chat and details once, without a render storm", () => {
    renders.chat = 0;
    mount();
    expect(screen.getByTestId("society-roster-rail")).toBeTruthy();
    expect(screen.getByTestId("agent-header-name").textContent).toBe("Alpha");
    expect(screen.getByRole("complementary", { name: "Details" }).textContent).toBe("Alpha");
    expect(renders.chat).toBeLessThan(5);
  });

  it("moves the brain picker into the header for a specialist", () => {
    mount();
    expect(screen.getByTestId("chat-probe").dataset.headerPicker).toBe("yes");
    expect(screen.getByRole("button", { name: "brain" })).toBeTruthy();
  });

  it("leaves the lead's chat its own model controls", () => {
    const roster = [agent({ agentId: "lead", name: "Lead", tier: "lead" })];
    vi.stubGlobal("fetch", vi.fn(async () => ({ ok: true, status: 200, json: async () => ({}) })));
    const client = new QueryClient();
    render(<QueryClientProvider client={client}><AgentCardOverlay embedded agent={roster[0]} roster={roster} onClose={() => undefined} /></QueryClientProvider>);
    expect(screen.getByTestId("chat-probe").dataset.headerPicker).toBe("no");
  });

  it("steps to the next agent with Alt + Arrow Down only while active", () => {
    const { onSelectAgent } = mount();
    fireEvent.keyDown(window, { key: "ArrowDown", altKey: true });
    expect(onSelectAgent).toHaveBeenCalledWith("b");
    cleanup();
    const inactive = mount({ active: false });
    fireEvent.keyDown(window, { key: "ArrowDown", altKey: true });
    expect(inactive.onSelectAgent).not.toHaveBeenCalled();
  });
});
