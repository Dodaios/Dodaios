import { cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { resetThreadLinksForTests } from "@/components/agentic/threads/CodingAgentLink";
import type { AgentChatEvent } from "@/lib/agentChatApi";
import { useAgentChatStore } from "@/store/agentChat";
import { AgentTimeline } from "./AgentTimeline";
import { LeadReply } from "./LeadReply";
import { linkBareThreadCodes, linkedThreadRefs, linksThread } from "./chatLinks";
import { chronological } from "./chronology";
import { EMPTY_TIMELINE, reduceEvents, type TurnItem } from "./reduce";

const THREAD = "a81a561c77124310afcd94f5c2a497d7";
const OTHER = "bddece0011224455667788990011aabb";
const PAGE = "20261113T164638__node__161187cead31::tasks/node/artifacts/files/reise.html";

let seq = 0;
function ev(kind: string, payload: Record<string, unknown>, ts?: number): AgentChatEvent {
  seq += 1;
  return { seq, ts_ms: ts ?? 1000 + seq, kind, payload } as AgentChatEvent;
}

/** The thread-link endpoint knows THREAD and OTHER; every other reference is no thread. */
function threadLinks() {
  const known: Record<string, Record<string, unknown>> = {
    [THREAD]: { found: true, session_id: THREAD, code: "a81a56", title: "Hover popover disappears", agent: "claude", agent_label: "Claude Code" },
    a81a56: { found: true, session_id: THREAD, code: "a81a56", title: "Hover popover disappears", agent: "claude", agent_label: "Claude Code" },
    bddece: { found: true, session_id: OTHER, code: "bddece", title: "Dictation rebuild", agent: "claude", agent_label: "Claude Code" },
  };
  return vi.fn(async (url: string) => {
    const ref = decodeURIComponent(String(url).split("/thread-links/")[1] ?? "");
    return new Response(JSON.stringify(known[ref] ?? { found: false, ref }), { status: 200, headers: { "Content-Type": "application/json" } });
  });
}

function draw(items: ReturnType<typeof reduceEvents>["items"]) {
  return render(<AgentTimeline items={items} assistantName="Dodaios" providerLabel={(id) => id} onDecide={() => undefined} bubbles />);
}

const STARTED_AGENT = { kind: "coding_thread", thread_id: THREAD, title: "Hover popover disappears", agent: "Claude Code", folder: "/x", text: "Started a Claude Code thread: Hover popover disappears" };

beforeEach(() => {
  resetThreadLinksForTests();
  vi.stubGlobal("fetch", threadLinks());
  useAgentChatStore.setState({ activeSessionId: "lead-1" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useAgentChatStore.setState({ activeSessionId: null });
  seq = 0;
});

describe("a coding agent the assistant started", () => {
  it("goes onto the turn that started it, once, and adds no row of its own", () => {
    const { items } = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "Fix the hover popover" }),
      ev("turn_started", { turn_id: "t1" }),
      ev("notice", STARTED_AGENT),
      ev("notice", STARTED_AGENT),
    ]);
    expect(items.map((item) => item.type)).toEqual(["user", "turn"]);
    expect((items[1] as TurnItem).codingThreads).toEqual([{ threadId: THREAD, title: "Hover popover disappears", agent: "Claude Code" }]);
  });

  it("is shown in the answer as a link to its thread, though the words do not link it", async () => {
    const { items } = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "Fix the hover popover" }),
      ev("turn_started", { turn_id: "t1" }),
      ev("notice", STARTED_AGENT),
      ev("assistant_text", { turn_id: "t1", text: "An Opus agent is on it now." }),
      ev("turn_finished", { turn_id: "t1", status: "done" }),
    ]);
    draw(items);
    const turn = screen.getByTestId("agent-turn");
    const links = within(turn).getByTestId("answer-coding-agents");
    await waitFor(() => expect(within(links).getByTestId("coding-agent-link").textContent).toContain("Hover popover disappears"));
  });

  it("is not linked twice when the words already link it", () => {
    const { items } = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "Fix the hover popover" }),
      ev("turn_started", { turn_id: "t1" }),
      ev("notice", STARTED_AGENT),
      ev("assistant_text", { turn_id: "t1", text: "[Hover popover disappears](thread:a81a56) works on it." }),
      ev("turn_finished", { turn_id: "t1", status: "done" }),
    ]);
    draw(items);
    expect(screen.queryByTestId("answer-coding-agents")).toBeNull();
    expect(screen.getAllByTestId("coding-agent-link")).toHaveLength(1);
  });

  it("is not linked again under a later message when an earlier one, placed above, links it", () => {
    const { items } = reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "Fix the hover popover" }, 100),
      ev("turn_started", { turn_id: "t1" }, 110),
      ev("notice", STARTED_AGENT, 120),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: `[Hover popover disappears](thread:${THREAD}) works on it.` }, 130),
      ev("user_message", { text: "And the flights?" }, 140),
      ev("assistant_text", { turn_id: "t1", message_id: "m2", text: "It is done." }, 150),
    ]);
    const rows = chronological(items);
    const closing = rows.find((row) => row.kind === "item" && row.item.type === "turn");
    expect(closing && closing.kind === "item" && (closing.item as TurnItem).codingThreads).toEqual([]);
  });
});

