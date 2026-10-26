/**
 * A routine's trigger as one plain-language sentence, in the reader's time.
 *
 * The scheduler stores a raw TaskSpec trigger (`dodaios/tasks/schema.py`):
 * `every` / `calendar` / `cron` / `at_time` / `after_delay` / `on_event`,
 * webhooks, integration hooks and sources. Clock times are converted from
 * the routine's own zone into the reader's zone, weekdays shift with them
 * when the conversion crosses midnight, and the routine's zone is named
 * when it differs. A cron line the sentence builder does not understand is
 * shown raw rather than guessed.
 *
 * `t` is the locale function; all words come from `society.agent_routines.schedule.*`,
 * weekday and month names from `Intl`, so every language reads naturally.
 */

export type Translate = (key: string) => string;

export interface HumanScheduleOptions {
  t: Translate;
  /** BCP 47 locale for weekday/month names and clock times. */
  locale?: string;
  /** The reader's IANA zone (default: the browser's). */
  viewerZone?: string;
  /** "Now", for the zone offsets (DST) — tests pin it. */
  now?: Date;
}

const KEY = "society.agent_routines.schedule.";
const WEEKDAYS_ONLY = [0, 1, 2, 3, 4];
const WEEKEND_ONLY = [5, 6];

function fill(template: string, values: Record<string, string | number>): string {
  return template.replace(/\{(\w+)\}/g, (match, name: string) => (name in values ? String(values[name]) : match));
}

function say(t: Translate, key: string, values: Record<string, string | number> = {}): string {
  return fill(t(KEY + key), values);
}

function list(items: string[], locale: string): string {
  if (items.length <= 1) return items[0] ?? "";
  try {
    return new Intl.ListFormat(locale, { style: "long", type: "conjunction" }).format(items);
  } catch {
    return items.join(", ");
  }
}

function sameSet(a: number[], b: number[]): boolean {
  return a.length === b.length && a.every((value) => b.includes(value));
}

/** Minutes east of UTC that `zone` is at `at`; null for an unknown zone. */
export function zoneOffsetMinutes(zone: string, at: Date): number | null {
  try {
    const parts = new Intl.DateTimeFormat("en-US", {
      timeZone: zone, hourCycle: "h23", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit",
    }).formatToParts(at);
    const get = (type: string) => Number(parts.find((part) => part.type === type)?.value ?? "0");
    const wall = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour") % 24, get("minute"));
    const instant = Math.floor(at.getTime() / 60_000) * 60_000;
    return Math.round((wall - instant) / 60_000);
  } catch {
    return null;
  }
}

