/**
 * The limits and permissions in the agent pane's Tools & access tab — the
 * budget, ceiling, approval mode and concurrency a person can change after
 * the agent exists.
 *
 * What this pins is the part that would break silently: Save sends ONLY the
 * fields that changed. The route re-derives an agent's focus whenever a title
 * or description arrives, so a budget edit that carried prose or tool lists
 * along would quietly rewrite the tools the agent reaches for.
 */
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

import { ToolsTab } from "@/components/society/card/pane/ToolsTab";
import type { SocietyAgent } from "@/components/society/data";

const AGENT: SocietyAgent = {
  agentId: "gamil-agent",
  name: "Gamil agent",
  title: "Specialist",
  description: "Look after the mail.",
  tier: "specialist",
  provider: "",
  providerLabel: "",
  model: "",
  effort: "",
  figure: null,
  palette: { primary: "#2f6f4f", secondary: "#8a5a3b", accent: "#ffd166" },
  grantMode: "all",
  toolGrants: [],
  focus: ["plugin:gmail"],
  denies: [],
  approvalRules: { requireApproval: [], alwaysAllow: [] },
  permissionCeiling: "monitor",
  dailyBudgetUsd: 2,
  checkpoint: "idle",
  state: "idle",
  lifecycle: "active",
  createdMs: 1_788_000_000_000,
  maxConcurrentRuns: 1,
  workspaceDir: "society/gamil-agent/workspace",
  wikiNamespace: "society/gamil-agent/",
  chatSessionId: "society:gamil-agent",
  routines: [],
  stats: { runs: 0, totalCostUsd: 0, spentTodayUsd: 0, lastActiveMs: null },
};

function rowFor(agent: SocietyAgent, body: Record<string, unknown>) {
  return {
    agent: {
      agent_id: agent.agentId, name: agent.name, title: agent.title, description: agent.description,
      tier: agent.tier, parent_agent_id: null, state: "active", avatar: {}, checkpoint: "idle",
      provider: "", model: "", effort: "", account_id: "", grant_mode: agent.grantMode,
      grants: agent.toolGrants, focus: agent.focus, denies: agent.denies, skills: null,
      workspace_dir: agent.workspaceDir, wiki_namespace: agent.wikiNamespace, knowledge_scope: "shared",
      permission_ceiling: agent.permissionCeiling, approval_mode: agent.approvalMode ?? null,
      approval_rules: { require_approval: [], always_allow: [] },
      daily_budget_usd: agent.dailyBudgetUsd, max_concurrent_runs: agent.maxConcurrentRuns,
      browser_mode: "own", browser_allowed_domains: [], computer_id: null, runtime: "jarvis",
      session_id: agent.chatSessionId, created_ms: 0, updated_ms: 0,
      stats: { runs: 0, total_cost_usd: 0, last_active_ms: null },
      ...body,
    },
  };
}

function renderTab(over: Partial<SocietyAgent> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, staleTime: Infinity } },
  });
  const agent = { ...AGENT, ...over };
  return render(
    <QueryClientProvider client={client}>
      <ToolsTab agent={agent} sample={false} />
    </QueryClientProvider>,
  );
}

let fetchMock: ReturnType<typeof vi.fn>;

function patchBody(): Record<string, unknown> {
  const patch = fetchMock.mock.calls.find((c) => (c[1] as RequestInit | undefined)?.method === "PATCH");
  expect(patch).toBeTruthy();
  return JSON.parse(String((patch?.[1] as RequestInit).body)) as Record<string, unknown>;
}

