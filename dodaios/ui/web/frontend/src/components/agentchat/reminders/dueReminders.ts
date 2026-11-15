import { create } from "zustand";

import { listReminders, type ReminderRow } from "@/lib/remindersApi";

/**
 * The reminders that have come due and are still open.
 *
 * The scheduler (`dodaios/notify/reminders.py`) tells a reminder once, at its
 * time, as the assistant's message in the chat (`ReminderDueMessage`). That
 * message offers what fits the item (Done, Later, Open, Dismiss) only while
 * the item is still open here: once it is ticked off, snoozed, or over by
 * itself (a reminder a week after its time, an appointment once it ended),
 * the message stays as what was said and its buttons go.
 *
 * Only what the scheduler has already told counts (`delivered`).
 */

interface DueRemindersState {
  items: ReminderRow[];
  /** The first read answered: before it, nothing is known to be open. */
  loaded: boolean;
}

export const useDueRemindersStore = create<DueRemindersState>(() => ({ items: [], loaded: false }));

/** The scheduler looks every 30 s; reading as often keeps the buttons within a minute of the truth. */
export const DUE_REMINDERS_POLL_MS = 30_000;

/** What of the API's list is due now: past its time and already told. */
export function dueNow(rows: ReminderRow[]): ReminderRow[] {
  return rows.filter((row) => row.overdue && row.delivered);
}

let inflight: Promise<void> | null = null;

/** Read the due reminders, one request at a time. A failed read keeps the last good list. */
export function refreshDueReminders(): Promise<void> {
  if (inflight) return inflight;
  inflight = (async () => {
    try {
      // One day ahead is the smallest window the API takes; the overdue ones come first in it.
      const { items } = await listReminders(1);
      useDueRemindersStore.setState({ items: dueNow(items ?? []), loaded: true });
    } catch {
      // The next read tries again; the chat keeps what it showed.
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Take a reminder out of the open ones at once (ticked off or snoozed); the next read confirms it. */
export function dropDueReminder(id: string): void {
  useDueRemindersStore.setState((state) => ({ items: state.items.filter((row) => row.id !== id) }));
}

let watchers = 0;
let stopWatching: (() => void) | null = null;

function startWatching(): () => void {
  const refresh = () => {
    if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
    void refreshDueReminders();
  };
  refresh();
  const timer = window.setInterval(refresh, DUE_REMINDERS_POLL_MS);
  window.addEventListener("focus", refresh);
  document.addEventListener("visibilitychange", refresh);
  return () => {
    window.clearInterval(timer);
    window.removeEventListener("focus", refresh);
    document.removeEventListener("visibilitychange", refresh);
  };
}

/**
 * Keep the list fresh while the window is in sight; returns the stop function.
 * Every reminder message in the chat asks for it, and they share one reading.
 */
export function watchDueReminders(): () => void {
  watchers += 1;
  if (watchers === 1) stopWatching = startWatching();
  let stopped = false;
  return () => {
    if (stopped) return;
    stopped = true;
    watchers -= 1;
    if (watchers === 0) {
      stopWatching?.();
      stopWatching = null;
    }
  };
}

/** When a reminder was due, short: the time today, else the day and the time. */
export function formatDue(dueAt: string | null, locale: string, now: Date = new Date()): string {
  if (!dueAt) return "";
  const date = new Date(dueAt);
  if (Number.isNaN(date.getTime())) return dueAt;
  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  return `${date.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" })} ${time}`;
}
