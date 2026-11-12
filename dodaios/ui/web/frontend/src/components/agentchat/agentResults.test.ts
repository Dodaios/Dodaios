import { describe, expect, it } from "vitest";
import { agentResultLabel, withoutAnsweredResults } from "./agentResults";
import { EMPTY_TIMELINE, reduceEvents, type NoticeItem, type TimelineItem } from "./reduce";
import type { AgentChatEvent } from "@/lib/agentChatApi";

let seq = 0;
const ev = (kind: string, tsMs: number, payload: Record<string, unknown> = {}): AgentChatEvent => ({
  seq: ++seq, ts_ms: tsMs, kind, payload,
});
const result = (tsMs: number, extra: Record<string, unknown> = {}) => ev("notice", tsMs, {
  kind: "coding_result", agent_name: "Claude Code", assignment_id: "a1", status: "completed",
  text: "Claude Code has finished: # Review of the five pull requests. None of them can be merged as",
  report: "{\"request\":\"Review the pull requests\",\"report\":\"# Review\"}", thread_id: "t1", ...extra,
});
const report = (tsMs: number) => ev("notice", tsMs, { kind: "report", text: "Review, 12 November", summary: "None can be merged." });
const shown = (events: AgentChatEvent[]): TimelineItem[] =>
  withoutAnsweredResults(reduceEvents(EMPTY_TIMELINE, events).items);
const kinds = (items: TimelineItem[]) => items.map((item) =>
  item.type === "notice" ? item.kind : item.type === "user" ? `user:${item.origin ?? "person"}` : item.type);

describe("a delegated agent's result in the assistant's chat", () => {
  it("is not drawn when it arrives while the assistant's turn is still working", () => {
    const waiting = [
      ev("user_message", 1_000, { text: "Review the five pull requests" }),
      ev("turn_started", 1_010, { turn_id: "T" }),
      ev("assistant_text", 2_000, { turn_id: "T", message_id: "m1", text: "The agent is on it." }),
      result(60_000),
    ];
    expect(kinds(shown(waiting))).toEqual(["user:person", "turn"]);
    // The turn goes on with the result: its answer, then the report card it wrote.
    const answered = shown([
      ...waiting,
      report(70_000),
      ev("assistant_text", 71_000, { turn_id: "T", message_id: "m2", text: "None of the five can be merged yet." }),
      ev("turn_finished", 72_000, { turn_id: "T", status: "done", duration_ms: 70_990 }),
    ]);
    expect(kinds(answered)).toEqual(["user:person", "turn", "report"]);
  });

  it("is not drawn when its request comes back in a turn of its own", () => {
    const parked = [
      ev("user_message", 1_000, { text: "Review the five pull requests" }),
      ev("turn_started", 1_010, { turn_id: "T1" }),
      ev("turn_finished", 5_000, { turn_id: "T1", status: "done", duration_ms: 3_990 }),
      ev("user_message", 6_000, { text: "And what is the weather?" }),
      ev("turn_started", 6_010, { turn_id: "T2" }),
      ev("turn_finished", 9_000, { turn_id: "T2", status: "done", duration_ms: 2_990 }),
      result(60_000),
    ];
    // Until the result's own turn starts, one line says the agent is done.
    expect(kinds(shown(parked)).at(-1)).toBe("coding_result");
    const continued = shown([
      ...parked,
      ev("user_message", 62_000, { text: "Review the five pull requests", origin: "background" }),
      ev("turn_started", 62_010, { turn_id: "T3" }),
    ]);
    expect(kinds(continued)).toEqual(["user:person", "turn", "user:person", "turn", "user:background", "turn"]);
  });

  it("is not drawn when it lands between the result message and that message's turn", () => {
    const items = shown([
      ev("user_message", 62_000, { text: "Review the five pull requests", origin: "background" }),
      result(62_005),
      ev("turn_started", 62_010, { turn_id: "T3" }),
    ]);
    expect(kinds(items)).toEqual(["user:background", "turn"]);
  });

  it("stays as one line when no turn takes it up", () => {
    const idle = [
      ev("user_message", 1_000, { text: "Review the five pull requests" }),
      ev("turn_started", 1_010, { turn_id: "T1" }),
      ev("turn_finished", 5_000, { turn_id: "T1", status: "cancelled", duration_ms: 3_990 }),
      result(60_000),
    ];
    expect(kinds(shown(idle))).toEqual(["user:person", "turn", "coding_result"]);
    // The person's next message is about something else: the line stays.
    const later = shown([
      ...idle,
      ev("user_message", 90_000, { text: "And what is the weather?" }),
      ev("turn_started", 90_010, { turn_id: "T2" }),
      ev("turn_finished", 95_000, { turn_id: "T2", status: "done", duration_ms: 4_990 }),
    ]);
    expect(kinds(later)).toEqual(["user:person", "turn", "coding_result", "user:person", "turn"]);
    // A later request's result does not take an older, unanswered one with it.
    const unrelated = shown([
      ...idle,
      ev("user_message", 90_000, { text: "And what is the weather?" }),
      ev("turn_started", 90_010, { turn_id: "T2" }),
      ev("turn_finished", 95_000, { turn_id: "T2", status: "done", duration_ms: 4_990 }),
      ev("user_message", 99_000, { text: "Fix the build", origin: "background" }),
    ]);
    expect(kinds(unrelated).filter((kind) => kind === "coding_result")).toHaveLength(1);
  });

  it("returns the same array when it drops nothing", () => {
    const none = reduceEvents(EMPTY_TIMELINE, [ev("user_message", 1_000, { text: "Hello" })]).items;
    expect(withoutAnsweredResults(none)).toBe(none);
    const kept = reduceEvents(EMPTY_TIMELINE, [result(1_000)]).items;
    expect(withoutAnsweredResults(kept)).toBe(kept);
  });

  it("words the line by how the agent's turn ended, without the report", () => {
    const t = (key: string) => ({
      "society.chat.agent_result_completed": "{0} is finished",
      "society.chat.agent_result_failed": "{0} failed",
      "society.chat.agent_result_other": "{0} has reported",
      "agent_attention.fallback_agent": "An agent",
    } as Record<string, string>)[key] ?? key;
    const line = (status: string, agentName = "Claude Code") =>
      agentResultLabel(t, { ...(reduceEvents(EMPTY_TIMELINE, [result(1, { status, agent_name: agentName })]).items[0] as NoticeItem) });
    expect(line("completed")).toBe("Claude Code is finished");
    expect(line("failed")).toBe("Claude Code failed");
    expect(line("done")).toBe("Claude Code has reported");
    expect(line("completed", "")).toBe("An agent is finished");
  });
});
