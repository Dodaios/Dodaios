import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAgentChatStore } from "@/store/agentChat";
import { useEventStore } from "@/store/events";
import {
  findCard,
  HIGHLIGHT_MS,
  isAgentOnScreen,
  openAgent,
  revealCard,
  setAgentOnScreen,
  takeAgentRequest,
  useAgentNavigation,
} from "./agentNavigation";

function card(html: string): HTMLElement {
  const host = document.createElement("div");
  host.innerHTML = html;
  document.body.appendChild(host);
  return host;
}

beforeEach(() => {
  useAgentNavigation.setState({ request: null, onScreen: null });
  useEventStore.setState({ activeSection: "chats" });
});

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("openAgent", () => {
  it("lands in the assistant's conversation, never on the retired Agents page", () => {
    useEventStore.setState({ activeSection: "memory" });
    openAgent("scout", { sessionId: "society:scout", cardRef: "q1", kind: "question" });
    expect(useEventStore.getState().activeSection).toBe("chats");
    expect(takeAgentRequest()).toBeNull();
  });

  it("opens the chat a card lives in when it is not the conversation itself", () => {
    const openSession = vi.fn();
    useAgentChatStore.setState({ activeSessionId: "other", openSession } as never);
    openAgent("jarvis", { sessionId: "s-7", cardRef: "a1", kind: "approval" });
    expect(openSession).toHaveBeenCalledWith("s-7");
    openSession.mockClear();
    openAgent("jarvis", { sessionId: "society:jarvis" });
    expect(openSession).not.toHaveBeenCalled();
  });

  it("ignores an empty agent id", () => {
    useEventStore.setState({ activeSection: "memory" });
    openAgent("");
    expect(useEventStore.getState().activeSection).toBe("memory");
  });
});

describe("on screen", () => {
  it("counts the assistant as on screen while its conversation is in front", () => {
    expect(isAgentOnScreen("jarvis")).toBe(true);
    useEventStore.setState({ activeSection: "memory" });
    expect(isAgentOnScreen("jarvis")).toBe(false);
  });

  it("never counts another agent: its page is retired", () => {
    setAgentOnScreen({ agentId: "scout" });
    expect(isAgentOnScreen("scout")).toBe(false);
    useEventStore.getState().setActiveSection("agents");
    expect(isAgentOnScreen("scout")).toBe(false);
  });
});

describe("cards", () => {
  it("finds a card by its ref first, else the newest open card of the kind", () => {
    const host = card(`
      <div data-testid="question-card" data-state="open" id="old"></div>
      <div data-testid="question-card" data-state="person"></div>
      <div data-testid="question-card" data-state="open" id="new"></div>
      <div data-card-ref="q-exact" id="exact"></div>
    `);
    expect(findCard(host, "q-exact", "question")?.id).toBe("exact");
    expect(findCard(host, "missing", "question")?.id).toBe("new");
    expect(findCard(host, "missing")).toBeNull();
  });

  it("waits for the card to render, then scrolls to it and marks it", async () => {
    vi.useFakeTimers();
    const host = card("");
    const found = revealCard({ cardRef: "a1", kind: "approval" }, { root: host, intervalMs: 50 });
    const later = document.createElement("div");
    later.dataset.testid = "thread-approval";
    later.scrollIntoView = vi.fn();
    host.appendChild(later);
    await vi.advanceTimersByTimeAsync(60);
    await expect(found).resolves.toBe(true);
    expect(later.scrollIntoView).toHaveBeenCalled();
    expect(later.dataset.attentionHighlight).toBe("true");
    await vi.advanceTimersByTimeAsync(HIGHLIGHT_MS + 10);
    expect(later.dataset.attentionHighlight).toBeUndefined();
  });

  it("finds a login card and a Connect card as the credential kind", () => {
    for (const testId of ["login-card", "connect-card"]) {
      const host = document.createElement("div");
      host.innerHTML = `<div data-testid="${testId}" data-state="success"></div><div id="open" data-testid="${testId}" data-state="open"></div>`;
      expect(findCard(host, undefined, "credential")?.id).toBe("open");
    }
  });

  it("gives up quietly when no card shows", async () => {
    vi.useFakeTimers();
    const found = revealCard({ kind: "credential" }, { root: card(""), timeoutMs: 200, intervalMs: 50 });
    await vi.advanceTimersByTimeAsync(300);
    await expect(found).resolves.toBe(false);
    await expect(revealCard({})).resolves.toBe(false);
  });
});
