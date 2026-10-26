import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import { useEventStore } from "@/store/events";
import { openAgent, useAgentNavigation } from "./agentNavigation";
import { LAST_AGENT_STORAGE_KEY } from "./lastAgent";
import { SocietyView } from "./SocietyView";

const reveal = vi.hoisted(() => ({ calls: [] as unknown[] }));
vi.mock("./agentNavigation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./agentNavigation")>();
  return { ...actual, revealCard: vi.fn(async (target: unknown) => { reveal.calls.push(target); return true; }) };
});
vi.mock("@/hooks/useAppInstance", () => ({ useAppInstance: () => ({ name: "default", isDev: false }) }));
vi.mock("@/lib/mapFullscreen", () => ({ setMapFullscreen: vi.fn(async () => undefined) }));
vi.mock("@tanstack/react-query", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@tanstack/react-query")>()),
  useQueryClient: () => ({ invalidateQueries: async () => undefined }),
}));
vi.mock("@/i18n", () => ({ useT: () => (key: string) => key, useLocaleChunk: () => true, fill: (t: string) => t, translate: (k: string) => k }));
vi.mock("@/components/society/chat/useModelMenuData", () => ({ useModelMenuData: () => undefined }));
vi.mock("@/lib/societyChatGroups", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/societyChatGroups")>()),
  useSocietyChatGroups: () => ({ data: [], isSuccess: true, isError: false, failureCount: 0 }),
}));
vi.mock("@/components/society/data", () => ({ useQuickCreateAgent: () => vi.fn(), useSocietyRoster: () => ({ data: { sample: false, agents: [
  { agentId: "jarvis", name: "Lead", tier: "lead", state: "idle" },
  { agentId: "scout", name: "Scout", tier: "specialist", state: "waiting" },
] }, isLoading: false }) }));
vi.mock("@/views/DodaiosAgentsView", () => ({ DodaiosAgentsView: () => <div data-testid="map" /> }));
vi.mock("@/components/society/card/AgentCardOverlay", () => ({ AgentCardOverlay: ({ agent }: any) => <div data-testid="workspace">{agent.name}</div> }));
vi.mock("@/components/society/roster/RosterRail", () => ({ RosterRail: () => <div data-testid="roster" /> }));
vi.mock("@/components/society/attention/AttentionBell", () => ({ AttentionBell: () => <button data-testid="attention-bell" /> }));

beforeEach(() => {
  reveal.calls = [];
  localStorage.removeItem(LAST_AGENT_STORAGE_KEY);
  useAgentNavigation.setState({ request: null, onScreen: null });
  useEventStore.setState({ activeSection: "agents" });
});
afterEach(() => cleanup());

it("puts the bell in the caption beside the mode switch", () => {
  render(<SocietyView />);
  expect(screen.getByTestId("mode-switch").contains(screen.getByTestId("attention-bell"))).toBe(true);
});

it("opens the requested agent and reveals the card", async () => {
  render(<SocietyView />);
  expect(screen.getByTestId("workspace").textContent).toBe("Lead");
  act(() => openAgent("scout", { sessionId: "society:scout", cardRef: "q1", kind: "question" }));
  await waitFor(() => expect(screen.getByTestId("workspace").textContent).toBe("Scout"));
  expect(reveal.calls).toEqual([{ cardRef: "q1", kind: "question" }]);
  expect(useAgentNavigation.getState().request).toBeNull();
  expect(useAgentNavigation.getState().onScreen).toEqual({ agentId: "scout" });
});

it("drops a request for an agent that is not on the roster", async () => {
  render(<SocietyView />);
  act(() => openAgent("gone", { cardRef: "x", kind: "approval" }));
  await waitFor(() => expect(useAgentNavigation.getState().request).toBeNull());
  expect(screen.getByTestId("workspace").textContent).toBe("Lead");
  expect(reveal.calls).toEqual([]);
});

it("forgets the agent on screen when the view goes away", () => {
  const view = render(<SocietyView />);
  expect(useAgentNavigation.getState().onScreen).toEqual({ agentId: "jarvis" });
  view.unmount();
  expect(useAgentNavigation.getState().onScreen).toBeNull();
});
