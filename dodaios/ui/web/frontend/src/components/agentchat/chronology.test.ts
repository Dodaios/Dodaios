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
    if (row.kind === "side_answer") return `beside: ${String(row.item.data.answer ?? "…")}`;
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
});
