/**
 * Numbers into words for the Self-improvement page.
 *
 * The backend sends numbers and names only (dodaios/rsi/overview.py); every
 * sentence is built here from the page's own strings, in the interface
 * language. Scores are shares of solved tasks (0 to 1); the page speaks of
 * "points", a difference of one task in a hundred.
 *
 * The one rule this file exists to keep: an uncertain number is never worded
 * as a win. A difference whose range includes zero is "not certain yet",
 * whatever its sign.
 */
import { fill } from "@/i18n";
import type { Measurement } from "@/lib/selfImprovementApi";

type T = (key: string) => string;

/** Domains whose check asks no model (docs/self-improvement.md, "The benchmark"). */
export const MODEL_FREE_DOMAINS: ReadonlySet<string> = new Set(["recall", "skill"]);

/** Tasks the deciding part (the select split) needs before anything is decided (`MIN_PAIRS`, dodaios/rsi/gate/rules.py). */
export const DECIDE_MIN_TASKS = 30;

/** A prompt this much shorter is a result of its own, said in the headline. */
export const SAVING_HEADLINE_SHARE = 0.05;

/** How much shorter the prompt is now than as shipped, as a share (0.67); 0 when it is not shorter. */
export function promptSaving(nowTokens: number, factoryTokens: number): number {
  if (!(factoryTokens > 0) || !(nowTokens < factoryTokens)) return 0;
  return (factoryTokens - nowTokens) / factoryTokens;
}

/** A share as a whole percent: 0.667 → "67 %" (in the locale's own way). */
export function fmtPercent(share: number, locale: string): string {
  return new Intl.NumberFormat(locale, { style: "percent", maximumFractionDigits: 0 }).format(share);
}

/** Domains whose cost is the prompt a task adds, in tokens. */
const TOKEN_COST_DOMAINS: ReadonlySet<string> = new Set(["recall", "first_move"]);

export type Certainty = "better" | "worse" | "unclear";

/** Where a measured range lies: wholly above zero, wholly below, or across it. */
export function certainty(low: number | null | undefined, high: number | null | undefined): Certainty {
  if (typeof low === "number" && low > 0) return "better";
  if (typeof high === "number" && high < 0) return "worse";
  return "unclear";
}

/** A score difference as signed points: 0.021 → "+2.1". */
export function fmtPoints(diff: number, locale: string): string {
  const points = Math.round(diff * 1000) / 10;
  return new Intl.NumberFormat(locale, {
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
    signDisplay: "exceptZero",
  }).format(points === 0 ? 0 : points);
}

/** A score as a share: 0.836 → "83.6 %" (in the locale's own way). */
export function fmtShare(score: number, locale: string): string {
  return new Intl.NumberFormat(locale, {
    style: "percent",
    minimumFractionDigits: 1,
    maximumFractionDigits: 1,
  }).format(score);
}

export function fmtTokens(tokens: number, locale: string): string {
  return new Intl.NumberFormat(locale, { maximumFractionDigits: 0 }).format(Math.round(tokens));
}

/** A parameter value as the person reads it; `null` is "not set". */
export function fmtValue(value: unknown, locale: string): string {
  if (typeof value === "number") {
    return new Intl.NumberFormat(locale, { maximumFractionDigits: 2 }).format(value);
  }
  if (value === null || value === undefined) return "–";
  return String(value);
}

/** Registry targets of notes the assistant wrote for itself (`PREFIX` in dodaios/rsi/adopt.py). */
export const NOTE_TARGET_PREFIX = "lesson:";

/** The catalog key of a parameter: dots cannot sit inside one key segment. */
export function paramKey(name: string): string {
  return name.replace(/[^\w]/g, "_");
}

/** A parameter's plain title, from the page's strings; the catalog's `doc` when it has none. */
export function paramTitle(t: T, name: string, doc = ""): string {
  // A note the assistant wrote for itself is named by the page, never by its id.
  if (name.startsWith(NOTE_TARGET_PREFIX)) return t("self_improvement.stack.note_title");
  const key = `self_improvement.param.${paramKey(name)}.title`;
  const title = t(key);
  if (title !== key) return title;
  return doc || name;
}

