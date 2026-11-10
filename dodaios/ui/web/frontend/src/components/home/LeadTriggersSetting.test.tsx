import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { droppedCount, LeadTriggersSetting, type Triggers } from "./LeadTriggersSetting";

const state = (over: Partial<Triggers> = {}): Triggers => ({
  settings: {
    accept: "observe",
    sources: { mail: { mode: "candidate", senders: [], scopes: [] } },
    policies: [{ id: "inv", text: "Tell me about invoices", sources: ["mail"], auto: false }],
  },
  counts: { received: 5, dropped_bot: 2, dropped_self: 1, candidates: 2 },
  waiting: 1,
  log: [{ id: "d1", action: "act", policy_id: "inv", policy_text: "Tell me about invoices", outcome: "would_have",
    event: { summary: "Invoice 7 overdue", source: "mail" } }],
  ...over,
});

describe("LeadTriggersSetting", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("counts every dropped reason", () => {
    expect(droppedCount(state().counts)).toBe(3);
  });

  it("lists what it would have done with the cited rule and promotes a rule", async () => {
    const calls: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      calls.push(`${init?.method ?? "GET"} ${String(url)}`);
      return new Response(JSON.stringify(state()));
    }));
    render(<LeadTriggersSetting />);
    const log = await screen.findByTestId("lead-triggers-log");
    expect(log.textContent).toContain("Invoice 7 overdue");
    expect(log.textContent).toContain("Tell me about invoices");
    fireEvent.click(screen.getByTestId("lead-triggers-promote-inv"));
    await waitFor(() => expect(calls).toContain("POST /api/agent-chat/lead/triggers/policies/inv/promote"));
  });

  it("shows only the mode while off and ignores a response of another shape", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify(state({
      settings: { accept: "off", sources: {}, policies: [] } })))));
    render(<LeadTriggersSetting />);
    await screen.findByTestId("lead-triggers");
    expect(screen.queryByTestId("lead-triggers-log")).toBeNull();
    cleanup();
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ available: true }))));
    render(<LeadTriggersSetting />);
    await waitFor(() => expect(screen.queryByTestId("lead-triggers")).toBeNull());
  });
});
