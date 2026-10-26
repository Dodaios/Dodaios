import { describe, expect, it } from "vitest";
import en from "@/i18n/locales/en.json";
import type { ReasoningBlock, TimelineItem, ToolBlock, TurnBlock, TurnItem, UserItem } from "../reduce";
import { announcementFor, openQuestionText, runSnapshot } from "./runAnnouncer";
import { stampLabel, stampPlan, STAMP_GAP_MS } from "./transcriptTime";
import { countUnseen } from "./TranscriptAids";
import { hasWork, workHeadKey, workSummary } from "./workSummary";

function t(key: string): string {
  let at: unknown = en;
  for (const part of key.split(".")) at = (at as Record<string, unknown>)?.[part];
  return typeof at === "string" ? at : key;
}

function turn(blocks: TurnBlock[], status: TurnItem["status"] = "done", id = "t1", startedMs = 1): TurnItem {
  return {
    type: "turn", id, provider: "p", model: "", effort: "", runner: "api", status, blocks,
    startedMs, durationMs: 4_000, usage: null, liveUsage: null, costUsd: null, error: null,
  };
}
function call(name: string, input: unknown = {}, output: string | null = "ok", extra: Partial<ToolBlock> = {}): ToolBlock {
  return { kind: "tool", callId: `c-${name}-${JSON.stringify(input).length}`, name, input, output, isError: false, durationMs: 10, approval: null, startedMs: 1, ...extra };
}
const thought: ReasoningBlock = { kind: "reasoning", id: "r1", text: "", durationMs: 900, live: false, startedMs: 1 };
const user = (id: string, tsMs: number): UserItem => ({ type: "user", id, text: "hi", attachments: [], tsMs });

describe("workSummary", () => {
  it("counts steps, helpers and changed files, without card polls or memory notes", () => {
    const blocks: TurnBlock[] = [
      thought,
      call("Read", { file_path: "a.ts" }),
      call("Edit", { file_path: "a.ts", old_string: "one\ntwo", new_string: "one\n2\nthree" }),
      call("Write", { file_path: "b.ts", content: "x\ny" }),
      call("society_wiki_note", { title: "Plan", body: "x" }, "{\"path\":\"society/a/x.md\",\"before\":\"\",\"after\":\"x\"}"),
      call("society_ask_user", { wait_for: "q1" }, "{\"status\":\"waiting\"}"),
      call("Task", { description: "Explore" }, "done"),
      call("Bash", { command: "false" }, "exit 1", { isError: true }),
    ];
    const summary = workSummary(blocks);
    expect(summary.steps).toBe(6);
    expect(summary.thoughts).toBe(1);
    expect(summary.helpers).toBe(1);
    expect(summary.files).toBe(2);
    expect(summary.added).toBe(4);
    expect(summary.removed).toBe(1);
    expect(summary.failed).toBe(1);
    expect(hasWork(summary)).toBe(true);
  });

  it("a plain reply has no work to show", () => {
    expect(hasWork(workSummary([{ kind: "text", id: "x", text: "Hello" }]))).toBe(false);
  });

  it("the line opens with how the turn ended", () => {
    expect(workHeadKey(turn([], "running"))).toBe("run_view.work.working");
    expect(workHeadKey(turn([], "cancelled"))).toBe("run_view.work.stopped_after");
    expect(workHeadKey(turn([], "error"))).toBe("run_view.work.failed_after");
    expect(workHeadKey(turn([]))).toBe("run_view.work.worked_for");
  });
});

