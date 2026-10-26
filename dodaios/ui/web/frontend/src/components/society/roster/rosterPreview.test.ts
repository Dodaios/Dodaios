import { describe, expect, it } from "vitest";

import type { SocietyAgent } from "../data";
import { formatRelative, needsYou, previewText, relativeStamp, rosterPreview, rosterStatus, waitingReasonOf } from "./rosterPreview";

function agent(over: Partial<SocietyAgent> & Record<string, unknown> = {}): SocietyAgent {
  return {
    agentId: "a",
    name: "Scout",
    title: "Research scout",
    state: "idle",
    tier: "specialist",
    ...over,
  } as SocietyAgent;
}

const reason = { kind: "question", summary: "Which **folder** should I use?", session_id: "s1", ref_id: "q1" };

describe("rosterPreview priority", () => {
  it("puts the waiting reason above a draft and the last message", () => {
    const preview = rosterPreview({ agent: agent({ waiting_reason: reason }), draft: "half a thought", lastMessage: "Done." });
    expect(preview).toEqual({ kind: "waiting", text: "Which folder should I use?" });
  });

  it("falls back to the plain waiting state when the backend sends no reason", () => {
    expect(rosterPreview({ agent: agent({ state: "waiting" }), draft: "draft", lastMessage: "Done." })).toEqual({ kind: "waiting", text: "" });
  });

  it("shows the person's draft above the last message", () => {
    expect(rosterPreview({ agent: agent(), draft: "  check the   invoices ", lastMessage: "Done." })).toEqual({ kind: "draft", text: "check the invoices" });
  });

  it("shows the last message, then the role", () => {
    expect(rosterPreview({ agent: agent(), lastMessage: "All three reports are in." })).toEqual({ kind: "message", text: "All three reports are in." });
    expect(rosterPreview({ agent: agent() })).toEqual({ kind: "role", text: "Research scout" });
  });

  it("keeps the last message while the agent works; the corner mark shows the work", () => {
    expect(rosterPreview({ agent: agent({ state: "working" }), lastMessage: "On it." })).toEqual({ kind: "message", text: "On it." });
  });
});

describe("rosterStatus", () => {
  it("ranks needs-you over working over unread", () => {
    expect(rosterStatus(agent({ state: "working", waiting_reason: reason }), true)).toBe("needs-you");
    expect(rosterStatus(agent({ state: "waiting" }), true)).toBe("needs-you");
    expect(rosterStatus(agent({ state: "working" }), true)).toBe("working");
    expect(rosterStatus(agent(), true)).toBe("unread");
    expect(rosterStatus(agent({ state: "paused" }), false)).toBe("paused");
    expect(rosterStatus(agent(), false)).toBe("idle");
  });

  it("reads the waiting reason in either spelling and ignores unknown kinds", () => {
    expect(waitingReasonOf(agent({ waitingReason: { kind: "approval", summary: "Send the mail?", sessionId: "s" } })))
      .toEqual({ kind: "approval", summary: "Send the mail?", sessionId: "s" });
    expect(waitingReasonOf(agent({ waiting_reason: { kind: "something-else", summary: "x" } }))).toBeNull();
    expect(needsYou(agent({ waiting_reason: null }))).toBe(false);
  });
});

describe("previewText", () => {
  it("drops ask blocks, routing markers, code and markdown", () => {
    const raw = "Here is the **plan**.\n[to jarvis]\n```ts\nconst x = 1;\n```\nSee [the doc](https://example.test).\n```jarvis-ask\n{\"questions\": []}\n```";
    expect(previewText(raw)).toBe("Here is the plan . See the doc.");
  });

  it("keeps a line that merely starts with a link", () => {
    expect(previewText("[The report](https://example.test) is ready.")).toBe("The report is ready.");
  });

  it("caps long lines", () => {
    const text = previewText("word ".repeat(100));
    expect(text.length).toBeLessThanOrEqual(160);
    expect(text.endsWith("…")).toBe(true);
  });
});

describe("relative times", () => {
  const now = Date.UTC(2026, 9, 26, 12, 0, 0);
  it("buckets into now, minutes, hours, days and a date", () => {
    expect(relativeStamp(now - 20_000, now)).toEqual({ unit: "now" });
    expect(relativeStamp(now - 5 * 60_000, now)).toEqual({ unit: "minute", value: 5 });
    expect(relativeStamp(now - 3 * 3_600_000, now)).toEqual({ unit: "hour", value: 3 });
    expect(relativeStamp(now - 2 * 86_400_000, now)).toEqual({ unit: "day", value: 2 });
    expect(relativeStamp(now - 30 * 86_400_000, now).unit).toBe("date");
  });

  it("formats short, localised labels", () => {
    expect(formatRelative(now - 10_000, now, "en", "now")).toBe("now");
    expect(formatRelative(now - 5 * 60_000, now, "en", "now")).toMatch(/^5\s?m/);
    expect(formatRelative(now - 3 * 3_600_000, now, "en", "now")).toMatch(/^3\s?h/);
    expect(formatRelative(now - 40 * 86_400_000, now, "en", "now")).toMatch(/Sep/);
  });
});
