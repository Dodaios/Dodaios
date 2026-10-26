import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

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
  it("records the request once and switches to the Agents section", () => {
    openAgent("scout", { sessionId: "society:scout", cardRef: "q1", kind: "question" });
    expect(useEventStore.getState().activeSection).toBe("agents");
    const taken = takeAgentRequest();
    expect(taken).toMatchObject({ agentId: "scout", cardRef: "q1", kind: "question" });
    expect(takeAgentRequest()).toBeNull();
  });

  it("gives two requests for the same agent different identities", () => {
    openAgent("scout");
    const first = useAgentNavigation.getState().request;
    openAgent("scout");
    expect(useAgentNavigation.getState().request?.nonce).not.toBe(first?.nonce);
  });

  it("ignores an empty agent id", () => {
    openAgent("");
    expect(useAgentNavigation.getState().request).toBeNull();
    expect(useEventStore.getState().activeSection).toBe("chats");
  });
});

describe("on screen", () => {
  it("counts only while the Agents section shows that agent", () => {
    setAgentOnScreen({ agentId: "scout" });
    expect(isAgentOnScreen("scout")).toBe(false); // another section is in front
    useEventStore.setState({ activeSection: "agents" });
    expect(isAgentOnScreen("scout")).toBe(true);
    expect(isAgentOnScreen("brain")).toBe(false);
    setAgentOnScreen(null);
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

  it("gives up quietly when no card shows", async () => {
    vi.useFakeTimers();
    const found = revealCard({ kind: "credential" }, { root: card(""), timeoutMs: 200, intervalMs: 50 });
    await vi.advanceTimersByTimeAsync(300);
    await expect(found).resolves.toBe(false);
    await expect(revealCard({})).resolves.toBe(false);
  });
});
