import { act, cleanup, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentChatEvent } from "@/lib/agentChatApi";
import { useAgentChatStore } from "@/store/agentChat";
import { AgentTimeline } from "./AgentTimeline";
import { EMPTY_TIMELINE, reduceEvents } from "./reduce";

const QUESTION = "What is the capital of Australia?";

let seq = 0;
function ev(kind: string, payload: Record<string, unknown>): AgentChatEvent {
  return { seq: ++seq, ts_ms: 1000 + seq, kind, payload } as AgentChatEvent;
}

/** The lead's conversation: a request still running, and a message sent meanwhile. */
function conversation(...closing: AgentChatEvent[]) {
  return reduceEvents(EMPTY_TIMELINE, [
    ev("user_message", { text: "Compare three standing desks" }),
    ev("turn_started", { turn_id: "t1" }),
    ev("notice", { kind: "side_thread_started", side_id: "side-1", text: QUESTION }),
    ...closing,
  ]).items;
}

function draw(items: ReturnType<typeof conversation>) {
  return render(
    <AgentTimeline items={items} assistantName="Dodaios" providerLabel={(id) => id} onDecide={() => undefined} bubbles />,
  );
}

type Frame = { data: string };
class Socket {
  static open: Socket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((frame: Frame) => void) | null = null;
  onclose: (() => void) | null = null;
  close = vi.fn();
  constructor(public url: string) { Socket.open.push(this); }
  push(frame: Record<string, unknown>) { this.onmessage?.({ data: JSON.stringify(frame) }); }
}

let fetcher: ReturnType<typeof vi.fn>;