describe("the agent pane's limits and permissions", () => {
  beforeEach(() => {
    fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (String(url).includes("/capabilities")) {
        return { ok: true, json: async () => ({ capabilities: [] }) } as Response;
      }
      if (String(url).includes("/providers")) {
        return { ok: true, json: async () => ({ providers: [] }) } as Response;
      }
      if (init?.method === "PATCH") {
        return { ok: true, json: async () => rowFor(AGENT, JSON.parse(String(init.body))) } as Response;
      }
      return { ok: true, json: async () => ({}) } as Response;
    });
    vi.stubGlobal("fetch", fetchMock);
  });
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
    vi.restoreAllMocks();
  });

  test("nothing is sent and no save bar shows until something changes", async () => {
    renderTab();
    await screen.findByTestId("agent-pane-limits");
    expect(screen.queryByTestId("agent-pane-savebar")).toBeNull();
    expect(fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === "PATCH")).toBe(false);
  });

  test("a budget edit sends the budget and nothing that would re-derive the tools", async () => {
    renderTab();
    fireEvent.change(await screen.findByTestId("agent-budget-input"), { target: { value: "7.5" } });
    fireEvent.click(screen.getByTestId("agent-pane-save"));
    await waitFor(() => expect(patchBody()).toEqual({ daily_budget_usd: 7.5 }));
  });

  test("raising the legacy ceiling asks first, then saves it", async () => {
    renderTab();
    const ceiling = await screen.findByTestId("agent-pane-ceiling");
    fireEvent.click(within(ceiling).getByText("Ask first"));
    fireEvent.click(screen.getByTestId("agent-pane-save"));
    const confirm = await screen.findByTestId("agent-pane-widen");
    await waitFor(() => expect(confirm.textContent).toContain("Ask first"));
    expect(fetchMock.mock.calls.some((c) => (c[1] as RequestInit | undefined)?.method === "PATCH")).toBe(false);
    fireEvent.click(screen.getByTestId("agent-pane-widen-confirm"));
    await waitFor(() => expect(patchBody()).toEqual({ permission_ceiling: "ask" }));
  });

  test("a stricter approval mode saves without a confirmation", async () => {
    renderTab({ approvalMode: "bypass" });
    const modes = await screen.findByTestId("agent-pane-approval-mode");
    fireEvent.click(within(modes).getByText("Always ask"));
    fireEvent.click(screen.getByTestId("agent-pane-save"));
    await waitFor(() => expect(patchBody()).toEqual({ approval_mode: "always_ask" }));
    expect(screen.queryByTestId("agent-pane-widen")).toBeNull();
  });

  test("an empty budget means no cap rather than a broken number", async () => {
    renderTab();
    fireEvent.change(await screen.findByTestId("agent-budget-input"), { target: { value: "" } });
    fireEvent.click(screen.getByTestId("agent-pane-save"));
    await waitFor(() => expect(patchBody().daily_budget_usd).toBe(0));
  });

  test("switching the cap off sends 0, which is the scheduler's no-cap", async () => {
    renderTab();
    fireEvent.click(await screen.findByTestId("agent-budget-switch"));
    expect(screen.queryByTestId("agent-budget-input")).toBeNull();
    fireEvent.click(screen.getByTestId("agent-pane-save"));
    await waitFor(() => expect(patchBody()).toEqual({ daily_budget_usd: 0 }));
  });

  test("a stored 0 reads as the cap switched off, and turning it on restores a number", async () => {
    renderTab({ dailyBudgetUsd: 0 });
    const toggle = await screen.findByTestId("agent-budget-switch");
    expect(toggle.getAttribute("aria-checked")).toBe("false");
    expect(screen.queryByTestId("agent-budget-input")).toBeNull();
    fireEvent.click(toggle);
    expect(screen.getByTestId("agent-budget-input")).toBeTruthy();
    fireEvent.click(screen.getByTestId("agent-pane-save"));
    await waitFor(() => expect(patchBody()).toEqual({ daily_budget_usd: 2 }));
  });

  test("after a save, a later change to the agent is adopted rather than shadowed by a stale draft", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false, staleTime: Infinity } } });
    const tree = (agent: SocietyAgent) => (
      <QueryClientProvider client={client}>
        <ToolsTab agent={agent} sample={false} />
      </QueryClientProvider>
    );
    // The server stores sets sorted: the saved row lists the sites in another order.
    const view = render(tree(AGENT));
    const sites = await screen.findByTestId("agent-pane-sites");
    for (const site of ["zeta.example", "alpha.example"]) {
      fireEvent.change(within(sites).getByRole("textbox"), { target: { value: site } });
      fireEvent.keyDown(within(sites).getByRole("textbox"), { key: "Enter" });
    }
    fireEvent.click(screen.getByTestId("agent-pane-save"));
    await waitFor(() => expect(patchBody()).toEqual({ browser_allowed_domains: ["zeta.example", "alpha.example"] }));
    const saved: SocietyAgent = { ...AGENT, browserAllowedDomains: ["alpha.example", "zeta.example"] };
    view.rerender(tree(saved));
    await waitFor(() => expect(screen.queryByTestId("agent-pane-savebar")).toBeNull());
    // An approved proposal then moves the budget: the tab shows it, with nothing "unsaved".
    view.rerender(tree({ ...saved, dailyBudgetUsd: 5 }));
    await waitFor(() => expect((screen.getByTestId("agent-budget-input") as HTMLInputElement).value).toBe("5"));
    expect(screen.queryByTestId("agent-pane-savebar")).toBeNull();
  });

  test("Discard returns every field to the saved value", async () => {
    renderTab();
    const input = (await screen.findByTestId("agent-budget-input")) as HTMLInputElement;
    fireEvent.change(input, { target: { value: "9" } });
    fireEvent.click(await screen.findByText("Discard"));
    expect((screen.getByTestId("agent-budget-input") as HTMLInputElement).value).toBe("2");
    expect(screen.queryByTestId("agent-pane-savebar")).toBeNull();
  });
});
