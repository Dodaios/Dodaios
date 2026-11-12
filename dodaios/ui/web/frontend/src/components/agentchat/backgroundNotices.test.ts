import { expect, it } from "vitest";
import { isBackgroundNotice, withoutBackgroundNotices } from "./backgroundNotices";
import type { TimelineItem } from "./reduce";

const notice = (id: string, kind: string, status = "", data: Record<string, unknown> = {}): TimelineItem => ({
  type: "notice", id, kind, text: "text", agentName: "Jarvis", agentId: "jarvis", status, tsMs: 1, data, resolved: "",
});
const user: TimelineItem = { type: "user", id: "u1", text: "Hello", attachments: [], tsMs: 1 };

it("treats learned memories and watchdog findings as background", () => {
  expect(isBackgroundNotice(notice("n1", "memory_learned", "done"))).toBe(true);
  expect(isBackgroundNotice(notice("n2", "watchdog", "done"))).toBe(true);
});

it("treats an unattended routine run that did not finish as background", () => {
  for (const status of ["failed", "skipped", "waiting", "blocked"]) {
    expect(isBackgroundNotice(notice("n1", "society_result", status, { source: "routine" }))).toBe(true);
  }
});

it("keeps a routine's finished result and a delegated task's outcome in the chat", () => {
  expect(isBackgroundNotice(notice("n1", "society_result", "done", { source: "routine" }))).toBe(false);
  expect(isBackgroundNotice(notice("n2", "society_result", "", { source: "routine" }))).toBe(false);
  // A task the assistant handed out for the person: its failure is part of the conversation.
  expect(isBackgroundNotice(notice("n3", "society_result", "blocked"))).toBe(false);
  expect(isBackgroundNotice(notice("n4", "reminder_due", "done"))).toBe(false);
  expect(isBackgroundNotice(user)).toBe(false);
});

it("drops the background notices and keeps the order of the rest", () => {
  const items = [
    user,
    notice("n1", "memory_learned", "done"),
    notice("n2", "society_result", "done", { source: "routine" }),
    notice("n3", "watchdog", "done"),
    notice("n4", "society_result", "failed", { source: "routine" }),
  ];
  expect(withoutBackgroundNotices(items).map((item) => item.id)).toEqual(["u1", "n2"]);
});

it("returns the same array when nothing is dropped", () => {
  const items = [user, notice("n1", "society_result", "done", { source: "routine" })];
  expect(withoutBackgroundNotices(items)).toBe(items);
});
