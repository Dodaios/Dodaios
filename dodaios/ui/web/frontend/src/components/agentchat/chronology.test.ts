import { describe, expect, it } from "vitest";

import type { AgentChatEvent } from "@/lib/agentChatApi";
import { chronological, typingRow, type ChatRow } from "./chronology";
import { EMPTY_TIMELINE, reduceEvents, type TimelineItem } from "./reduce";

let seq = 0;
/** An event at second `at` of the conversation. */
function ev(at: number, kind: string, payload: Record<string, unknown>): AgentChatEvent {
  return { seq: ++seq, ts_ms: 1_000_000 + at * 1000, kind, payload } as AgentChatEvent;
}
const items = (...events: AgentChatEvent[]) => reduceEvents(EMPTY_TIMELINE, events).items;
const said = (at: number, turn: string, id: string, text: string) =>
  ev(at, "assistant_text", { turn_id: turn, message_id: id, text });

/** What each row shows, in the order it is drawn. */
function read(rows: ChatRow[]): string[] {
  return rows.map((row) => {
    if (row.kind === "turn_part") return `said: ${row.part.blocks.map((block) => block.text).join(" | ")}`;
    if (row.kind === "side_message") return `me: ${row.item.text}`;
    if (row.kind === "side_answer") {
      const part = row.part;
      const texts = "live" in part
        ? part.closing
          ? part.live.flatMap((entry) => entry.type === "turn" ? entry.blocks.flatMap((block) => block.kind === "text" ? [block.text] : []) : [])
          : part.texts.map((block) => block.text)
        : part.messages;
      return `beside${part.closing ? "" : " (earlier)"}: ${texts.join(" | ") || "…"}`;
    }
    const item = row.item;
    if (item.type === "user") return `me: ${item.text}`;
    if (item.type === "turn") {
      const texts = item.blocks.filter((block) => block.kind === "text").map((block) => block.kind === "text" ? block.text : "");
      return `turn(${item.status}): ${texts.join(" | ")}`;
    }
    return item.type;
  });
}

