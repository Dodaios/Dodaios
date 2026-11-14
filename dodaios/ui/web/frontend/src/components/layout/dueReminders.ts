import { create } from "zustand";

import { listReminders, type ReminderRow } from "@/lib/remindersApi";

/**
 * The reminders that have come due and are still open, for the rail.
 *
 * The scheduler (`dodaios/notify/reminders.py`) tells a reminder once, at its
 * time. From then on it waits on the rail until the person ticks it off or
 * snoozes it, or until it leaves the current set by itself (a reminder a week
 * after its time, a calendar appointment once it has ended).
 *
 * Only what the scheduler has already told shows here (`delivered`): a
 * reminder never reaches the rail before its desktop notification.
 */

interface DueRemindersState {
  items: ReminderRow[];
}

export const useDueRemindersStore = create<DueRemindersState>(() => ({ items: [] }));

/** The scheduler looks every 30 s; reading as often keeps the tile within a minute of its time. */
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
      useDueRemindersStore.setState({ items: dueNow(items ?? []) });
    } catch {
      // The next read tries again; the rail keeps what it showed.
    } finally {
      inflight = null;
    }
  })();
  return inflight;
}

/** Take a reminder off the rail at once (ticked off or snoozed); the next read confirms it. */
export function dropDueReminder(id: string): void {
  useDueRemindersStore.setState((state) => ({ items: state.items.filter((row) => row.id !== id) }));
}

/** Keep the list fresh while the window is in sight; returns the stop function. */
export function watchDueReminders(): () => void {
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

/** When a reminder was due, short: the time today, else the day and the time. */
export function formatDue(dueAt: string | null, locale: string, now: Date = new Date()): string {
  if (!dueAt) return "";
  const date = new Date(dueAt);
  if (Number.isNaN(date.getTime())) return dueAt;
  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (date.toDateString() === now.toDateString()) return time;
  return `${date.toLocaleDateString(locale, { weekday: "short", day: "numeric", month: "short" })} ${time}`;
}
