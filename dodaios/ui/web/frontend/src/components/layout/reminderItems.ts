import { fill } from "@/i18n";
import type { ReminderRow } from "@/lib/remindersApi";

/**
 * What the rail says about a reminder that has come due, in words a person
 * reads at a glance: whose it is (Google Calendar, Dodaios itself), what it is
 * called, and when it runs, on the person's clock and in their language.
 *
 * Two kinds stand on the rail. An appointment from a calendar runs from its
 * start to its end and leaves the rail once it is over; it can be opened in
 * its calendar or dismissed, never snoozed (a meeting that already started
 * does not come back later). A reminder the person asked Dodaios for is ticked
 * off or snoozed.
 *
 * A calendar entry that only says "busy" (a calendar shared as free/busy, a
 * published availability) has no name to show: the rail says so instead of
 * presenting "Busy" as its title (`busy_only`, set by the calendar sync).
 */

/** The person's own reminders: Dodaios' mark on the rail. */
export const OWN_SOURCE = "dodaios";
/** Where an appointment comes from when an older backend does not say: the one calendar it syncs. */
export const CALENDAR_SOURCE = "google_calendar";

type Translate = (key: string) => string;

/** One reminder on the rail, with the ids of the same item seen twice (one appointment on two calendars). */
export interface ReminderItem {
  key: string;
  row: ReminderRow;
  ids: string[];
  source: string;
  appointment: boolean;
}

/** Brand names of the services a reminder can come from; Google's own calendar has a name per language. */
const SOURCE_NAMES: Record<string, string> = {
  outlook: "Outlook",
  outlook_calendar: "Outlook",
  microsoft_todo: "Microsoft To Do",
  todoist: "Todoist",
  gmail: "Gmail",
  apple_calendar: "Apple Calendar",
  apple_reminders: "Apple Reminders",
  cal_com: "Cal.com",
  notion: "Notion",
  linear: "Linear",
  asana: "Asana",
  clickup: "ClickUp",
  slack: "Slack",
};
/** Sources whose name the UI translates. */
const TRANSLATED_SOURCES = new Set([OWN_SOURCE, CALENDAR_SOURCE]);

/** An appointment memory written before the backend sent its title ("Appointment: Dentist on 2026-11-12 09:00."). */
const OLD_APPOINTMENT = /^Appointment:\s*(.*?)\s+on\s+\d{4}-\d{2}-\d{2}/;

export function reminderSource(row: ReminderRow): string {
  return row.source || (row.reminder ? OWN_SOURCE : CALENDAR_SOURCE);
}

/** The service's name as the card's first line: "Google Calendar", "Todoist"; the own ones read "Reminder". */
export function sourceName(source: string, t: Translate): string {
  if (TRANSLATED_SOURCES.has(source)) return t(`reminders.source_${source}`);
  return SOURCE_NAMES[source] ?? source.split(/[_-]+/).filter(Boolean).map((word) => word[0].toUpperCase() + word.slice(1)).join(" ");
}

/** What the item is called: its own title, or that the calendar shares no more than "busy". */
export function itemTitle(row: ReminderRow, t: Translate): string {
  if (row.busy_only) return t("reminders.busy_title");
  const title = (row.title ?? "").trim();
  if (title) return title;
  if (row.title === "" && !row.reminder) return t("reminders.untitled");
  const old = OLD_APPOINTMENT.exec(row.text);
  return old ? old[1] : row.text;
}

function moment(value: string | null | undefined): Date | null {
  if (!value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** A whole day's date ("2026-11-18") as local midnight; also takes an older backend's UTC midnight. */
function localDay(value: string | null | undefined): Date | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value ?? "");
  return match ? new Date(Number(match[1]), Number(match[2]) - 1, Number(match[3])) : null;
}

const DAY_MS = 86_400_000;

function startOfDay(date: Date): number {
  return new Date(date.getFullYear(), date.getMonth(), date.getDate()).getTime();
}