describe("the conversation in the order a messenger shows it", () => {
  it("leaves a conversation without overlap exactly as it is", () => {
    const base = items(
      ev(0, "user_message", { text: "Hello" }),
      ev(1, "turn_started", { turn_id: "t1" }),
      said(2, "t1", "m1", "Hi."),
      ev(3, "turn_finished", { turn_id: "t1", status: "done" }),
      ev(10, "user_message", { text: "And now?" }),
    );
    const rows = chronological(base);
    expect(read(rows)).toEqual(["me: Hello", "turn(done): Hi.", "me: And now?"]);
    // The turn is the timeline's own object: nothing about it is rebuilt.
    expect((rows[1] as { item: TimelineItem }).item).toBe(base[1]);
    expect(typingRow(rows)).toBeNull();
  });

  it("puts what a turn says after the person's next message below that message", () => {
    // The complaint (maintainer, 2026-11-12): the turn kept writing ABOVE
    // the message sent meanwhile, so the newest words were never at the bottom.
    const rows = chronological(items(
      ev(0, "user_message", { text: "Review the five pull requests" }),
      ev(1, "turn_started", { turn_id: "t1" }),
      said(2, "t1", "m1", "The agent is on it."),
      ev(10, "notice", { kind: "side_thread_started", side_id: "s1", text: "And the weather?" }),
      ev(14, "notice", { kind: "side_thread_finished", side_id: "s1", status: "done", text: "And the weather?", answer: "Sunny." }),
      said(20, "t1", "m2", "Still running."),
      said(30, "t1", "m3", "All five are fine."),
      ev(31, "turn_finished", { turn_id: "t1", status: "done" }),
    ));
    expect(read(rows)).toEqual([
      "me: Review the five pull requests",
      "said: The agent is on it.",
      "me: And the weather?",
      "beside: Sunny.",
      "turn(done): Still running. | All five are fine.",
    ]);
  });

  it("keeps a working turn's dots at the very bottom, below an answer still being written beside it", () => {
    const rows = chronological(items(
      ev(0, "user_message", { text: "Research desks" }),
      ev(1, "turn_started", { turn_id: "t1" }),
      said(2, "t1", "m1", "On it."),
      ev(10, "notice", { kind: "side_thread_started", side_id: "s1", text: "Capital of Peru?" }),
      said(12, "t1", "m2", "Found three so far."),
    ));
    expect(read(rows)).toEqual([
      "me: Research desks",
      "said: On it.",
      "me: Capital of Peru?",
      "said: Found three so far.",
      "beside: …",
      "turn(running): ",
    ]);
    // One place types: the working turn, last in the chat.
    expect(typingRow(rows)).toBe(rows[5].id);
  });

  it("lets the side thread type once the turn above is done, and places its answer where it arrived", () => {
    const open = [
      ev(0, "user_message", { text: "Research desks" }),
      ev(1, "turn_started", { turn_id: "t1" }),
      ev(10, "notice", { kind: "side_thread_started", side_id: "s1", text: "Capital of Peru?" }),
      said(12, "t1", "m1", "Here are three desks."),
      ev(13, "turn_finished", { turn_id: "t1", status: "done" }),
    ];
    const running = chronological(items(...open));
    expect(read(running)).toEqual(["me: Research desks", "me: Capital of Peru?", "turn(done): Here are three desks.", "beside: …"]);
    expect(typingRow(running)).toBe(running[3].id);

    const answered = chronological(items(...open,
      ev(20, "notice", { kind: "side_thread_finished", side_id: "s1", status: "done", text: "Capital of Peru?", answer: "Lima." })));
    expect(read(answered)).toEqual(["me: Research desks", "me: Capital of Peru?", "turn(done): Here are three desks.", "beside: Lima."]);
    expect(typingRow(answered)).toBeNull();
  });

  it("lets the side thread type while the turn below only waits for an agent", () => {
    const rows = chronological(items(
      ev(0, "user_message", { text: "Review the pull requests" }),
      ev(1, "turn_started", { turn_id: "t1" }),
      said(2, "t1", "m1", "An agent is on it."),
      ev(3, "background_wait", { turn_id: "t1", tasks: ["review"] }),
      ev(10, "notice", { kind: "side_thread_started", side_id: "s1", text: "Capital of Peru?" }),
    ));
    expect(read(rows).slice(-2)).toEqual(["beside: …", "turn(running): "]);
    expect(typingRow(rows)).toBe(rows[rows.length - 2].id);
  });

  it("never moves an item above an earlier one, whatever their clocks say", () => {
    // An imported turn carries an old time: it stays where the timeline has it.
    const rows = chronological(items(
      ev(100, "user_message", { text: "first" }),
      ev(5, "user_message", { text: "second, with an older clock" }),
      ev(101, "turn_started", { turn_id: "t1" }),
      said(102, "t1", "m1", "Answer."),
      ev(103, "turn_finished", { turn_id: "t1", status: "done" }),
    ));
    expect(read(rows)).toEqual(["me: first", "me: second, with an older clock", "turn(done): Answer."]);
  });

  describe("a side thread's answer, one message at a time", () => {
    // The complaint (maintainer, 2026-11-13): with two messages answered at
    // once, the main turn's new messages appeared ABOVE the side thread's
    // answer that was already on screen, and the side thread's first message
    // jumped below them when it ended. Every new message comes out at the
    // very bottom.
    const main = [
      ev(0, "user_message", { text: "Send that to the agent" }),
      ev(1, "turn_started", { turn_id: "t1" }),
      ev(30, "notice", { kind: "side_thread_started", side_id: "s1", text: "And the other PRs?" }),
      said(40, "t1", "m1", "The agent is busy."),
      said(44, "t1", "m2", "Not delivered yet."),
    ];
    // The side thread's own session, as its store reads it.
    const sideSession = (...more: AgentChatEvent[]) => items(
      ev(30, "user_message", { text: "And the other PRs?" }),
      ev(30, "turn_started", { turn_id: "s-t1" }),
      said(36, "s-t1", "s-m1", "Looking at the other PRs."),
      ...more,
    ).filter((item) => item.type !== "user");

    it("puts each message of both answers where it was written while both run", () => {
      const rows = chronological(items(...main), new Map([["s1", sideSession()]]));
      expect(read(rows)).toEqual([
        "me: Send that to the agent",
        "me: And the other PRs?",
        "beside (earlier): Looking at the other PRs.",
        "said: The agent is busy. | Not delivered yet.",
        // Still at work: its rest waits at the bottom, above the main turn's dots.
        "beside: …",
        "turn(running): ",
      ]);
      // The dots belong to the lowest row still being written, never to an earlier part.
      expect(typingRow(rows)).toBe(rows[5].id);
    });

    it("keeps the side thread's first message where it was when both have ended", () => {
      const done = [
        ...main,
        said(54, "t1", "m3", "Checked again."),
        ev(54, "turn_finished", { turn_id: "t1", status: "done" }),
        ev(59, "notice", {
          kind: "side_thread_finished", side_id: "s1", status: "done", text: "And the other PRs?",
          answer: "Seven PRs.", messages: ["Looking at the other PRs.", "Seven PRs."],
          message_times: [1_036_000, 1_059_000],
        }),
      ];
      const expected = [
        "me: Send that to the agent",
        "me: And the other PRs?",
        "beside (earlier): Looking at the other PRs.",
        "turn(done): The agent is busy. | Not delivered yet. | Checked again.",
        "beside: Seven PRs.",
      ];
      // Watched while it ran, and read again from the notice after a reload: the same order.
      const watched = chronological(items(...done), new Map([["s1", sideSession(
        said(59, "s-t1", "s-m2", "Seven PRs."), ev(59, "turn_finished", { turn_id: "s-t1", status: "done" }),
      )]]));
      expect(read(watched)).toEqual(expected);
      expect(read(chronological(items(...done)))).toEqual(expected);
      expect(typingRow(watched)).toBeNull();
    });

    it("keeps a notice without message times in one piece where the answer arrived", () => {
      const rows = chronological(items(
        ...main,
        ev(54, "turn_finished", { turn_id: "t1", status: "done" }),
        ev(59, "notice", {
          kind: "side_thread_finished", side_id: "s1", status: "done", text: "And the other PRs?",
          answer: "Seven PRs.", messages: ["Looking at the other PRs.", "Seven PRs."],
        }),
      ));
      expect(read(rows).slice(-2)).toEqual([
        "turn(done): The agent is busy. | Not delivered yet.",
        "beside: Looking at the other PRs. | Seven PRs.",
      ]);
    });
  });
});
