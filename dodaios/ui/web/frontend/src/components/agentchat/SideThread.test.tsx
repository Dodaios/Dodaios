import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
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

describe("a message sent while the conversation still works", () => {
  it("reads as the person's message with its answer once it is answered", () => {
    draw(conversation(ev("notice", {
      kind: "side_thread_finished", side_id: "side-1", status: "done", text: QUESTION, answer: "Canberra.",
    })));
    const thread = screen.getByTestId("side-thread");
    expect(thread.getAttribute("data-status")).toBe("done");
    // Their own bubble, like every message of theirs, then the reply.
    expect(within(thread).getByTestId("agent-message-user").textContent).toBe(QUESTION);
    expect(within(thread).getByTestId("side-thread-answer").textContent).toContain("Canberra.");
    // Answered: nothing but the exchange itself, no label under the message.
    expect(within(thread).queryByTestId("side-thread-state")).toBeNull();
    // Finished: nothing to stop or move, and no second connection for a reopened chat.
    expect(within(thread).queryByTestId("side-thread-stop")).toBeNull();
    expect(Socket.open).toHaveLength(0);
  });

  it("says how an unanswered one ended", () => {
    draw(conversation(ev("notice", { kind: "side_thread_finished", side_id: "side-1", status: "interrupted", text: QUESTION })));
    const state = screen.getByTestId("side-thread-state").textContent ?? "";
    expect(state).toContain("restart");
    expect(screen.queryByTestId("side-thread-answer")).toBeNull();
  });

  it("shows the answer being written, from the side thread's own session", async () => {
    draw(conversation());
    const thread = screen.getByTestId("side-thread");
    expect(thread.getAttribute("data-status")).toBe("running");
    expect(within(thread).getByTestId("side-thread-state").textContent).toContain("beside the running task");
    await waitFor(() => expect(Socket.open).toHaveLength(1));
    expect(decodeURIComponent(Socket.open[0].url)).toContain("/sessions/side-1/ws");

    act(() => Socket.open[0].push({
      type: "snapshot",
      session: { session_id: "side-1", provider: "openai", model: "m", effort: "", surface: "jarvis", running: true },
      events: [
        { seq: 1, ts_ms: 1, kind: "user_message", payload: { text: QUESTION } },
        { seq: 2, ts_ms: 2, kind: "turn_started", payload: { turn_id: "s-t1", provider: "openai", model: "m" } },
        { seq: 3, ts_ms: 3, kind: "assistant_text", payload: { turn_id: "s-t1", message_id: "m1", text: "Canberra." } },
      ],
    }));
    const live = await within(thread).findByTestId("side-thread-live");
    expect(live.textContent).toContain("Canberra.");
    // The person's message is the bubble above, not repeated inside the answer.
    expect(within(live).queryByTestId("agent-message-user")).toBeNull();
    // A side thread never becomes the chat a voice call continues.
    expect(fetcher.mock.calls.some(([url]) => String(url).includes("voice"))).toBe(false);
  });

  it("stops only this answer, or moves the message to the running task", async () => {
    draw(conversation());
    fireEvent.click(screen.getByTestId("side-thread-stop"));
    await waitFor(() => expect(fetcher.mock.calls.some(
      ([url, init]) => url === "/api/agent-chat/sessions/lead-1/side-threads/side-1/stop" && init?.method === "POST",
    )).toBe(true));
    fireEvent.click(screen.getByTestId("side-thread-to-main"));
    await waitFor(() => expect(fetcher.mock.calls.some(
      ([url, init]) => url === "/api/agent-chat/sessions/lead-1/side-threads/side-1/to-main" && init?.method === "POST",
    )).toBe(true));
  });
});
