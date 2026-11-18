import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, test, vi } from "vitest";

vi.mock("@/lib/openExternal", () => ({ openExternalUrl: vi.fn(async () => true) }));

import { openExternalUrl } from "@/lib/openExternal";
import type { ReminderRow } from "@/lib/remindersApi";
import { useEventStore } from "@/store/events";

import type { NoticeItem, TimelineItem } from "../reduce";
import { dueNow, useDueRemindersStore } from "./dueReminders";
import { foldReminderNotices, noticeRow, ReminderDueMessage } from "./ReminderDueMessage";

/** The payload `dodaios/notify/reminders.py` posts: the item's fields plus its memory id. */
function told(id: string, fields: Record<string, unknown>): NoticeItem {
  return {
    type: "notice", id, kind: "reminder_due", text: "", agentName: "", agentId: "", status: "", tsMs: 1, resolved: "",
    data: { kind: "reminder_due", status: "", reminder: true, due_at: "2026-11-14T07:45:00Z", ...fields },
  };
}

const own = (id: string, memory: string, text: string) =>
  told(id, { memory_id: memory, text, title: text, source: "dodaios", start: "2026-11-14T07:45:00Z", end: null });

const appointment = (id: string, memory: string, title: string, extra: Record<string, unknown> = {}) => told(id, {
  memory_id: memory, reminder: false, source: "google_calendar", title, busy_only: false,
  text: `Appointment: ${title} on 2026-11-14 10:15–15:00.`, due_at: "2026-11-14T09:15:00Z",
  start: "2026-11-14T09:15:00Z", end: "2026-11-14T14:00:00Z", all_day: false, calendar: "", location: "",
  url: `https://www.google.com/calendar/event?eid=${memory}`, ...extra,
});

/** What `/api/notify/reminders` still lists as open. */
let open: ReminderRow[] = [];
let calls: string[] = [];

function row(id: string, extra: Partial<ReminderRow> = {}): ReminderRow {
  return { id, text: id, due_at: "2026-11-14T07:45:00Z", kind: "ephemeral", reminder: true, overdue: true, delivered: true, ...extra };
}

function backend(fail = false) {
  return vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    const json = (body: unknown) => new Response(JSON.stringify(body), { status: 200 });
    if (url.startsWith("/api/notify/reminders?")) return json({ items: open });
    const done = /^\/api\/notify\/reminders\/([^/]+)\/done$/.exec(url);
    if (done) {
      if (fail) return new Response("{}", { status: 500 });
      open = open.filter((r) => r.id !== decodeURIComponent(done[1]));
      return json({ ok: true });
    }
    const snoozed = /^\/api\/notify\/reminders\/([^/]+)\/snooze$/.exec(url);
    if (snoozed) {
      open = open.filter((r) => r.id !== decodeURIComponent(snoozed[1]));
      return json({ ...row("mem_new"), due_at: "2026-11-14T09:00:00Z", overdue: false, delivered: false });
    }
    return new Response("gone", { status: 404 });
  });
}

function show(item: TimelineItem) {
  return render(<ReminderDueMessage item={item as NoticeItem} />);
}

