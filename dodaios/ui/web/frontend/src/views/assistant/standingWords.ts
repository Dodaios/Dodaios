/**
 * A standing task in words: its pace ("every 3 hours", "daily"), its level,
 * what the last look found, and when the next one comes. Pure, so the
 * assistant's page, its panel on the front page and the suggestion card in
 * the conversation all say the same thing the same way.
 */
import { localeForUiLanguage } from "@/components/runs/format";
import { fill, type UiLanguage } from "@/i18n";
import type { StandingAutonomy, StandingLimits, StandingOutcome, StandingTask } from "@/lib/standingTasksApi";
import { whenAhead, whenShort } from "@/views/assistant/format";

type T = (key: string) => string;

const HOUR = 60;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;

/** The paces the person can pick; the server's limits trim both ends. */
export const PACE_CHOICES: readonly number[] = [15, 30, HOUR, 3 * HOUR, 6 * HOUR, 12 * HOUR, DAY, 3 * DAY, WEEK];

export const AUTONOMY_ORDER: readonly StandingAutonomy[] = ["watch", "prepare", "act"];
const OUTCOMES = new Set<string>(["quiet", "reported", "prepared", "acted", "asked", "failed", "skipped"]);

/** The first letter in upper case, for words that open a line or an option. */
export function capitalize(text: string, lang: UiLanguage): string {
  return text.charAt(0).toLocaleUpperCase(localeForUiLanguage(lang)) + text.slice(1);
}

/** The pace in words, lower case: "every 15 minutes", "hourly", "every 3 hours", "daily", "weekly". */
export function paceWords(minutes: number, t: T, lang: UiLanguage): string {
  const n = Math.max(1, Math.round(minutes));
  const count = (value: number) => value.toLocaleString(localeForUiLanguage(lang), { maximumFractionDigits: 1 });
  if (n === WEEK) return t("standing.pace_weekly");
  if (n === DAY) return t("standing.pace_daily");
  if (n === HOUR) return t("standing.pace_hourly");
  if (n % DAY === 0) return fill(t("standing.pace_days"), { n: count(n / DAY) });
  if (n % HOUR === 0) return fill(t("standing.pace_hours"), { n: count(n / HOUR) });
  if (n < 2 * HOUR) return fill(t("standing.pace_minutes"), { n: count(n) });
  // An odd pace the assistant chose for itself, to the nearest half hour.
  return fill(t("standing.pace_hours"), { n: count(Math.round(n / 30) / 2) });
}

/** "looks every 3 hours", lower case so it can follow another phrase. */
export function looksWords(minutes: number, t: T, lang: UiLanguage): string {
  return fill(t("standing.looks"), { pace: paceWords(minutes, t, lang) });
}

/**
 * The choices of a pace picker: the presets inside the server's limits, plus
 * the task's own pace when the assistant settled on one in between.
 */
export function paceOptions(
  limits: StandingLimits | undefined,
  current: number,
  t: T,
  lang: UiLanguage,
): { value: string; label: string }[] {
  const min = limits?.min_interval_min ?? PACE_CHOICES[0];
  const max = limits?.max_interval_min ?? WEEK;
  const minutes = new Set(PACE_CHOICES.filter((choice) => choice >= min && choice <= max));
  if (current > 0) minutes.add(Math.round(current));
  return [...minutes]
    .sort((a, b) => a - b)
    .map((choice) => ({ value: String(choice), label: capitalize(paceWords(choice, t, lang), lang) }));
}

/** The level's name: "Watch", "Prepare", "Act"; an unknown level as the server wrote it. */
export function autonomyName(level: string, t: T): string {
  return (AUTONOMY_ORDER as readonly string[]).includes(level) ? t(`standing.autonomy_${level}`) : level;
}

/** The level as what the assistant does: "Prepares the next step". */
export function autonomyDoes(level: string, t: T): string {
  return (AUTONOMY_ORDER as readonly string[]).includes(level) ? t(`standing.autonomy_${level}_does`) : level;
}

/** "Prepares the next step · looks every 3 hours" */
export function mannerLine(task: { autonomy: string; interval_min: number }, t: T, lang: UiLanguage): string {
  const parts = [autonomyDoes(task.autonomy, t)];
  if (task.interval_min > 0) parts.push(looksWords(task.interval_min, t, lang));
  return parts.join(" · ");
}

/** What a look came to, in words: "Nothing new", "Needs you"; "" before the first look. */
export function outcomeWords(outcome: string, t: T): string {
  return OUTCOMES.has(outcome) ? t(`standing.outcome_${outcome}`) : "";
}

export type OutcomeTone = "attention" | "fault" | "plain";

/** A look that waits for the person, or one that failed, is said in its status hue. */
export function outcomeTone(outcome: StandingOutcome | string): OutcomeTone {
  if (outcome === "asked") return "attention";
  if (outcome === "failed") return "fault";
  return "plain";
}

export const TONE_INK: Record<OutcomeTone, string> = {
  attention: "text-warning",
  fault: "text-destructive",
  plain: "",
};

/** What the last look found: "Told you: cost per purchase rose to 18.40 EUR"; "" before the first look. */
export function lastFinding(task: Pick<StandingTask, "last_outcome" | "last_summary">, t: T): string {
  const words = outcomeWords(task.last_outcome, t);
  const summary = task.last_summary.trim();
  if (!words) return summary;
  return summary ? `${words}: ${summary}` : words;
}

/** "Last look: 14:02"; `null` before the first look. */
export function lastLookLine(task: Pick<StandingTask, "last_run_ms">, t: T, lang: UiLanguage, now = Date.now()): string | null {
  const when = whenShort(task.last_run_ms, lang, now);
  return when ? fill(t("standing.last_look_line"), { when }) : null;
}

/** When the next look comes: "17:00", "tomorrow, 09:00", "any moment"; `null` when none is planned. */
export function nextLookWords(task: Pick<StandingTask, "next_run_ms" | "state">, t: T, lang: UiLanguage, now = Date.now()): string | null {
  if (task.state !== "active" || task.next_run_ms === null) return null;
  return whenAhead(task.next_run_ms, lang, now) ?? t("standing.next_due");
}

/** "Next look: 17:00"; `null` for a task that is not running. */
export function nextLookLine(task: Pick<StandingTask, "next_run_ms" | "state">, t: T, lang: UiLanguage, now = Date.now()): string | null {
  const when = nextLookWords(task, t, lang, now);
  return when ? fill(t("standing.next_look_line"), { when }) : null;
}
