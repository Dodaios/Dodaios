import type { DictationEntry } from "@/hooks/useDictation";

/** One local calendar day of the history. */
export interface Day {
  /** Local date as `YYYY-MM-DD`; the raw stamp when it cannot be parsed. */
  key: string;
  entries: DictationEntry[];
}

/** `YYYY-MM-DD` in the viewer's own timezone. */
export function dayKey(date: Date): string {
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${date.getFullYear()}-${month}-${day}`;
}

function keyOf(stamp: string): string {
  const date = new Date(stamp);
  return Number.isNaN(date.getTime()) ? stamp : dayKey(date);
}

/**
 * Sorts entries newest first and cuts them into local calendar days.
 *
 * Local, not UTC: a dictation made late in the evening belongs to the day the
 * person lived it on, wherever they are.
 */
export function groupByDay(entries: readonly DictationEntry[]): Day[] {
  const sorted = [...entries].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  );
  const days = new Map<string, DictationEntry[]>();
  for (const entry of sorted) {
    const key = keyOf(entry.created_at);
    const day = days.get(key);
    if (day) day.push(entry);
    else days.set(key, [entry]);
  }
  return [...days.entries()]
    .map(([key, dayEntries]) => ({ key, entries: dayEntries }))
    .sort((a, b) => (a.key < b.key ? 1 : a.key > b.key ? -1 : 0));
}

/** "Today", "Yesterday", or the long date in the interface language. */
export function dayTitle(
  key: string,
  locale: string,
  words: { today: string; yesterday: string },
  now: Date = new Date(),
): string {
  if (key === dayKey(now)) return words.today;
  const yesterday = new Date(now);
  yesterday.setDate(yesterday.getDate() - 1);
  if (key === dayKey(yesterday)) return words.yesterday;
  const date = new Date(`${key}T00:00:00`);
  return Number.isNaN(date.getTime())
    ? key
    : date.toLocaleDateString(locale, { year: "numeric", month: "long", day: "numeric" });
}

/** The time of day without seconds, in the interface language's clock. */
export function timeOfDay(stamp: string, locale: string): string {
  const date = new Date(stamp);
  return Number.isNaN(date.getTime())
    ? ""
    : date.toLocaleTimeString(locale, { hour: "numeric", minute: "2-digit" });
}

/** Entries whose delivered or heard text contains the query, ignoring case. */
export function matching(entries: readonly DictationEntry[], query: string): DictationEntry[] {
  const needle = query.trim().toLowerCase();
  if (!needle) return [...entries];
  return entries.filter(
    (entry) =>
      (entry.text ?? "").toLowerCase().includes(needle) ||
      (entry.raw_text ?? "").toLowerCase().includes(needle),
  );
}
