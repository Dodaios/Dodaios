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

  it("shows each account's state and saves its toggle and the own address", async () => {
    const puts: string[] = [];
    vi.stubGlobal("fetch", vi.fn(async (_url: RequestInfo | URL, init?: RequestInit) => {
      if (init?.method === "PUT") puts.push(String(init.body));
      return new Response(JSON.stringify(state({
        producers: [
          { id: "gmail", source: "mail", connected: true, state: "polling", last_poll: 1, last_event_at: 0, last_error: "", events: 0 },
          { id: "github", source: "github", connected: false, state: "not_connected", last_poll: 0, last_event_at: 0, last_error: "", events: 0 },
        ],
      })));
    }));
    render(<LeadTriggersSetting />);
    const list = await screen.findByTestId("lead-triggers-producers");
    expect(list.textContent).toContain("Gmail");
    expect(list.textContent).toContain("Not connected");
    fireEvent.click(screen.getByTestId("lead-triggers-producer-toggle-gmail"));
    await waitFor(() => expect(puts.some((body) => JSON.parse(body).producers?.gmail === false)).toBe(true));
    const input = screen.getByTestId("lead-triggers-agent-address");
    fireEvent.change(input, { target: { value: "agent@mail.example" } });
    fireEvent.blur(input);
    await waitFor(() => expect(puts.some((body) => JSON.parse(body).agent_address === "agent@mail.example")).toBe(true));
  });
});
