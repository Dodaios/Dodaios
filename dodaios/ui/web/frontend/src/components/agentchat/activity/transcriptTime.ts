/**
 * When a conversation shows a time stamp, and what it says.
 *
 * A stamp marks a pause: 15 minutes or more of silence, or a new day. It
 * sits in front of a whole run of messages by the same author, never in the
 * middle of one, so a reply that came after a long think is not cut off
 * from its question. The first message of a conversation always gets one.
 *
 * The words are short and relative: "Today 14:05", "Yesterday 09:12",
 * "Tue, 14 Oct 18:30" inside the year, a full date before it.
 */

/** Silence this long earns a fresh stamp. */
export const STAMP_GAP_MS = 15 * 60_000;

export interface StampEntry {
  id: string;
  /** When the entry happened; 0 when it carries no time (it neither earns nor breaks a stamp). */
  ts: number;
  /** When it ended, for an entry that lasts (a turn); a pause is counted from here. */
  end?: number;
  /** Who spoke: consecutive entries by the same author share one stamp. */
  author: string;
}

function dayOf(ms: number): string {
  return new Date(ms).toDateString();
}

/** The ids of the entries that get a stamp in front of them. */
export function stampPlan(entries: readonly StampEntry[], gapMs = STAMP_GAP_MS): Set<string> {
  const out = new Set<string>();
  let lastTs = 0;
  let lastAuthor: string | null = null;
  for (const entry of entries) {
    if (!entry.ts) continue;
    const newGroup = entry.author !== lastAuthor;
    if (newGroup) {
      const pause = lastTs === 0 || entry.ts - lastTs >= gapMs || dayOf(entry.ts) !== dayOf(lastTs);
      if (pause) out.add(entry.id);
    }
    lastTs = Math.max(lastTs, entry.end ?? entry.ts);
    lastAuthor = entry.author;
  }
  return out;
}

const formatters = new Map<string, Intl.DateTimeFormat>();

function formatter(locale: string, options: Intl.DateTimeFormatOptions): Intl.DateTimeFormat {
  const key = `${locale}|${JSON.stringify(options)}`;
  let found = formatters.get(key);
  if (!found) {
    try {
      found = new Intl.DateTimeFormat(locale, options);
    } catch {
      found = new Intl.DateTimeFormat(undefined, options);
    }
    formatters.set(key, found);
  }
  return found;
}

/** The stamp's words, relative to `now`. `t` fills `run_view.time.*`. */
export function stampLabel(ms: number, now: number, locale: string, t: (key: string) => string): string {
  const date = new Date(ms);
  const time = formatter(locale, { hour: "2-digit", minute: "2-digit" }).format(date);
  const today = new Date(now);
  if (date.toDateString() === today.toDateString()) return t("run_view.time.today").replace("{time}", time);
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return t("run_view.time.yesterday").replace("{time}", time);
  if (date.getFullYear() === today.getFullYear()) {
    return `${formatter(locale, { weekday: "short", day: "numeric", month: "short" }).format(date)} ${time}`;
  }
  return `${formatter(locale, { day: "numeric", month: "short", year: "numeric" }).format(date)} ${time}`;
}
