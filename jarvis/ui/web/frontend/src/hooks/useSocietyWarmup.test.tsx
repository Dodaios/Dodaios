import type { ReactNode } from "react";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { RosterData } from "@/components/society/data";
import type { SocietyChatGroup } from "@/lib/societyChatGroups";
import { useEventStore } from "@/store/events";
import { useSocietyWarmup } from "./useSocietyWarmup";

const ROSTER_URL = "/api/society/agents";
const TEAMS_URL = "/api/society/chat-groups";
const ROSTER_KEY = ["society", "roster"];
const TEAMS_KEY = ["society", "chat-groups"];

const TEAM: SocietyChatGroup = { group_id: "team", name: "Launch team", members: ["scout", "writer"], created_ms: 1, updated_ms: 1 };

function row(id: string) {
  return {
    agent_id: id, name: id, title: "", description: "", tier: "specialist", parent_agent_id: null, state: "active",
    avatar: null, checkpoint: "home", provider: "openai", model: "", effort: "", grant_mode: "all", grants: [],
    focus: [], denies: [], permission_ceiling: "ask", approval_rules: { require_approval: [], always_allow: [] },
    daily_budget_usd: 0, max_concurrent_runs: 1, session_id: `society:${id}`, created_ms: 0, updated_ms: 0,
    stats: { runs: 0, total_cost_usd: 0, last_active_ms: null },
  };
}

describe("useSocietyWarmup", () => {
  let client: QueryClient;
  let agents: string[];
  const calls: string[] = [];
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;
  const count = (url: string) => calls.filter((call) => call === url).length;

  beforeEach(() => {
    calls.length = 0;
    agents = ["scout", "writer"];
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.stubGlobal("fetch", async (url: string) => {
      calls.push(url);
      return new Response(JSON.stringify(url === ROSTER_URL ? { agents: agents.map(row) } : { groups: [TEAM] }));
    });
    useEventStore.setState({ activeSection: "chats", solo: false });
  });
  afterEach(() => {
    cleanup();
    client.clear();
    vi.unstubAllGlobals();
    vi.useRealTimers();
    useEventStore.setState({ activeSection: "chats", solo: false });
  });

  it("has the roster and the teams loaded before anyone opens the Agents section", async () => {
    renderHook(() => useSocietyWarmup(), { wrapper });

    await waitFor(() => expect(client.getQueryData(TEAMS_KEY)).toEqual([TEAM]));
    expect(client.getQueryData<RosterData>(ROSTER_KEY)?.agents.map((agent) => agent.agentId)).toEqual(["scout", "writer"]);
  });

  it("reads both again on the switch to the section, so a new agent is there on arrival", async () => {
    vi.useFakeTimers({ toFake: ["Date"] });
    renderHook(() => useSocietyWarmup(), { wrapper });
    await waitFor(() => expect(count(TEAMS_URL)).toBe(1));

    agents = ["scout", "writer", "newcomer"];
    vi.setSystemTime(Date.now() + 60_000);
    act(() => useEventStore.getState().setActiveSection("agents"));

    await waitFor(() => expect(client.getQueryData<RosterData>(ROSTER_KEY)?.agents).toHaveLength(3));
    await waitFor(() => expect(count(TEAMS_URL)).toBe(2));
  });

  it("asks nothing twice when the lists were read a moment ago", async () => {
    renderHook(() => useSocietyWarmup(), { wrapper });
    await waitFor(() => expect(count(TEAMS_URL)).toBe(1));

    act(() => useEventStore.getState().setActiveSection("agents"));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });

    expect(count(ROSTER_URL)).toBe(1);
    expect(count(TEAMS_URL)).toBe(1);
  });

  it("leaves the teams alone while only the sample roster is known", async () => {
    agents = [];
    renderHook(() => useSocietyWarmup(), { wrapper });

    await waitFor(() => expect(client.getQueryData<RosterData>(ROSTER_KEY)?.sample).toBe(true));
    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    expect(count(TEAMS_URL)).toBe(0);
  });

  it("stays quiet in a detached window of another section", async () => {
    useEventStore.setState({ activeSection: "agentic-ide", solo: true });
    renderHook(() => useSocietyWarmup(), { wrapper });

    await act(async () => { await new Promise((resolve) => setTimeout(resolve, 20)); });
    expect(calls).toEqual([]);
  });
});
