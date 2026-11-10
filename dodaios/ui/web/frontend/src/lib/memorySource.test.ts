import { afterEach, describe, expect, it, vi } from "vitest";

import { anchorOf, findMessage, jumpToMessage } from "@/lib/memorySource";
import { useEventStore } from "@/store/events";
import { useHomeStore } from "@/store/home";

function conversation(html: string): HTMLElement {
  const root = document.createElement("div");
  root.innerHTML = html;
  document.body.appendChild(root);
  return root;
}

afterEach(() => {
  document.body.innerHTML = "";
  vi.useRealTimers();
});

describe("anchorOf", () => {
  it("reads where a learned memory was said", () => {
    expect(anchorOf({ via: "review", session_id: "s1", turn_id: "t1", message_seq: 41, evidence: "I live in Hamburg" })).toEqual({
      sessionId: "s1",
      turnId: "t1",
      seq: 41,
      evidence: "I live in Hamburg",
    });
  });

  it("links a spoken memory by its quote alone", () => {
    expect(anchorOf({ via: "review", channel: "voice", evidence: "my dog Bruno" })).toEqual({
      sessionId: undefined,
      turnId: undefined,
      seq: undefined,
      evidence: "my dog Bruno",
    });
  });

  it("has no anchor for memories that never came from a conversation", () => {
    expect(anchorOf({ via: "import", file: "m.txt" })).toBeNull();
    expect(anchorOf({ via: "memory section" })).toBeNull();
    expect(anchorOf({ evidence: "only a quote, from an old import" })).toBeNull();
    expect(anchorOf(undefined)).toBeNull();
  });
});

describe("findMessage", () => {
  it("finds the message by number, then by quote, then the turn", () => {
    const root = conversation(`
      <p data-message-id="u-3">My sister Mia lives in Rome.</p>
      <div data-message-id="turn-3">Nice.</div>
      <p data-message-id="u-7">By the way, I live in   Hamburg now.</p>
      <div data-message-id="turn-7">Noted.</div>
    `);
    expect(findMessage({ seq: 7 }, root)?.dataset.messageId).toBe("u-7");
    expect(findMessage({ evidence: "I live in Hamburg" }, root)?.dataset.messageId).toBe("u-7");
    expect(findMessage({ seq: 99, turnId: "turn-3" }, root)?.dataset.messageId).toBe("turn-3");
    expect(findMessage({ seq: 99 }, root)).toBeNull();
  });
});

describe("jumpToMessage", () => {
  it("opens the conversation and marks the message", async () => {
    useHomeStore.setState({ agentChatId: "other" });
    useEventStore.setState({ activeSection: "memory" });
    conversation(`<p data-message-id="u-5">I work as a nurse.</p>`);
    const el = document.querySelector<HTMLElement>("[data-message-id='u-5']")!;
    el.scrollIntoView = vi.fn();
    await expect(jumpToMessage({ seq: 5 }, { navigate: true })).resolves.toBe(true);
    expect(useEventStore.getState().activeSection).toBe("chats");
    expect(useHomeStore.getState().agentChatId).toBeNull();
    expect(el.scrollIntoView).toHaveBeenCalled();
    expect(el.getAttribute("data-memory-source")).toBe("true");
  });

  it("gives up when the message is not on screen", async () => {
    await expect(jumpToMessage({ seq: 5 }, { timeoutMs: 0 })).resolves.toBe(false);
  });
});
