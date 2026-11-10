import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CostAgentBucket } from "@/hooks/useCosts";
import { useI18nStore } from "@/i18n";
import { useEventStore } from "@/store/events";
import { AgentSpendPanel, agentDisplayName } from "./AgentSpendPanel";

const clients: QueryClient[] = [];

beforeEach(() => {
  useI18nStore.getState().setUi("en", { push: false });
  useEventStore.setState({ assistantName: "Nova" });
  // The roster answers empty: names then come from the cost report itself.
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => new Response(JSON.stringify({ agents: [] }), { status: 200 })),
  );
});

afterEach(() => {
  cleanup();
  for (const client of clients.splice(0)) client.clear();
  vi.unstubAllGlobals();
});

function row(key: string, cost: number, extra: Partial<CostAgentBucket> = {}): CostAgentBucket {
  return {
    key, name: key, lead: false, archived: false,
    cost_usd: cost, tokens_in: 1_000, tokens_out: 100, tokens_cached: 0, tokens_total: 1_100,
    entries: 1, gap_tokens: 0, subscription_usd: 0, chars: 0, audio_ms: 0,
    price_sources: ["recorded"], last_ts_ms: 0, cost_share: 0, token_share: 0,
    members: [], breakdown: {},
    ...extra,
  };
}

function mount(rows: CostAgentBucket[], onToggle = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  clients.push(client);
  render(
    <QueryClientProvider client={client}>
      <AgentSpendPanel
        rows={rows}
        active={[]}
        onToggle={onToggle}
        money={(usd) => `$${usd.toFixed(2)}`}
      />
    </QueryClientProvider>,
  );
  return onToggle;
}

describe("AgentSpendPanel", () => {
  it("splits the assistant itself from its agents and lists the assistant first", () => {
    mount([
      row("scout", 4, { name: "Scout" }),
      row("jarvis", 1.5, { name: "Jarvis", lead: true }),
      row("archivist", 2, { name: "Archivist" }),
    ]);
    expect(screen.getByText("Nova itself")).toBeTruthy();
    expect(screen.getByText("$1.50", { selector: "div" })).toBeTruthy();
    expect(screen.getByText("All agents (2)")).toBeTruthy();
    expect(screen.getByText("$6.00")).toBeTruthy();

    const list = screen.getByRole("list", { name: "Spend per agent" });
    const names = within(list).getAllByRole("button").map((b) => b.textContent ?? "");
    expect(names[0]).toContain("Nova");
    expect(names[1]).toContain("Scout");
    expect(names[2]).toContain("Archivist");
  });

  it("filters the page to an agent when its row is clicked", () => {
    const onToggle = mount([row("scout", 4, { name: "Scout" })]);
    fireEvent.click(screen.getByRole("button", { name: /Scout/ }));
    expect(onToggle).toHaveBeenCalledWith("scout");
  });

  it("says so when no agent spent anything", () => {
    mount([]);
    expect(screen.getByText("No agent used anything in this period.")).toBeTruthy();
  });

  it("drops the roster's deletion suffix from a name", () => {
    expect(agentDisplayName({ key: "qa", name: "QA Hermes (deleted qa-hermes)" })).toBe("QA Hermes");
    expect(agentDisplayName({ key: "gone", name: "" })).toBe("gone");
  });
});
