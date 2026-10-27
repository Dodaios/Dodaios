import { afterEach, describe, expect, test, vi } from "vitest";
import type { SocietyAgentRow } from "@/lib/societyApi";
import { fetchSocietyRoster, type RosterData } from "./data";
import { SAMPLE_ROSTER } from "./mockRoster";

const ROW = {
  agent_id: "agent-1", name: "Lumi", title: "", description: "", tier: "specialist",
  parent_agent_id: null, state: "active", avatar: null, checkpoint: "home", provider: "openai",
  model: "", effort: "", account_id: "", grant_mode: "all", grants: [], focus: [], denies: [],
  skills: null, workspace_dir: "", wiki_namespace: "", knowledge_scope: "shared",
  permission_ceiling: "ask", approval_mode: "bypass",
  approval_rules: { require_approval: [], always_allow: [] }, daily_budget_usd: 0,
  max_concurrent_runs: 1, browser_mode: "own", browser_allowed_domains: [], computer_id: null,
  runtime: "openclaw", session_id: "society:agent-1", created_ms: 0, updated_ms: 0,
  stats: { runs: 0, total_cost_usd: 0, last_active_ms: null },
} as unknown as SocietyAgentRow;

function answer(status: number, agents: SocietyAgentRow[] = []) {
  vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ agents }), { status })));
}

afterEach(() => vi.unstubAllGlobals());

const sampleIds = new Set(SAMPLE_ROSTER.map((agent) => agent.agentId));

describe("fetchSocietyRoster never makes up a roster", () => {
  test("a backend that is down or restarting is an error, not sample rows", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("Failed to fetch"); }));
    await expect(fetchSocietyRoster()).rejects.toThrow();
    answer(503);
    await expect(fetchSocietyRoster()).rejects.toThrow(/503/);
  });

  test("the real rows come through", async () => {
    answer(200, [ROW]);
    const roster = await fetchSocietyRoster();
    expect(roster.sample).toBe(false);
    expect(roster.agents.map((agent) => agent.agentId)).toEqual(["agent-1"]);
  });

  test("an empty roster is empty, never the sample agents", async () => {
    answer(200, []);
    const roster = await fetchSocietyRoster();
    expect(roster).toEqual({ agents: [], sample: false });
    expect(roster.agents.some((agent) => sampleIds.has(agent.agentId))).toBe(false);
  });

  test("an empty answer right after a real roster keeps the last known one (the query keeps it on error)", async () => {
    answer(200, [ROW]);
    const previous: RosterData = await fetchSocietyRoster();
    answer(200, []);
    await expect(fetchSocietyRoster(previous)).rejects.toThrow(/empty roster/);
  });
});