beforeEach(() => {
  Socket.open = [];
  vi.stubGlobal("WebSocket", Socket);
  fetcher = vi.fn(async (url: string) => new Response(
    JSON.stringify(String(url).includes("/to-main") ? { outcome: "queued" } : { stopped: true }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  ));
  vi.stubGlobal("fetch", fetcher);
  useAgentChatStore.setState({ activeSessionId: "lead-1" });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  useAgentChatStore.setState({ activeSessionId: null });
  seq = 0;
});

const SNAPSHOT = (...events: Record<string, unknown>[]) => ({
  type: "snapshot",
  session: { session_id: "side-1", provider: "openai", model: "m", effort: "", surface: "jarvis", running: true },
  events: [
    { seq: 1, ts_ms: 1, kind: "user_message", payload: { text: QUESTION } },
    { seq: 2, ts_ms: 2, kind: "turn_started", payload: { turn_id: "s-t1", provider: "openai", model: "m" } },
    ...events,
  ],
});
const FINISHED = ev("notice", { kind: "side_thread_finished", side_id: "side-1", status: "done", text: QUESTION, answer: "Canberra." });

describe("a message sent while the conversation still works", () => {
  it("reads as the person's message with its answer once it is answered", () => {
    draw(conversation(FINISHED));
    // Their own bubble, like every message of theirs, then the reply.
    const mine = screen.getAllByTestId("agent-message-user").find((node) => node.getAttribute("data-side-thread") === "message")!;
    expect(mine.textContent).toBe(QUESTION);
    const reply = screen.getByTestId("side-thread-reply");
    expect(reply.getAttribute("data-status")).toBe("done");
    expect(within(reply).getByTestId("side-thread-answer").textContent).toContain("Canberra.");
    // Nothing but the exchange itself: no label, no control, and no second
    // connection for a reopened chat.
    expect(screen.queryByTestId("side-thread-state")).toBeNull();
    expect(within(reply).queryAllByRole("button")).toHaveLength(0);
    expect(Socket.open).toHaveLength(0);
  });

  it("keeps each message of a finished one a bubble of its own", () => {
    // Said at once, said when the agent was sent, and the result minutes later.
    const messages = [
      "I'll look at your screenshot and then send an agent.",
      "An agent is on it. I'll tell you what it changed.\n\nIt works on a branch of its own.",
      "Done: the line is gone from the chat.",
    ];
    draw(conversation(ev("notice", {
      kind: "side_thread_finished", side_id: "side-1", status: "done", text: QUESTION,
      answer: messages.slice(1).join("\n\n"), messages,
    })));
    const bubbles = within(screen.getByTestId("side-thread-answer")).getAllByTestId("lead-bubble");
    // One bubble per message, however many paragraphs it has, in the order they were written.
    expect(bubbles).toHaveLength(3);
    expect(bubbles[0].textContent).toBe(messages[0]);
    expect(bubbles[1].textContent).toContain("An agent is on it.");
    expect(bubbles[1].textContent).toContain("It works on a branch of its own.");
    expect(bubbles[2].textContent).toBe(messages[2]);
    expect(Socket.open).toHaveLength(0);
  });

  it("draws a notice that only carries the answer as the one message it has", () => {
    draw(conversation(ev("notice", {
      kind: "side_thread_finished", side_id: "side-1", status: "done", text: QUESTION,
      answer: "Canberra.\n\nIt is in the south-east.", messages: [],
    })));
    expect(within(screen.getByTestId("side-thread-answer")).getAllByTestId("lead-bubble")).toHaveLength(1);
  });

  it("says how an unanswered one ended", () => {
    draw(conversation(ev("notice", { kind: "side_thread_finished", side_id: "side-1", status: "interrupted", text: QUESTION })));
    expect(screen.getByTestId("side-thread-state").textContent).toContain("restart");
    expect(screen.queryByTestId("side-thread-answer")).toBeNull();
  });

  it("shows the answer being written, from the side thread's own session", async () => {
    draw(conversation());
    const reply = screen.getByTestId("side-thread-reply");
    expect(reply.getAttribute("data-status")).toBe("running");
    // How it is answered is not the person's concern: no label, no control.
    expect(screen.queryByTestId("side-thread-state")).toBeNull();
    expect(within(reply).queryAllByRole("button")).toHaveLength(0);
    await waitFor(() => expect(Socket.open).toHaveLength(1));
    expect(decodeURIComponent(Socket.open[0].url)).toContain("/sessions/side-1/ws");

    act(() => Socket.open[0].push(SNAPSHOT(
      { seq: 3, ts_ms: 3, kind: "assistant_text", payload: { turn_id: "s-t1", message_id: "m1", text: "Canberra." } },
    )));
    const live = await within(reply).findByTestId("side-thread-live");
    expect(live.textContent).toContain("Canberra.");
    // The person's message is the bubble above, not repeated inside the answer.
    expect(within(live).queryByTestId("agent-message-user")).toBeNull();
    // A side thread never becomes the chat a voice call continues.
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("voice"))).toBe(false);
  });

  it("does not draw an agent's result that its own answer takes up", async () => {
    draw(conversation());
    await waitFor(() => expect(Socket.open).toHaveLength(1));
    act(() => Socket.open[0].push({
      type: "snapshot",
      session: { session_id: "side-1", provider: "openai", model: "m", effort: "", surface: "jarvis", running: true },
      events: [
        { seq: 1, ts_ms: 1, kind: "user_message", payload: { text: QUESTION } },
        { seq: 2, ts_ms: 2, kind: "turn_started", payload: { turn_id: "s-t1", provider: "openai", model: "m" } },
        { seq: 3, ts_ms: 3, kind: "notice", payload: {
          kind: "coding_result", agent_name: "Claude Code", status: "completed", thread_id: "th1",
          text: "Claude Code has finished: # Review of the pull requests",
        } },
        { seq: 4, ts_ms: 4, kind: "assistant_text", payload: { turn_id: "s-t1", message_id: "m1", text: "The review is done." } },
      ],
    }));
    const live = await within(screen.getByTestId("side-thread-reply")).findByTestId("side-thread-live");
    expect(live.textContent).toContain("The review is done.");
    expect(live.textContent).not.toContain("has finished");
    expect(within(live).queryByTestId("coding-thread-activity")).toBeNull();
  });

  it("shows the assistant typing in one place only, at the bottom", async () => {
    // The complaint (maintainer, 2026-11-12): the turn above and the message
    // sent meanwhile each showed three dots.
    const view = draw(conversation());
    const dots = () => screen.getAllByTestId("typing-indicator");
    const reply = () => screen.getByTestId("side-thread-reply");
    const below = (node: Element, other: Element) => Boolean(other.compareDocumentPosition(node) & Node.DOCUMENT_POSITION_FOLLOWING);
    // The working turn has them, and stands below the message sent meanwhile.
    expect(dots()).toHaveLength(1);
    expect(screen.getByTestId("agent-turn").contains(dots()[0])).toBe(true);
    expect(below(dots()[0], reply())).toBe(true);

    // The side thread's own turn starts: still one set, still at the bottom.
    await waitFor(() => expect(Socket.open).toHaveLength(1));
    act(() => Socket.open[0].push(SNAPSHOT()));
    await screen.findByTestId("side-thread-live");
    expect(dots()).toHaveLength(1);
    expect(reply().contains(dots()[0])).toBe(false);

    // The turn above is done while the side thread still writes: it types now.
    const done = ev("turn_finished", { turn_id: "t1", status: "done" });
    view.rerender(<AgentTimeline items={conversation(done)} assistantName="Dodaios" providerLabel={(id) => id} onDecide={() => undefined} bubbles />);
    expect(dots()).toHaveLength(1);
    expect(reply().contains(dots()[0])).toBe(true);

    // Everything answered: nobody types.
    view.rerender(<AgentTimeline items={conversation(done, FINISHED)} assistantName="Dodaios" providerLabel={(id) => id} onDecide={() => undefined} bubbles />);
    expect(screen.queryAllByTestId("typing-indicator")).toHaveLength(0);
  });

  it("draws what the turn says after the message below that message", () => {
    // The complaint (maintainer, 2026-11-12): the newest words were above the
    // message sent meanwhile, and one had to scroll up to read them.
    const { container } = draw(reduceEvents(EMPTY_TIMELINE, [
      ev("user_message", { text: "Compare three standing desks" }),
      ev("turn_started", { turn_id: "t1" }),
      ev("assistant_text", { turn_id: "t1", message_id: "m1", text: "Looking at desks now." }),
      ev("notice", { kind: "side_thread_started", side_id: "side-1", text: QUESTION }),
      FINISHED,
      ev("assistant_text", { turn_id: "t1", message_id: "m2", text: "Here are the three desks." }),
      ev("turn_finished", { turn_id: "t1", status: "done" }),
    ]).items);
    const text = container.textContent ?? "";
    const order = ["Compare three standing desks", "Looking at desks now.", QUESTION, "Canberra.", "Here are the three desks."];
    expect(order.map((part) => text.indexOf(part))).toEqual([...order.map((part) => text.indexOf(part))].sort((a, b) => a - b));
    expect(order.every((part) => text.includes(part))).toBe(true);
    // The turn's earlier words are a part of it; the turn itself closes below.
    expect(screen.getByTestId("agent-turn-part").textContent).toContain("Looking at desks now.");
    expect(screen.getByTestId("agent-turn").textContent).toContain("Here are the three desks.");
    expect(screen.getByTestId("agent-turn").textContent).not.toContain("Looking at desks now.");
  });

  it("brings every new message out at the bottom while both answers are written", async () => {
    // The complaint (maintainer, 2026-11-13): with two messages answered at
    // once, the main turn's new messages appeared above the answer written
    // beside it, in the middle of the chat.
    const start = [
      ev("user_message", { text: "Send that to the agent" }),
      ev("turn_started", { turn_id: "t1" }),
      ev("notice", { kind: "side_thread_started", side_id: "side-1", text: QUESTION }),
    ];
    const view = draw(reduceEvents(EMPTY_TIMELINE, start).items);
    await waitFor(() => expect(Socket.open).toHaveLength(1));
    act(() => Socket.open[0].push(SNAPSHOT(
      { seq: 3, ts_ms: 1_010, kind: "assistant_text", payload: { turn_id: "s-t1", message_id: "s-m1", text: "Looking it up." } },
    )));
    await screen.findByText("Looking it up.");
    const redraw = (...more: AgentChatEvent[]) => view.rerender(
      <AgentTimeline items={reduceEvents(EMPTY_TIMELINE, [...start, ...more]).items} assistantName="Dodaios"
        providerLabel={(id) => id} onDecide={() => undefined} bubbles />,
    );
    const said = { seq: 10, ts_ms: 1_020, kind: "assistant_text", payload: { turn_id: "t1", message_id: "m1", text: "The agent is busy." } } as AgentChatEvent;
    redraw(said);
    const order = () => {
      const text = view.container.textContent ?? "";
      return ["Send that to the agent", QUESTION, "Looking it up.", "The agent is busy.", "Canberra."]
        .filter((part) => text.includes(part))
        .sort((a, b) => text.indexOf(a) - text.indexOf(b));
    };
    // The main turn's newest message stands below the side thread's message already on screen.
    expect(order()).toEqual(["Send that to the agent", QUESTION, "Looking it up.", "The agent is busy."]);

    // The side thread writes again: below that, at the bottom.
    act(() => Socket.open[0].push({ type: "event", event: {
      seq: 4, ts_ms: 1_030, kind: "assistant_text", payload: { turn_id: "s-t1", message_id: "s-m2", text: "Canberra." },
    } }));
    await screen.findByText("Canberra.");
    expect(order()).toEqual(["Send that to the agent", QUESTION, "Looking it up.", "The agent is busy.", "Canberra."]);
  });
});