/** "Today", "Tomorrow", "Yesterday" in the UI's language, else a short date ("Sat, Nov 14"). */
export function dayLabel(date: Date, locale: string, now: Date = new Date()): string {
  const days = Math.round((startOfDay(date) - startOfDay(now)) / DAY_MS);
  if (Math.abs(days) <= 1) {
    try {
      const word = new Intl.RelativeTimeFormat(locale, { numeric: "auto" }).format(days, "day");
      return word.charAt(0).toLocaleUpperCase(locale) + word.slice(1);
    } catch {
      // An engine without relative words falls through to the date.
    }
  }
  return date.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" });
}

function clock(date: Date, locale: string): string {
  return date.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

/** "10:15–15:00 Uhr", "10:15 AM – 3:00 PM": the locale's own way to write a span of one day. */
function clockRange(start: Date, end: Date, locale: string): string {
  try {
    return new Intl.DateTimeFormat(locale, { hour: "numeric", minute: "2-digit" }).formatRange(start, end);
  } catch {
    return `${clock(start, locale)} – ${clock(end, locale)}`;
  }
}

/**
 * When the item runs, on the person's clock: "Today, 10:15–15:00", "Tomorrow,
 * all day", "Yesterday, 18:00" for a reminder that was due then.
 */
export function itemWhen(row: ReminderRow, locale: string, t: Translate, now: Date = new Date()): string {
  const appointment = !row.reminder;
  if (appointment && row.all_day) {
    const first = localDay(row.start ?? row.due_at);
    if (!first) return "";
    const after = localDay(row.end);
    // The calendar's end date of a whole-day entry is the day after it.
    const last = after ? new Date(after.getTime() - DAY_MS) : first;
    if (startOfDay(last) > startOfDay(first)) return `${dayLabel(first, locale, now)} – ${dayLabel(last, locale, now)}`;
    return fill(t("reminders.all_day_on"), { day: dayLabel(first, locale, now) });
  }
  const start = moment(appointment ? row.start ?? row.due_at : row.due_at);
  if (!start) return "";
  const day = dayLabel(start, locale, now);
  const end = appointment ? moment(row.end) : null;
  if (!end || end.getTime() <= start.getTime()) return fill(t("reminders.day_time"), { day, time: clock(start, locale) });
  if (startOfDay(end) === startOfDay(start)) return fill(t("reminders.day_time"), { day, time: clockRange(start, end, locale) });
  return `${fill(t("reminders.day_time"), { day, time: clock(start, locale) })} – ${fill(t("reminders.day_time"), {
    day: dayLabel(end, locale, now), time: clock(end, locale),
  })}`;
}

/** Where the item is: its place, else the calendar it comes from (the primary one has no name here). */
export function itemPlace(row: ReminderRow): string {
  return (row.location ?? "").trim() || (row.calendar ?? "").trim();
}

/** When and where in one line, for a label or a list row. */
export function itemDetail(row: ReminderRow, locale: string, t: Translate, now: Date = new Date()): string {
  return [itemWhen(row, locale, t, now), itemPlace(row)].filter(Boolean).join(" · ");
}

/** The same item twice is one: one appointment seen on two calendars, or a duplicate an older sync left. */
function itemKey(row: ReminderRow, source: string): string {
  const startMs = moment(row.start ?? row.due_at)?.getTime() ?? row.due_at;
  const endMs = moment(row.end)?.getTime() ?? "";
  const name = row.busy_only ? "\u0000busy" : (row.title ?? row.text).trim().toLowerCase();
  return [source, row.reminder ? "r" : "a", name, startMs, endMs].join("|");
}

/** The due rows as rail items, oldest first, with duplicates folded into one. */
export function reminderItems(rows: ReminderRow[]): ReminderItem[] {
  const items = new Map<string, ReminderItem>();
  for (const row of rows) {
    if (!row.id || !(row.text || row.title || row.busy_only)) continue;
    const source = reminderSource(row);
    const key = itemKey(row, source);
    const same = items.get(key);
    if (same) same.ids.push(row.id);
    else items.set(key, { key, row, ids: [row.id], source, appointment: !row.reminder });
  }
  return [...items.values()];
}
