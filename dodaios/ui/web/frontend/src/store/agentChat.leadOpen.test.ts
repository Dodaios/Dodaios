import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { AgentChatSession } from "@/lib/agentChatApi";
import { createAgentChatStore } from "@/store/agentChat";

/**
 * The front page opens the lead's one conversation. The route that names it
 * answers slowly while the backend starts (1.1 s measured), so the id from
 * the last start opens at once and the route only confirms or corrects it;
 * meanwhile `opening` keeps the greeting off the page.
 */

const LEAD_KEY = "jarvis.agentChat.leadSession.v1";

function session(id: string): AgentChatSession {
  return {
    session_id: id,
    title: id,
    provider: "claude-api",
    model: "",
    effort: "high",
    cwd: "C:\\work",
    permission_mode: "ask",
    surface: "jarvis",
    vendor_session: null,
    created_ms: 1,
    updated_ms: 2,
    message_count: 1,
    preview: id,
  };
}

const sockets: FakeSocket[] = [];

class FakeSocket {
  onopen: (() => void) | null = null;
  onmessage: ((msg: { data: string }) => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  constructor(readonly url: string) {
    sockets.push(this);
  }
  close() {}
  /** The backend's first frame: the whole transcript. */
  snapshot(id: string, events: unknown[] = []) {
    this.onmessage?.({ data: JSON.stringify({ type: "snapshot", session: session(id), events }) });
  }
}

/** A lead route the test answers by hand; every other route answers plainly. */
function stubLead(): { answer: (id: string | null) => void } {
  let resolve: (response: Response) => void = () => {};
  const lead = new Promise<Response>((r) => { resolve = r; });
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = String(input);
      const reply = (data: unknown) => new Response(JSON.stringify(data), { status: 200 });
      if (url === "/api/agent-chat/lead") return lead;
      if (url.startsWith("/api/agent-chat/catalog")) return reply({ providers: [], default_cwd: "C:\\work", shell: "pwsh" });
      if (url.startsWith("/api/jarvis-agent/status")) return reply({ mapping: [] });
      if (url.startsWith("/api/agent-chat/sessions?")) return reply({ sessions: [] });
      return reply({});
    }),
  );
  return {
    answer: (id) => resolve(id ? new Response(JSON.stringify(session(id)), { status: 200 }) : new Response(null, { status: 500 })),
  };
}

const settle = () => new Promise((r) => setTimeout(r, 0));
const socketFor = (id: string) => sockets.filter((s) => s.url.includes(`/sessions/${id}/ws`));

describe("opening the lead's conversation", () => {
  beforeEach(() => {
    sockets.length = 0;
    localStorage.clear();
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("starts as opening, so the first paint shows no greeting", () => {
    stubLead();
    expect(createAgentChatStore("jarvis").getState().opening).toBe(true);
    // A side thread's view and the IDE's store never open the lead.
    expect(createAgentChatStore("jarvis", "side", { voice: false }).getState().opening).toBe(false);
    expect(createAgentChatStore("agent").getState().opening).toBe(false);
  });

  it("asks the route on a first start, then opens and remembers the conversation", async () => {
    const lead = stubLead();
    const store = createAgentChatStore("jarvis");
    store.getState().newChat();
    expect(store.getState().activeSessionId).toBeNull();
    expect(store.getState().opening).toBe(true);

    lead.answer("lead-1");
    await settle();
    expect(store.getState().activeSessionId).toBe("lead-1");
    expect(localStorage.getItem(LEAD_KEY)).toBe("lead-1");
    // Opened, but the transcript is not here yet.
    expect(store.getState().opening).toBe(true);

    socketFor("lead-1")[0].snapshot("lead-1");
    expect(store.getState().opening).toBe(false);
  });

  it("opens the remembered conversation at once, before the route answers", async () => {
    localStorage.setItem(LEAD_KEY, "lead-1");
    const lead = stubLead();
    const store = createAgentChatStore("jarvis");
    store.getState().newChat();
    expect(store.getState().activeSessionId).toBe("lead-1");
    expect(socketFor("lead-1")).toHaveLength(1);

    // The route confirms it: the socket already open stays.
    lead.answer("lead-1");
    await settle();
    expect(store.getState().activeSessionId).toBe("lead-1");
    expect(socketFor("lead-1")).toHaveLength(1);
  });

  it("follows the route when the remembered conversation is no longer the lead's", async () => {
    localStorage.setItem(LEAD_KEY, "old-lead");
    const lead = stubLead();
    const store = createAgentChatStore("jarvis");
    store.getState().newChat();
    expect(store.getState().activeSessionId).toBe("old-lead");

    lead.answer("lead-2");
    await settle();
    expect(store.getState().activeSessionId).toBe("lead-2");
    expect(localStorage.getItem(LEAD_KEY)).toBe("lead-2");
  });

  it("leaves a chat the person opened meanwhile alone", async () => {
    localStorage.setItem(LEAD_KEY, "old-lead");
    const lead = stubLead();
    const store = createAgentChatStore("jarvis");
    store.getState().newChat();
    store.getState().newChat({ voiceSessionId: "voice-1" });
    expect(store.getState().opening).toBe(false);

    lead.answer("lead-2");
    await settle();
    expect(store.getState().activeSessionId).toBeNull();
    expect(localStorage.getItem(LEAD_KEY)).toBe("lead-2");
  });

  it("shows the blank page with its greeting when the route fails and nothing was remembered", async () => {
    const lead = stubLead();
    const store = createAgentChatStore("jarvis");
    store.getState().newChat();
    lead.answer(null);
    await settle();
    expect(store.getState().activeSessionId).toBeNull();
    expect(store.getState().opening).toBe(false);
  });
});

describe("coming back to the front page", () => {
  beforeEach(() => {
    sockets.length = 0;
    localStorage.clear();
    vi.stubGlobal("WebSocket", FakeSocket);
  });
  afterEach(() => {
    vi.unstubAllGlobals();
    localStorage.clear();
  });

  it("paints the conversation already read at once and only asks for what is new", async () => {
    localStorage.setItem(LEAD_KEY, "lead-1");
    const lead = stubLead();
    const store = createAgentChatStore("jarvis");
    store.getState().newChat();
    socketFor("lead-1")[0].snapshot("lead-1", [
      { seq: 1, ts_ms: 1, kind: "user_message", payload: { text: "hello" } },
    ]);
    const shown = store.getState().timeline;
    expect(shown.items.length).toBeGreaterThan(0);

    // The Dodaios tab: a "new chat" that reopens the one conversation.
    store.getState().newChat();
    expect(store.getState().activeSessionId).toBe("lead-1");
    expect(store.getState().timeline).toBe(shown);
    expect(store.getState().opening).toBe(false);
    expect(socketFor("lead-1").at(-1)?.url).toContain("after=1");
    lead.answer("lead-1");
    await settle();
  });
});
