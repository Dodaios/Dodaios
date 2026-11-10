import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { activityOf, costLine, LeadActivityPanel, type Proactive } from "./LeadActivityPanel";
import type { TimelineItem } from "@/components/agentchat/reduce";
import { useAgentChatStore } from "@/store/agentChat";

const t = (key: string) => key;
const turn = (id: string, extra: Record<string, unknown>): TimelineItem => ({
  type: "turn", id, provider: "openai", model: "m", effort: "", runner: "brain", status: "done",
  blocks: [], startedMs: 1, durationMs: null, usage: null, liveUsage: null, costUsd: null, error: null,
  ...extra,
} as TimelineItem);

describe("activityOf", () => {
  it("sorts the conversation into waiting, running and done", () => {
    const items: TimelineItem[] = [
      turn("t1", { blocks: [{ kind: "tool", id: "c1", name: "gmail", approval: { approvalId: "a1", summary: "Send the reply", decision: null } }] }),
      turn("t2", { status: "running" }),
      turn("t3", { background: ["Research agent"] }),
      { type: "notice", id: "n1", kind: "society_result", text: "Flights found\nmore", agentName: "Scout", agentId: "s",
        status: "done", tsMs: 2, data: {}, resolved: "" },
    ];
    const { waiting, running, done } = activityOf(items, t);
    expect(waiting.map((r) => r.text)).toEqual(["Send the reply"]);
    expect(running.map((r) => r.text)).toEqual(["home.activity.answering", "Research agent"]);
    expect(done.map((r) => r.text)).toEqual(["Scout: Flights found"]);
    expect(done[0].messageId).toBe("n1");
  });
});

const proactive = (over: Partial<Proactive["settings"]> = {}, checks: Partial<Proactive["checks"]> = {}): Proactive => ({
  available: true,
  settings: { level: "off", topics: ["mail", "calendar", "agents", "deadlines"], interval_hours: 3, from_hour: 8, to_hour: 22, timezone: "", ...over },
  checks: { enabled: false, runs_per_day: 5, provider: "", model: "", billed_via_key: false, ...checks },
});

describe("costLine", () => {
  it("says off, how often and on what, or that an API-key seat is skipped", () => {
    expect(costLine(proactive(), t)).toBe("home.proactive.hint_off");
    const en = (key: string) => (key === "home.proactive.cost" ? "{n} checks, {from}-{to}, on {model}" : key);
    expect(costLine(proactive({ level: "important" }, { model: "sonnet" }), en)).toBe("5 checks, 8-22, on sonnet");
    expect(costLine(proactive({ level: "important" }), t)).toBe("home.proactive.cost_subscription");
    expect(costLine(proactive({ level: "important" }, { billed_via_key: true }), t)).toBe("home.proactive.cost_billed");
  });
});

describe("LeadActivityPanel proactivity setting", () => {
  afterEach(() => {
    cleanup();
    vi.unstubAllGlobals();
  });

  it("shows the level alone while off, and saves the whole setting on a change", async () => {
    let current = proactive();
    const puts: unknown[] = [];
    vi.stubGlobal("fetch", vi.fn(async (url: RequestInfo | URL, init?: RequestInit) => {
      const path = String(url);
      if (path === "/api/agent-chat/lead/brief") return new Response(JSON.stringify({ available: false }));
      if (path === "/api/agent-chat/lead/proactive" && init?.method === "PUT") {
        const body = JSON.parse(String(init.body)) as Proactive["settings"];
        puts.push(body);
        current = proactive(body, { enabled: body.level !== "off", runs_per_day: body.interval_hours === 6 ? 3 : 5 });
        return new Response(JSON.stringify(current));
      }
      return new Response(JSON.stringify(current));
    }));
    useAgentChatStore.setState({ timeline: { items: [], pendingApprovals: [], lastSeq: 0, sessionPatch: null } } as never);
    render(<LeadActivityPanel onClose={() => undefined} />);
    // The real English strings load in tests.
    const section = await screen.findByTestId("lead-proactive");
    expect(section.textContent).toContain("Off. On, it writes into this conversation only when something needs you.");
    expect(screen.queryByTestId("lead-proactive-mail")).toBeNull();
    expect(screen.queryByTestId("lead-proactive-interval")).toBeNull();

    fireEvent.click(screen.getByTestId("lead-proactive-level"));
    fireEvent.click(await screen.findByRole("option", { name: "Only important" }));
    await waitFor(() => expect(puts).toHaveLength(1));
    expect(puts[0]).toMatchObject({ level: "important", interval_hours: 3, topics: ["mail", "calendar", "agents", "deadlines"] });
    expect((puts[0] as { timezone: string }).timezone).toBeTruthy();
    // On: the rhythm, the topic switches and the honest cost line appear.
    await screen.findByTestId("lead-proactive-interval");
    expect(screen.getByTestId("lead-proactive-cost").textContent).toBe(
      "About 5 checks a day between 8:00 and 22:00, on your subscription or local model. Never bills an API key.",
    );
    expect(section.textContent).toContain("check on me in 25 minutes");

    fireEvent.click(screen.getByTestId("lead-proactive-mail"));
    await waitFor(() => expect(puts).toHaveLength(2));
    expect((puts[1] as { topics: string[] }).topics).toEqual(["calendar", "agents", "deadlines"]);
  });
});
