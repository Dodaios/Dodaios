import { useEffect, useSyncExternalStore } from "react";

import type { RailNotice } from "./railNotices";

/**
 * Notices the person closed or put off from the rail's right-click menu.
 *
 * Closing hides one notice until it is a new one: the same subject asking
 * again later (a new question from the agent, a new disconnect of the same
 * plugin) has a new `stamp` and shows again. A notice with no stamp of its
 * own (a provider in trouble) cannot tell "still" from "again", so closing it
 * holds for a day; if the trouble is still there then, it is worth a tile.
 *
 * "Hide for an hour" holds for an hour, whatever happens meanwhile.
 *
 * Kept in localStorage, so a restart does not bring back what was closed.
 */

const STORAGE_KEY = "dodaios.railNotices.dismissed";
export const SNOOZE_MS = 60 * 60 * 1000;
/** How long a close holds for a notice without a stamp. */
export const UNSTAMPED_CLOSE_MS = 24 * 60 * 60 * 1000;
/** A stamped close is dropped from storage after this long, so the list stays small. */
const STAMPED_KEEP_MS = 30 * 24 * 60 * 60 * 1000;

interface Dismissal {
  /** The notice as it was when closed; a different one shows again. */
  sign: string;
  /** Hidden until this time (epoch ms). */
  until: number;
}

type Dismissals = Record<string, Dismissal>;

/** What tells this notice apart from a later one about the same subject. */
export function noticeSign(notice: RailNotice): string {
  return [notice.stamp ?? "", notice.title].join("\u0000");
}

function read(): Dismissals {
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    const parsed = raw ? (JSON.parse(raw) as unknown) : null;
    return parsed && typeof parsed === "object" ? (parsed as Dismissals) : {};
  } catch {
    return {};
  }
}

let current: Dismissals = typeof window === "undefined" ? {} : read();
const listeners = new Set<() => void>();

function write(next: Dismissals): void {
  const now = Date.now();
  // Drop what has run out, so storage holds only what still hides something.
  current = Object.fromEntries(Object.entries(next).filter(([, entry]) => entry.until > now));
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(current));
  } catch {
    // Private mode or a full storage: the close still holds for this session.
  }
  listeners.forEach((listener) => listener());
}

/** Close notices: hidden until they come back as a new one (see the module note). */
export function closeNotices(notices: RailNotice[]): void {
  const now = Date.now();
  const next = { ...current };
  for (const notice of notices) {
    next[notice.key] = { sign: noticeSign(notice), until: now + (notice.stamp ? STAMPED_KEEP_MS : UNSTAMPED_CLOSE_MS) };
  }
  write(next);
}

/** Hide a notice for an hour, whatever happens meanwhile. */
export function snoozeNotice(notice: RailNotice): void {
  write({ ...current, [notice.key]: { sign: "", until: Date.now() + SNOOZE_MS } });
}

/** Whether the notice is hidden now. A snooze (empty sign) hides any notice of that key. */
export function isDismissed(notice: RailNotice, dismissals: Dismissals = current, now = Date.now()): boolean {
  const entry = dismissals[notice.key];
  if (!entry || entry.until <= now) return false;
  return entry.sign === "" || entry.sign === noticeSign(notice);
}

function subscribe(listener: () => void): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/**
 * The notices the person did not close or put off. Re-renders when a close
 * or a snooze runs out, so the tile comes back on time.
 */
export function useVisibleNotices(notices: RailNotice[]): RailNotice[] {
  const dismissals = useSyncExternalStore(subscribe, () => current, () => current);
  const now = Date.now();
  const nextEnd = Object.values(dismissals).reduce((soonest, entry) => (entry.until > now ? Math.min(soonest, entry.until) : soonest), Infinity);
  useEffect(() => {
    if (!Number.isFinite(nextEnd)) return;
    // setTimeout holds at most ~24.8 days; a longer wait is re-armed by the next render.
    const timer = window.setTimeout(() => write(current), Math.min(nextEnd - Date.now() + 50, 2 ** 31 - 1));
    return () => window.clearTimeout(timer);
  }, [nextEnd]);
  return notices.filter((notice) => !isDismissed(notice, dismissals, now));
}

/** Tests only: forget every close and snooze. */
export function resetNoticeDismissals(): void {
  write({});
}