describe("a coding agent's code written in an answer", () => {
  it("becomes a link in running text only", () => {
    expect(linkBareThreadCodes("Sent it to #bddece instead.")).toBe("Sent it to [#bddece](thread:bddece) instead.");
    expect(linkBareThreadCodes("(#A81A56)")).toBe("([#A81A56](thread:a81a56))");
    // A pull request number, inline code, a link, a web address and a code block stay as they are.
    for (const text of [
      "See #154512.",
      "Use `#bddece` as the colour.",
      "[#bddece](thread:bddece)",
      "https://example.test/#bddece",
      "```css\ncolor: #bddece;\n```",
      "a#bddece",
    ]) expect(linkBareThreadCodes(text)).toBe(text);
  });

  it("reads which threads a text links to", () => {
    const refs = linkedThreadRefs(`[A](thread:${THREAD}) and [B](thread:#BDDECE)`);
    expect(refs).toEqual([THREAD, "bddece"]);
    expect(linksThread(refs, OTHER)).toBe(true);
    expect(linksThread(["a81a57"], THREAD)).toBe(false);
  });

  it("opens the thread when one has that code, and stays plain text when none has", async () => {
    render(<LeadReply text="I will not send it to #bddece; the colour #ffaa00 stays." />);
    await waitFor(() => expect(screen.getByTestId("coding-agent-link").textContent).toContain("Dictation rebuild"));
    await waitFor(() => expect(screen.getByTestId("coding-agent-link-gone").textContent).toBe("#ffaa00"));
    expect(screen.getAllByTestId("coding-agent-link")).toHaveLength(1);
  });
});

describe("what a message answered beside a running request made", () => {
  function sideConversation(cards: Record<string, unknown>[]) {
    return reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "Search flights" }),
      ev("turn_started", { turn_id: "t1" }),
      ev("notice", { kind: "side_thread_started", side_id: "side-1", text: "Write my travel note" }),
      ev("notice", {
        kind: "side_thread_finished", side_id: "side-1", status: "done", text: "Write my travel note",
        answer: "Your travel note is in Nodes.", messages: ["Your travel note is in Nodes."], cards,
      }),
    ]).items;
  }

  it("shows the node it made under its answer", () => {
    draw(sideConversation([{ kind: "report", text: "Trip Munich – Dubai", summary: "", artifact: PAGE, sections: 0, ts_ms: 1003 }]));
    const answer = screen.getByTestId("side-thread-answer");
    expect(within(answer).getByTestId("page-card")).toBeTruthy();
    expect(within(answer).getByTestId("page-card-title").textContent).toContain("Trip Munich – Dubai");
  });

  it("shows several pages as links, and the coding agent it started", async () => {
    draw(sideConversation([
      { kind: "report", text: "Trip", artifact: PAGE, ts_ms: 1 },
      { kind: "report", text: "Packing list", artifact: `${PAGE.split("::")[0]}::tasks/node/artifacts/files/pack.html`, ts_ms: 2 },
      { ...STARTED_AGENT, ts_ms: 3 },
      { kind: "report", text: "No address" },
    ]));
    const answer = screen.getByTestId("side-thread-answer");
    expect(within(answer).getAllByTestId("page-link")).toHaveLength(2);
    expect(within(answer).queryByTestId("page-card")).toBeNull();
    await waitFor(() => expect(within(answer).getByTestId("coding-agent-link").textContent).toContain("Hover popover disappears"));
  });

  it("shows nothing more when it made nothing", () => {
    draw(sideConversation([]));
    const answer = screen.getByTestId("side-thread-answer");
    expect(within(answer).queryByTestId("side-thread-pages")).toBeNull();
    expect(within(answer).queryByTestId("answer-coding-agents")).toBeNull();
  });
});