beforeEach(() => {
  open = [];
  calls = [];
  useDueRemindersStore.setState({ items: [], loaded: false });
  useEventStore.setState({ toasts: [] });
  vi.stubGlobal("fetch", backend());
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("ReminderDueMessage", () => {
  test("the assistant says the person's own reminder in the chat; Done ticks it off and says so", async () => {
    open = [row("mem_1")];
    show(own("n-1", "mem_1", "Call the dentist"));
    const message = screen.getByTestId("reminder-message");
    expect(message.dataset.messageId).toBe("n-1");
    expect(screen.getByTestId("reminder-words").textContent).toMatch(/^Call the dentist, .*\d:\d{2}/);
    fireEvent.click(await screen.findByTestId("reminder-done"));
    await waitFor(() => expect(screen.getByTestId("reminder-settled").textContent).toBe("Ticked off"));
    expect(calls).toContain("/api/notify/reminders/mem_1/done");
    expect(screen.queryByTestId("reminder-actions")).toBeNull();
  });

  test("Later shows the snooze choices; a snooze says when it comes back", async () => {
    open = [row("mem_2")];
    show(own("n-2", "mem_2", "Take the pizza out"));
    expect(screen.queryByTestId("reminder-snooze")).toBeNull();
    fireEvent.click(await screen.findByTestId("reminder-later"));
    expect(screen.getByRole("group", { name: "Remind me again:" })).toBeTruthy();
    fireEvent.click(screen.getAllByTestId("reminder-snooze")[0]);
    await waitFor(() => expect(screen.getByTestId("reminder-settled").textContent).toMatch(/^Snoozed until/));
    expect(calls).toContain("/api/notify/reminders/mem_2/snooze");
  });

  test("a failed Done keeps the buttons and says it went wrong", async () => {
    open = [row("mem_3")];
    vi.stubGlobal("fetch", backend(true));
    show(own("n-3", "mem_3", "Pay the rent"));
    fireEvent.click(await screen.findByTestId("reminder-done"));
    await waitFor(() => expect(useEventStore.getState().toasts.some((toast) => toast.kind === "error")).toBe(true));
    expect(screen.getByTestId("reminder-done")).toBeTruthy();
  });

  test("an item that is no longer open keeps its words and offers nothing", async () => {
    show(own("n-4", "mem_4", "Water the plants"));
    await waitFor(() => expect(useDueRemindersStore.getState().loaded).toBe(true));
    expect(screen.getByTestId("reminder-words").textContent).toMatch(/^Water the plants/);
    expect(screen.queryByTestId("reminder-actions")).toBeNull();
  });

  test("a calendar appointment names its calendar, its title, when and where; it opens there or is dismissed", async () => {
    open = [row("ev_1", { reminder: false })];
    show(appointment("n-5", "ev_1", "Dentist", { location: "Main St 1" }));
    const message = screen.getByTestId("reminder-message");
    expect(screen.getByTestId("reminder-words").textContent).toMatch(/^Dentist, .*\d:\d{2}.* · Main St 1\.$/);
    expect(message.textContent).not.toMatch(/Appointment:/);
    const open_ = await screen.findByTestId("reminder-open");
    expect(open_.textContent).toBe("Open in Google Calendar");
    // A meeting that started is opened or dismissed, never snoozed.
    expect(screen.queryByTestId("reminder-later")).toBeNull();
    fireEvent.click(open_);
    expect(openExternalUrl).toHaveBeenCalledWith("https://www.google.com/calendar/event?eid=ev_1");
    fireEvent.click(screen.getByTestId("reminder-dismiss"));
    await waitFor(() => expect(screen.getByTestId("reminder-settled").textContent).toBe("Dismissed"));
    expect(calls).toContain("/api/notify/reminders/ev_1/done");
  });

  test("an entry that only says busy says so", () => {
    show(appointment("n-6", "ev_2", "", { busy_only: true, calendar: "Team availability" }));
    expect(screen.getByTestId("reminder-words").textContent).toMatch(/^Busy \(no details shared\), .*Team availability\.$/);
  });

  test("several told in one go are one message, each item with its own actions under the words", async () => {
    open = [row("a1", { reminder: false }), row("a2", { reminder: false })];
    const [message] = foldReminderNotices([
      appointment("n-7", "a1", "Standup", { start: "2026-11-14T09:00:00Z", end: "2026-11-14T09:15:00Z" }),
      appointment("n-8", "a2", "Review", { start: "2026-11-14T09:05:00Z", end: "2026-11-14T10:00:00Z" }),
    ]);
    show(message);
    expect(screen.getAllByTestId("reminder-message")).toHaveLength(1);
    expect(screen.getByTestId("reminder-words").textContent).toMatch(/^Standup, .*\. Review, /);
    await waitFor(() => expect(screen.getAllByTestId("reminder-label").map((label) => label.textContent)).toEqual(["Standup", "Review"]));
    // A notification of the second item still finds its place.
    expect(document.querySelector('[data-message-id="n-8"]')).toBeTruthy();
    await waitFor(() => expect(screen.getAllByTestId("reminder-dismiss")).toHaveLength(2));
    fireEvent.click(screen.getAllByTestId("reminder-dismiss")[0]);
    await waitFor(() => expect(screen.getAllByTestId("reminder-dismiss")).toHaveLength(1));
  });

  test("the words the assistant wrote are the message; the actions stay under them", async () => {
    open = [row("a1", { reminder: false }), row("a2", { reminder: false })];
    const words = "Gleich ist Pause bis 10:45, danach hast du eine halbe Stunde für Mails.";  // i18n-allow
    const [message] = foldReminderNotices([
      appointment("n-10", "a1", "Pause", { voice: words, voice_by: "model" }),
      appointment("n-11", "a2", "Mails & Inbox", { voice_covered: true }),
    ]);
    show(message);
    expect(screen.getByTestId("reminder-words").textContent).toBe(words);
    expect(screen.getByTestId("reminder-message").textContent).not.toMatch(/From your|Appointment:/);
    await waitFor(() => expect(screen.getAllByTestId("reminder-dismiss")).toHaveLength(2));
  });

  test("an older notice with only its text still says it", () => {
    show(told("n-9", { text: "Buy milk", reminder: true }));
    expect(screen.getByTestId("reminder-message").textContent).toContain("Buy milk");
  });
});

describe("foldReminderNotices", () => {
  const user: TimelineItem = { type: "user", id: "u1", text: "Hi", attachments: [], tsMs: 1 };

  test("folds a run of reminders into its first and keeps everything else in place", () => {
    const items = [own("n1", "m1", "A"), own("n2", "m2", "B"), user, own("n3", "m3", "C")];
    const folded = foldReminderNotices(items);
    expect(folded.map((item) => item.id)).toEqual(["n1", "u1", "n3"]);
    expect(((folded[0] as NoticeItem).data.reminder_group as NoticeItem[]).map((item) => item.id)).toEqual(["n1", "n2"]);
  });

  test("a reminder with words of its own is a message of its own; one worded with the one before joins it", () => {
    const first = { ...own("n1", "m1", "A"), data: { ...own("n1", "m1", "A").data, voice: "Water the plants and call mum." } };
    const covered = { ...own("n2", "m2", "B"), data: { ...own("n2", "m2", "B").data, voice_covered: true } };
    const later = { ...own("n3", "m3", "C"), data: { ...own("n3", "m3", "C").data, voice: "Your lunch break starts now." } };
    const folded = foldReminderNotices([first, covered, later]);
    expect(folded.map((item) => item.id)).toEqual(["n1", "n3"]);
    expect(((folded[0] as NoticeItem).data.reminder_group as NoticeItem[]).map((item) => item.id)).toEqual(["n1", "n2"]);
  });

  test("returns the same array when there is nothing to fold", () => {
    const items = [own("n1", "m1", "A"), user];
    expect(foldReminderNotices(items)).toBe(items);
  });
});

describe("noticeRow", () => {
  test("a dated memory that is not from a calendar is the person's own, never an appointment", () => {
    // The scheduler's payload for a task memory with a due date: no reminder flag, Dodaios' own source.
    const task = told("n1", { memory_id: "m1", reminder: false, source: "dodaios", title: "Book the hotels", text: "Book the hotels" });
    expect(noticeRow(task)).toMatchObject({ reminder: true, source: "dodaios" });
    // An older notice without a source: only the calendar sync's wording makes it an appointment.
    const old = told("n2", { memory_id: "m2", reminder: false, text: "Plan the trip" });
    expect(noticeRow(old)).toMatchObject({ reminder: true, source: "dodaios" });
    const oldAppointment = told("n3", { memory_id: "m3", reminder: false, text: "Appointment: Dentist on 2026-11-14 10:15." });
    expect(noticeRow(oldAppointment)).toMatchObject({ reminder: false, source: undefined });
  });

  test("such an item reads as the person's own reminder in the chat", () => {
    show(told("n4", { memory_id: "m4", reminder: false, source: "dodaios", title: "Book the hotels", text: "Book the hotels" }));
    expect(screen.getByTestId("reminder-words").textContent).toMatch(/^Book the hotels/);
    expect(screen.getByTestId("reminder-message").textContent).not.toMatch(/Calendar/);
  });

  test("reads the item's fields from the notice", () => {
    expect(noticeRow(appointment("n1", "ev_9", "Dentist"))).toMatchObject({
      id: "ev_9", reminder: false, source: "google_calendar", title: "Dentist", start: "2026-11-14T09:15:00Z",
    });
  });
});

describe("dueNow", () => {
  test("keeps only what is past its time and already told", () => {
    const rows = [row("a"), row("b", { delivered: false }), row("c", { overdue: false })];
    expect(dueNow(rows).map((r) => r.id)).toEqual(["a"]);
  });
});
