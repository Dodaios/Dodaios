import { expect, it } from "vitest";

import { groupBackgroundRuns, isQuietBackground, type BackgroundRunItem } from "./backgroundLine";
import type { InternalRunItem } from "./InternalMessageRun";
import type { NoticeItem, TimelineItem } from "./reduce";

function notice(id: string, tsMs: number, kind = "routine_run", extra: Partial<NoticeItem> = {}): NoticeItem {
  return { type: "notice", id, tsMs, kind, text: `Text ${id}`, agentName: "", agentId: "", status: "", data: {}, resolved: "", ...extra };
}

const user = { type: "user", id: "u1", tsMs: 5_000, text: "hi", attachments: [] } as unknown as TimelineItem;
const MINUTE = 60_000;

it("folds back-to-back background notices into one run named after its first notice", () => {
  const rows = groupBackgroundRuns([
    notice("a", 1_000),
    notice("b", 1_000 + 5 * MINUTE, "memory_updated"),
    notice("c", 1_000 + 19 * MINUTE, "learned_skill"),
  ]);
  expect(rows).toHaveLength(1);
  const run = rows[0] as BackgroundRunItem;
  expect(run.type).toBe("background_run");
  // The first notice's own id: the timeline keys its time stamps by item id.
  expect(run.id).toBe("a");
  expect(run.items.map((item) => item.id)).toEqual(["a", "b", "c"]);
});

it("starts a new run after a pause of 20 minutes or after any other item", () => {
  const rows = groupBackgroundRuns([
    notice("a", 1_000),
    notice("b", 1_000 + 20 * MINUTE),
    user,
    notice("c", 1_000 + 21 * MINUTE),
  ]);
  expect(rows.map((row) => row.type)).toEqual(["background_run", "background_run", "user", "background_run"]);
  expect(rows.map((row) => row.id)).toEqual(["a", "b", "u1", "c"]);
});

it("leaves notices the timeline draws in their own way, and a routine's result, where they are", () => {
  const result = notice("r", 3_000, "society_result", { status: "done", data: { source: "routine" } });
  const reminder = notice("d", 2_000, "reminder_due");
  const rows = groupBackgroundRuns([notice("a", 1_000), reminder, notice("b", 2_500), result, notice("c", 4_000)]);
  expect(rows.map((row) => row.type)).toEqual(["background_run", "notice", "background_run", "notice", "background_run"]);
  expect(rows[1]).toBe(reminder);
  expect(rows[3]).toBe(result);
});

it("counts a routine that failed, and another agent's report, as background", () => {
  expect(isQuietBackground(notice("f", 1, "society_result", { status: "failed", data: { source: "routine" } }))).toBe(true);
  expect(isQuietBackground(notice("s", 1, "society_result", { status: "done", agentName: "Scout" }))).toBe(true);
  expect(isQuietBackground(notice("q", 1, "message_queued"))).toBe(false);
  expect(isQuietBackground(user)).toBe(false);
});

it("passes agent-to-agent runs through untouched and in order", () => {
  const internal: InternalRunItem = { type: "internal_run", id: "i1", items: [] };
  const rows = groupBackgroundRuns([notice("a", 1_000), internal, notice("b", 1_500)]);
  expect(rows.map((row) => row.type)).toEqual(["background_run", "internal_run", "background_run"]);
  expect(rows[1]).toBe(internal);
});
