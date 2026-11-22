import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { CONVERSATION_CLEARED } from "@/components/agentchat/reduce";
import { createAgentChatStore } from "@/store/agentChat";

/**
 * `/clear` in a coding thread starts its conversation over (maintainer,
 * 2026-11-22: the command ran as a turn of the CLI and the thread kept
 * showing everything). No message is written for it, so the thread draws none.
 */

class FakeSocket {
  onopen: (() => void) | null = null;
  onmessage: ((msg: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  close() {}
}

function answering(message: Record<string, unknown>) {
  const calls: { url: string; body: Record<string, unknown> | null }[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: string, init?: RequestInit) => {
    const url = String(input);
    calls.push({ url, body: typeof init?.body === "string" ? JSON.parse(init.body) : null });
    if (url.endsWith("/messages")) return new Response(JSON.stringify(message), { status: 202 });
    return new Response(JSON.stringify({ sessions: [] }), { status: 200 });
  }));
  return calls;
}

function openThread() {
  const store = createAgentChatStore("agent", "clear-test");
  store.setState({ activeSessionId: "t1", opening: false });
  for (const [seq, kind, payload] of [
    [1, "user_message", { text: "first topic" }],
    [2, "turn_started", { turn_id: "a" }],
    [3, "assistant_text", { turn_id: "a", message_id: "m", text: "an answer" }],
    [4, "turn_finished", { turn_id: "a", status: "done" }],
  ] as const) store.getState().ingest({ seq, ts_ms: 1_000 + seq, kind, payload });
  return store;
}

describe("/clear in a coding thread", () => {
  beforeEach(() => {
    window.localStorage.clear();
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => vi.unstubAllGlobals());

  it("goes to the backend without a message drawn on its way, and no turn is awaited", async () => {
    const calls = answering({ turn_id: "", session_id: "t1", cleared: true });
    const store = openThread();
    const sending = store.getState().send("/clear");
    expect(store.getState().outbox ?? []).toEqual([]);
    expect(await sending).toBe("sent");
    expect(calls.find((call) => call.url.endsWith("/messages"))?.body).toMatchObject({ text: "/clear" });
    expect(store.getState().busy).toBe(false);
    expect(store.getState().activeSession?.running ?? false).toBe(false);
  });

  it("empties the thread when the clear arrives, down to one line", () => {
    answering({});
    const store = openThread();
    expect(store.getState().timeline.items).toHaveLength(2);
    store.getState().ingest({ seq: 5, ts_ms: 2_000, kind: CONVERSATION_CLEARED, payload: {} });
    const { items, lastSeq } = store.getState().timeline;
    expect(items).toHaveLength(1);
    expect(items[0]).toMatchObject({ type: "notice", kind: CONVERSATION_CLEARED });
    expect(lastSeq).toBe(5);
  });

  it("does nothing in a thread that does not exist yet", async () => {
    const calls = answering({});
    const store = createAgentChatStore("agent", "clear-draft-test");
    expect(await store.getState().send("/clear")).toBe("sent");
    expect(calls).toEqual([]);
    expect(store.getState().activeSessionId).toBeNull();
  });

  it("stays a message in a chat that is not a coding thread", async () => {
    answering({ turn_id: "t", session_id: "lead" });
    const store = createAgentChatStore("jarvis", "clear-lead-test");
    store.setState({ activeSessionId: "lead", opening: false });
    const sending = store.getState().send("/clear");
    expect(store.getState().outbox).toHaveLength(1);
    await sending;
  });
});