/** What a parameter sets, in one sentence; the catalog's `doc` when the page has none. */
export function paramAbout(t: T, name: string, doc = ""): string {
  const key = `self_improvement.param.${paramKey(name)}.about`;
  const about = t(key);
  return about !== key ? about : doc;
}

/**
 * A switched line beside the lead's messages as one plain sentence ("Dropped the
 * line …"), from the page's strings; "" when `name` switches no line or the value
 * is no switch. A line switch is a parameter with on/off sentences
 * (`self_improvement.line.<key>`; the kernel's list is dodaios/rsi/lines.py).
 */
export function lineSentence(t: T, name: string, after: unknown): string {
  if (typeof after !== "boolean") return "";
  const key = `self_improvement.line.${paramKey(name)}.${after ? "on" : "off"}`;
  const text = t(key);
  return text !== key ? text : "";
}

/** A value as the person reads it, with on and off in words for a switch. */
export function valueWords(t: T, value: unknown, locale: string): string {
  if (typeof value === "boolean") return t(value ? "self_improvement.value.on" : "self_improvement.value.off");
  return fmtValue(value, locale);
}

/** An area's own wording for `key` ("building", "no_tasks"), else the shared one. */
export function areaText(t: T, domain: string, key: string): string {
  const own = `self_improvement.domain.${domain}.${key}`;
  const text = t(own);
  return text !== own ? text : t(`self_improvement.area.${key}`);
}

export function areaName(t: T, domain: string): string {
  const key = `self_improvement.domain.${domain}.name`;
  const name = t(key);
  return name !== key ? name : domain;
}

/** What an area's check asks, in one sentence; empty when the page has none for it. */
export function areaAbout(t: T, domain: string): string {
  const key = `self_improvement.domain.${domain}.about`;
  const about = t(key);
  return about !== key ? about : "";
}

/** A word from a small closed set (states, outcomes), or the raw value when the set has no word for it. */
export function wordFor(t: T, group: string, value: string): string {
  const key = `self_improvement.${group}.${value.replace(/\s+/g, "_")}`;
  const word = t(key);
  return word !== key ? word : value;
}

/** The cost part of an effect: "prompt 100 tokens shorter"; empty when nothing changed or the domain has no token cost. */
export function costWords(t: T, domain: string, costDiff: number | null | undefined, locale: string): string {
  if (!TOKEN_COST_DOMAINS.has(domain) || typeof costDiff !== "number") return "";
  const tokens = Math.round(costDiff);
  if (tokens === 0) return "";
  return fill(t(tokens < 0 ? "self_improvement.effect.shorter" : "self_improvement.effect.longer"), {
    tokens: fmtTokens(Math.abs(tokens), locale),
  });
}

/**
 * One measurement in a line: "+11.9 points on 84 tasks (between +2.0 and +21.0)",
 * "as good on 150 tasks, prompt 100 tokens shorter", or "no clear difference on …".
 */
export function effectWords(t: T, found: Measurement | null | undefined, locale: string): string {
  if (!found || typeof found.diff !== "number" || typeof found.low !== "number" || typeof found.high !== "number") {
    return t("self_improvement.effect.none");
  }
  const where = certainty(found.low, found.high);
  const cost = costWords(t, found.domain, found.cost_diff, locale);
  const numbers = {
    diff: fmtPoints(found.diff, locale),
    low: fmtPoints(found.low, locale),
    high: fmtPoints(found.high, locale),
    n: found.n,
  };
  let head: string;
  if (where === "better") head = fill(t("self_improvement.effect.better"), numbers);
  else if (where === "worse") head = fill(t("self_improvement.effect.worse"), numbers);
  else if (cost && (found.cost_diff ?? 0) < 0) head = fill(t("self_improvement.effect.as_good"), numbers);
  else head = fill(t("self_improvement.effect.unclear"), numbers);
  return cost ? `${head}, ${cost}` : head;
}

/** "23 Nov, 03:14" — a night's date in the interface language. */
export function nightDate(ms: number, locale: string): string {
  return new Date(ms).toLocaleString(locale, { weekday: "short", day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" });
}

/** "23 Nov" — a point on the curve. */
export function shortDate(ms: number, locale: string): string {
  return new Date(ms).toLocaleDateString(locale, { day: "numeric", month: "short" });
}