describe("stampPlan", () => {
  const base = new Date(2026, 9, 26, 10, 0).getTime();
  it("stamps the first message, a 15-minute pause and a new day", () => {
    const plan = stampPlan([
      { id: "a", ts: base, author: "person" },
      { id: "b", ts: base + 60_000, author: "agent" },
      { id: "c", ts: base + 60_000 + STAMP_GAP_MS, author: "person" },
      { id: "d", ts: base + 60_000 + STAMP_GAP_MS + 1_000, author: "agent" },
      { id: "e", ts: new Date(2026, 9, 27, 8, 0).getTime(), author: "person" },
    ]);
    expect([...plan]).toEqual(["a", "c", "e"]);
  });

  it("never splits one speaker's run, and ignores entries without a time", () => {
    const plan = stampPlan([
      { id: "a", ts: base, author: "agent" },
      { id: "x", ts: 0, author: "notice" },
      { id: "b", ts: base + 2 * STAMP_GAP_MS, author: "agent" },
      { id: "c", ts: base + 2 * STAMP_GAP_MS + 1, author: "person" },
    ]);
    expect([...plan]).toEqual(["a"]);
  });

  it("says today, yesterday, a weekday date, then a full date", () => {
    const now = new Date(2026, 9, 26, 18, 0).getTime();
    expect(stampLabel(new Date(2026, 9, 26, 9, 5).getTime(), now, "en-GB", t)).toBe("Today 09:05");
    expect(stampLabel(new Date(2026, 9, 25, 9, 5).getTime(), now, "en-GB", t)).toBe("Yesterday 09:05");
    expect(stampLabel(new Date(2026, 2, 3, 9, 5).getTime(), now, "en-GB", t)).toMatch(/Tue.*3.*Mar.*09:05/);
    expect(stampLabel(new Date(2025, 2, 3, 9, 5).getTime(), now, "en-GB", t)).toMatch(/2025.*09:05/);
  });
});

describe("countUnseen", () => {
  it("counts only what the reader has not seen", () => {
    const items: TimelineItem[] = [user("u1", 1), turn([], "done", "t1"), user("u2", 2), turn([], "running", "t2")];
    expect(countUnseen(items, new Set(["u1", "t1"]))).toBe(2);
    expect(countUnseen(items, new Set(items.map((item) => item.id)))).toBe(0);
  });
});

describe("run announcer", () => {
  const question = call("society_ask_user", {}, null, {
    callId: "q", question: { questionId: "q1", asker: "", questions: [{ question: "Which branch?", options: [], recommendationReason: "" }],
      answers: [null], expiresMs: null, closed: false },
  });

  it("says started, asks, replied, stopped and failed, once per change", () => {
    const running = runSnapshot([turn([], "running")]);
    expect(announcementFor(null, running)?.key).toBe("run_view.announce.started");
    expect(announcementFor(running, running)).toBeNull();
    const asking = [turn([question], "running")];
    const snap = runSnapshot(asking);
    expect(announcementFor(running, snap, openQuestionText(asking, snap))).toEqual({ key: "run_view.announce.asked", detail: "Which branch?" });
    const replied = runSnapshot([turn([{ kind: "text", id: "x", text: "Done." }], "done")]);
    expect(announcementFor(running, replied)?.key).toBe("run_view.announce.replied");
    expect(announcementFor(running, runSnapshot([turn([], "done")]))?.key).toBe("run_view.announce.finished");
    expect(announcementFor(running, runSnapshot([turn([], "cancelled")]))?.key).toBe("run_view.announce.stopped");
    expect(announcementFor(running, runSnapshot([turn([], "error")]))?.key).toBe("run_view.announce.failed");
  });

  it("never reads out a turn that was already over when it first appeared", () => {
    const old = runSnapshot([turn([], "done", "t0")]);
    expect(announcementFor(old, runSnapshot([turn([], "done", "t9")]))).toBeNull();
  });

  it("an approval card is announced as needing an OK", () => {
    const running = runSnapshot([turn([], "running")]);
    const gate = call("Bash", { command: "rm x" }, null, { approval: { approvalId: "a1", summary: "", decision: null } });
    expect(announcementFor(running, runSnapshot([turn([gate], "running")]))?.key).toBe("run_view.announce.needs_ok");
  });
});
