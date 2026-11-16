import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { createAgentChatStore } from "@/store/agentChat";
import { withOutbox } from "@/components/agentchat/outbox";

/**
 * A sent message is in the chat the moment Enter is pressed: the backend
 * records it only after it prepared the turn, about a second later
 * (maintainer, 2026-11-16: "the frame froze, nothing new in the UI").
 */

class FakeSocket {
  onopen: (() => void) | null = null;
  onmessage: ((msg: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close() {}
}

/** The send's answer waits until the test lets it through. */
function heldSend(): { release: (body: Record<string, unknown>, status?: number) => void } {
  let release!: (body: Record<string, unknown>, status?: number) => void;
  vi.stubGlobal("fetch", vi.fn(async (input: string) => {
    const url = String(input);
    if (url.endsWith("/messages")) {
      return new Promise<Response>((resolve) => {
        release = (body, status = 202) => resolve(new Response(JSON.stringify(body), { status }));
      });
    }
    return new Response(JSON.stringify({ sessions: [] }), { status: 200 });
  }));
  return { release: (body, status) => release(body, status) };
}

function openChat() {
  const store = createAgentChatStore("jarvis");
  store.setState({ activeSessionId: "lead", opening: false });
  return store;
}

describe("the outbox", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("draws the message and keeps the chat busy before the backend answers", async () => {
    const send = heldSend();
    const store = openChat();
    const sending = store.getState().send("  hello there  ");
    const state = store.getState();
    expect(state.busy).toBe(true);
    const drawn = withOutbox(state.timeline.items, state.outbox, "lead");
    expect(drawn).toHaveLength(1);
    expect(drawn[0]).toMatchObject({ type: "user", text: "hello there" });
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    send.release({ turn_id: "t1", session_id: "lead" });
    expect(await sending).toBe("sent");
    // Still drawn: its own message has not come back yet.
    expect(store.getState().outbox).toHaveLength(1);
  });

  it("gives way to the recorded message, so it is never drawn twice", async () => {
    const send = heldSend();
    const store = openChat();
    const sending = store.getState().send("hello");
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    store.getState().ingest({ seq: 7, ts_ms: Date.now(), kind: "user_message", payload: { text: "hello" } });
    expect(store.getState().outbox).toEqual([]);
    const state = store.getState();
    expect(withOutbox(state.timeline.items, state.outbox, "lead").filter((item) => item.type === "user")).toHaveLength(1);
    send.release({ turn_id: "t1", session_id: "lead" });
    await sending;
  });

  it("drops the message when the send fails: the composer has the words back", async () => {
    const send = heldSend();
    const store = openChat();
    const sending = store.getState().send("hello");
    await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
    send.release({ detail: "a turn is already running" }, 409);
    expect(await sending).toBe("failed");
    expect(store.getState().outbox).toEqual([]);
  });

  it("drops the message the backend steered into the running turn or answered beside it", async () => {
    for (const answer of [{ steered: true }, { side_thread: "side-1" }, { queued: true, queue_id: "q" }, { ritual: "r1" }]) {
      const send = heldSend();
      const store = openChat();
      const sending = store.getState().send("hello");
      await vi.waitFor(() => expect(fetch).toHaveBeenCalled());
      send.release({ turn_id: "", session_id: "lead", ...answer });
      await sending;
      expect(store.getState().outbox).toEqual([]);
    }
  });

  it("is not drawn in another chat", () => {
    heldSend();
    const store = openChat();
    void store.getState().send("hello");
    const state = store.getState();
    expect(withOutbox([], state.outbox, "other")).toEqual([]);
  });
});
