/** Numbers and times on the routine panels, in the UI language. */

const UNITS: [Intl.RelativeTimeFormatUnit, number][] = [
  ["year", 365 * 86_400_000],
  ["month", 30 * 86_400_000],
  ["week", 7 * 86_400_000],
  ["day", 86_400_000],
  ["hour", 3_600_000],
  ["minute", 60_000],
];

/** "in 3 hours", "2 days ago", "now". */
export function relativeTime(atMs: number, nowMs: number, locale: string): string {
  const diff = atMs - nowMs;
  const format = new Intl.RelativeTimeFormat(locale, { numeric: "auto" });
  for (const [unit, size] of UNITS) {
    if (Math.abs(diff) >= size) return format.format(Math.round(diff / size), unit);
  }
  return format.format(0, "minute");
}

/** "Mon, 08:00" this week, otherwise "12 Oct, 08:00". */
export function shortDateTime(atMs: number, nowMs: number, locale: string): string {
  const at = new Date(atMs);
  const sameDay = new Date(nowMs).toDateString() === at.toDateString();
  const time = at.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  if (sameDay) return time;
  const withinWeek = Math.abs(atMs - nowMs) < 6 * 86_400_000;
  const day = withinWeek
    ? at.toLocaleDateString(locale, { weekday: "short" })
    : at.toLocaleDateString(locale, { day: "numeric", month: "short" });
  return `${day}, ${time}`;
}

/** "850 ms", "42 s", "3 min 5 s", "1 h 4 min". */
export function formatDuration(ms: number | null | undefined): string {
  if (ms === null || ms === undefined || !Number.isFinite(ms) || ms < 0) return "";
  if (ms < 1000) return `${Math.round(ms)} ms`;
  const seconds = Math.round(ms / 1000);
  if (seconds < 60) return `${seconds} s`;
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return seconds % 60 ? `${minutes} min ${seconds % 60} s` : `${minutes} min`;
  const hours = Math.floor(minutes / 60);
  return minutes % 60 ? `${hours} h ${minutes % 60} min` : `${hours} h`;
}

/** "$0.04", "<$0.01", "$1.20"; "" when the cost is unknown. */
export function formatCost(usd: number | null | undefined, locale: string): string {
  if (usd === null || usd === undefined || !Number.isFinite(usd)) return "";
  if (usd === 0) return new Intl.NumberFormat(locale, { style: "currency", currency: "USD" }).format(0);
  if (usd < 0.01) return `<${new Intl.NumberFormat(locale, { style: "currency", currency: "USD" }).format(0.01)}`;
  return new Intl.NumberFormat(locale, { style: "currency", currency: "USD", maximumFractionDigits: usd < 1 ? 3 : 2, minimumFractionDigits: 2 }).format(usd);
}

/** `{name}` placeholders. */
export function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in values ? String(values[name]) : match));
}