function viewerZoneOf(options: HumanScheduleOptions): string {
  if (options.viewerZone) return options.viewerZone;
  try { return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC"; } catch { return "UTC"; }
}

function clock(minutes: number, locale: string): string {
  const at = new Date(Date.UTC(2024, 0, 1, Math.floor(minutes / 60), minutes % 60));
  return at.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
}

function weekdayName(day: number, locale: string): string {
  // 2024-01-01 was a Monday: day 0 = Monday, as the calendar trigger stores it.
  return new Date(Date.UTC(2024, 0, 1 + day)).toLocaleDateString(locale, { weekday: "long", timeZone: "UTC" });
}

function monthName(month: number, locale: string): string {
  return new Date(Date.UTC(2024, month - 1, 1)).toLocaleDateString(locale, { month: "long", timeZone: "UTC" });
}

function dayOfYear(month: number, day: number, locale: string): string {
  return new Date(Date.UTC(2024, month - 1, day)).toLocaleDateString(locale, { month: "long", day: "numeric", timeZone: "UTC" });
}

/** A short city-ish label for a zone: "Europe/Berlin" → "Berlin". */
export function zoneLabel(zone: string): string {
  const tail = zone.split("/").pop() ?? zone;
  return tail.replace(/_/g, " ");
}

interface Wall {
  /** Minutes after midnight in the reader's zone. */
  times: number[];
  /** Weekdays (0 = Monday) in the reader's zone, or [] for every day. */
  weekdays: number[];
  monthDays: number[];
  months: number[];
  /** The routine's own zone, when it is not the reader's and the sentence keeps it. */
  keptZone: string;
  /** The routine's own clock times, when they were converted. */
  originalTimes: number[];
  originalZone: string;
}

/**
 * Move clock times (and weekdays with them) from `zone` into the reader's
 * zone. Month days do not move across midnight cleanly, so a converted
 * time that changes the date of a month-day rule keeps the routine's zone.
 */
function toViewer(times: number[], weekdays: number[], monthDays: number[], months: number[], zone: string, options: HumanScheduleOptions): Wall {
  const viewer = viewerZoneOf(options);
  const base: Wall = { times, weekdays, monthDays, months, keptZone: "", originalTimes: [], originalZone: "" };
  if (!zone || zone === viewer) return base;
  const now = options.now ?? new Date();
  const from = zoneOffsetMinutes(zone, now);
  const to = zoneOffsetMinutes(viewer, now);
  if (from === null || to === null) return { ...base, keptZone: zone };
  const delta = to - from;
  if (delta === 0) return base;
  const shifted = times.map((minutes) => minutes + delta);
  const dayShifts = new Set(shifted.map((minutes) => Math.floor(minutes / 1440)));
  if (dayShifts.size > 1 || ((monthDays.length || months.length) && !dayShifts.has(0))) {
    return { ...base, keptZone: zone };
  }
  const shift = [...dayShifts][0] ?? 0;
  return {
    times: shifted.map((minutes) => ((minutes % 1440) + 1440) % 1440),
    weekdays: weekdays.map((day) => (((day + shift) % 7) + 7) % 7).sort((a, b) => a - b),
    monthDays, months, keptZone: "", originalTimes: times, originalZone: zone,
  };
}

/** The sentence for clock times on a day pattern, in the reader's zone. */
function wallSentence(wall: Wall, options: HumanScheduleOptions): string {
  const { t } = options;
  const locale = options.locale ?? "en";
  const at = list([...wall.times].sort((a, b) => a - b).map((minutes) => clock(minutes, locale)), locale);
  let sentence: string;
  const days = [...new Set(wall.weekdays)].sort((a, b) => a - b);
  if (wall.monthDays.length && wall.months.length === 1 && !days.length) {
    sentence = say(t, "yearly_at", { date: list(wall.monthDays.map((day) => dayOfYear(wall.months[0], day, locale)), locale), time: at });
  } else if (wall.monthDays.length) {
    sentence = say(t, "monthly_at", { days: list(wall.monthDays.map(String), locale), time: at });
  } else if (!days.length || days.length === 7) {
    sentence = say(t, "daily_at", { time: at });
  } else if (sameSet(days, WEEKDAYS_ONLY)) {
    sentence = say(t, "weekdays_at", { time: at });
  } else if (sameSet(days, WEEKEND_ONLY)) {
    sentence = say(t, "weekends_at", { time: at });
  } else {
    sentence = say(t, "days_at", { days: list(days.map((day) => weekdayName(day, locale)), locale), time: at });
  }
  if (wall.months.length && !(wall.monthDays.length && wall.months.length === 1 && !days.length)) {
    sentence = say(t, "in_months", { schedule: sentence, months: list(wall.months.map((month) => monthName(month, locale)), locale) });
  }
  if (wall.keptZone) return say(t, "zone_time", { schedule: sentence, zone: zoneLabel(wall.keptZone) });
  if (wall.originalZone && wall.originalTimes.length) {
    const original = list(wall.originalTimes.map((minutes) => clock(minutes, locale)), locale);
    return say(t, "converted", { schedule: sentence, time: original, zone: zoneLabel(wall.originalZone) });
  }
  return sentence;
}

// ------------------------------------------------------------------- cron

type CronField = { any: true } | { any: false; values: number[]; step?: number };

const MONTH_NAMES = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"];
const DAY_NAMES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"];
const ALIASES: Record<string, string> = {
  "@yearly": "0 0 1 1 *", "@annually": "0 0 1 1 *", "@monthly": "0 0 1 * *",
  "@weekly": "0 0 * * 0", "@daily": "0 0 * * *", "@midnight": "0 0 * * *", "@hourly": "0 * * * *",
};

function cronNumber(token: string, names?: string[], offset = 0): number {
  const lower = token.toLowerCase();
  const named = names?.indexOf(lower) ?? -1;
  if (named >= 0) return named + offset;
  if (!/^\d+$/.test(token)) throw new Error(`bad cron token ${token}`);
  return Number(token);
}

/** One cron field as "any" or the explicit values it allows. */
export function parseCronField(text: string, min: number, max: number, names?: string[], nameOffset = 0): CronField {
  if (text === "*" || text === "?") return { any: true };
  const values = new Set<number>();
  let step: number | undefined;
  for (const part of text.split(",")) {
    const [range, stepText] = part.split("/");
    const by = stepText === undefined ? 1 : Number(stepText);
    if (!Number.isInteger(by) || by < 1) throw new Error("bad cron step");
    let lo: number; let hi: number;
    if (range === "*" || range === "?") { lo = min; hi = max; if (stepText !== undefined && text.split(",").length === 1) step = by; }
    else if (range.includes("-")) { const [a, b] = range.split("-"); lo = cronNumber(a, names, nameOffset); hi = cronNumber(b, names, nameOffset); }
    else {
      lo = cronNumber(range, names, nameOffset); hi = stepText !== undefined ? max : lo;
      if (stepText !== undefined && lo === min && text.split(",").length === 1) step = by;
    }
    if (lo < min || hi > max || lo > hi) throw new Error("cron value out of range");
    for (let value = lo; value <= hi; value += by) values.add(value);
  }
  const sorted = [...values].sort((a, b) => a - b);
  if (step === undefined && sorted.length === max - min + 1) return { any: true };
  return { any: false, values: sorted, ...(step !== undefined ? { step } : {}) };
}

function cronSentence(expression: string, zone: string, options: HumanScheduleOptions): string {
  const { t } = options;
  const fields = (ALIASES[expression.trim().toLowerCase()] ?? expression).trim().split(/\s+/);
  if (fields.length !== 5) throw new Error("not a five-field cron line");
  const minute = parseCronField(fields[0], 0, 59);
  const hour = parseCronField(fields[1], 0, 23);
  const dom = parseCronField(fields[2], 1, 31);
  const month = parseCronField(fields[3], 1, 12, MONTH_NAMES, 1);
  // Cron counts Sunday as 0 (and 7); the calendar trigger counts Monday as 0.
  // Parsed over 0–7 so ranges like "1-7" stay valid; 7 folds onto Sunday.
  const dowRaw = parseCronField(fields[4], 0, 7, DAY_NAMES);
  const dowSet = dowRaw.any ? [] : [...new Set(dowRaw.values.map((day) => (day + 6) % 7))].sort((a, b) => a - b);
  const dow = dowSet.length === 7 ? [] : dowSet;
  const months = month.any ? [] : month.values;
  const daysSuffix = (sentence: string) => {
    if (!dow.length) return sentence;
    const locale = options.locale ?? "en";
    const days = sameSet(dow, WEEKDAYS_ONLY) ? say(t, "on_weekdays") : sameSet(dow, WEEKEND_ONLY) ? say(t, "on_weekends")
      : list(dow.map((day) => weekdayName(day, locale)), locale);
    return say(t, "with_days", { schedule: sentence, days });
  };
  const restOpen = dom.any && month.any;
  if (minute.any && hour.any && restOpen) return daysSuffix(say(t, "every_minute"));
  if (!minute.any && minute.step && minute.values[0] === 0 && hour.any && restOpen) {
    return daysSuffix(say(t, "every_minutes", { n: minute.step }));
  }
  if (!minute.any && minute.values.length === 1 && restOpen && (hour.any || (hour.step && hour.values[0] === 0))) {
    const at = minute.values[0];
    const step = hour.any ? 1 : hour.step!;
    const sentence = step === 1
      ? (at === 0 ? say(t, "every_hour") : say(t, "every_hour_at", { minute: String(at).padStart(2, "0") }))
      : (at === 0 ? say(t, "every_hours", { n: step }) : say(t, "every_hours_at", { n: step, minute: String(at).padStart(2, "0") }));
    return daysSuffix(sentence);
  }
  if (!minute.any && !hour.any && minute.values.length * hour.values.length <= 6 && (dom.any || !dow.length)) {
    const times = hour.values.flatMap((h) => minute.values.map((m) => h * 60 + m));
    return wallSentence(toViewer(times, dow, dom.any ? [] : dom.values, months, zone, options), options);
  }
  throw new Error("cron shape without a sentence");
}

// ------------------------------------------------------------------ entry

function durationWords(seconds: number, t: Translate): string {
  if (seconds >= 86_400 && seconds % 86_400 === 0) return say(t, "n_days", { n: seconds / 86_400 });
  if (seconds >= 3_600 && seconds % 3_600 === 0) return say(t, "n_hours", { n: seconds / 3_600 });
  if (seconds >= 60 && seconds % 60 === 0) return say(t, "n_minutes", { n: seconds / 60 });
  return say(t, "n_seconds", { n: Math.round(seconds) });
}

function parseClock(text: unknown): number | null {
  const match = /^(\d{1,2}):(\d{2})$/.exec(String(text ?? ""));
  if (!match) return null;
  const hours = Number(match[1]); const minutes = Number(match[2]);
  return hours < 24 && minutes < 60 ? hours * 60 + minutes : null;
}

function numbers(value: unknown): number[] {
  return Array.isArray(value) ? value.map(Number).filter((n) => Number.isFinite(n)) : [];
}

/**
 * The plain-language sentence for a stored trigger, or "" when there is none.
 * Never throws: an unreadable shape falls back to the raw text.
 */
export function humanSchedule(trigger: unknown, options: HumanScheduleOptions): string {
  if (!trigger || typeof trigger !== "object") return "";
  const raw = trigger as Record<string, unknown>;
  const { t } = options;
  const locale = options.locale ?? "en";
  const kind = String(raw.type ?? raw.kind ?? "");
  try {
    if (kind === "cron") {
      const expression = String(raw.expression ?? "").trim();
      try {
        return cronSentence(expression, String(raw.timezone ?? ""), options);
      } catch {
        return say(t, "custom_cron", { expression });
      }
    }
    if (kind === "calendar") {
      const time = parseClock(raw.local_time);
      if (time === null) return say(t, "custom", { kind });
      return wallSentence(toViewer([time], numbers(raw.weekdays), numbers(raw.month_days), numbers(raw.months), String(raw.timezone ?? ""), options), options);
    }
    if (kind === "every") {
      const seconds = Number(raw.interval_seconds ?? 0);
      if (!(seconds > 0)) return say(t, "custom", { kind });
      const start = typeof raw.start_at === "string" ? new Date(raw.start_at) : null;
      if (start && !Number.isNaN(start.getTime()) && seconds % 86_400 === 0) {
        const at = start.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit", ...(options.viewerZone ? { timeZone: options.viewerZone } : {}) });
        return seconds === 86_400 ? say(t, "daily_at", { time: at }) : say(t, "every_n_days_at", { n: seconds / 86_400, time: at });
      }
      if (seconds === 60) return say(t, "every_minute");
      if (seconds === 3_600) return say(t, "every_hour");
      if (seconds === 86_400) return say(t, "every_day");
      if (seconds === 604_800) return say(t, "every_week");
      return say(t, "every_duration", { duration: durationWords(seconds, t) });
    }
    if (kind === "at_time") {
      const at = new Date(String(raw.iso_timestamp ?? ""));
      if (Number.isNaN(at.getTime())) return say(t, "custom", { kind });
      const when = at.toLocaleString(locale, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", ...(options.viewerZone ? { timeZone: options.viewerZone } : {}) });
      return say(t, "once_at", { when });
    }
    if (kind === "after_delay") return say(t, "once_in", { duration: durationWords(Number(raw.delay_seconds ?? 0), t) });
    if (kind === "on_event") return say(t, "on_event", { event: String(raw.event_name ?? "") });
    if (kind === "webhook") {
      const provider = String(raw.provider ?? "generic");
      return provider && provider !== "generic" ? say(t, "on_provider", { provider: provider.charAt(0).toUpperCase() + provider.slice(1) }) : say(t, "on_webhook");
    }
    if (kind === "event_hook") return say(t, "on_integration", { event: String(raw.event_name ?? "") });
    if (kind === "source") {
      const source = (raw.source ?? {}) as { kind?: string; topic?: string; path?: string };
      const sourceKind = String(source.kind ?? "");
      if (sourceKind === "manual" || sourceKind === "form" || sourceKind === "chat") return say(t, "on_demand");
      if (sourceKind === "file") return say(t, "on_file", { path: String(source.path ?? "") });
      const label = t(`society.triggers.kinds.${sourceKind}`);
      return say(t, "on_source", { source: label.startsWith("society.") ? sourceKind : label });
    }
  } catch {
    // Fall through to the raw kind below.
  }
  return kind ? say(t, "custom", { kind }) : "";
}

/** The trigger family, for the row icon and the "test run" rules. */
export type TriggerFamily = "clock" | "interval" | "once" | "webhook" | "event" | "source" | "manual" | "unknown";

export function triggerFamily(trigger: unknown): TriggerFamily {
  if (!trigger || typeof trigger !== "object") return "unknown";
  const raw = trigger as Record<string, unknown>;
  const kind = String(raw.type ?? raw.kind ?? "");
  if (kind === "calendar" || kind === "cron") return "clock";
  if (kind === "every") return "interval";
  if (kind === "at_time" || kind === "after_delay") return "once";
  if (kind === "webhook") return "webhook";
  if (kind === "on_event" || kind === "event_hook") return "event";
  if (kind === "source") {
    const sourceKind = String((raw.source as { kind?: string } | undefined)?.kind ?? "");
    return ["manual", "form", "chat"].includes(sourceKind) ? "manual" : "source";
  }
  return "unknown";
}
