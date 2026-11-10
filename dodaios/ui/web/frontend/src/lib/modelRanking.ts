import type { CuratedModel } from "@/lib/agentChatApi";

/**
 * Splits a provider's model list into the current lineup and older models.
 *
 * Each model line ("Claude Opus", "Gemini Pro", "GPT Sol") keeps only its
 * newest version in the lineup; earlier versions of that line, and named
 * aliases without a version, move to an "older models" fold. The lineup is
 * sorted strongest first (see `TIER`), then newest version, ties keeping the
 * catalog's own order.
 *
 * Nothing is folded when the list carries no versions at all (Cursor's
 * "Auto", a user's own aliases): there is no evidence of what is older.
 */

export interface RankedModels<T extends CuratedModel = CuratedModel> {
  current: T[];
  older: T[];
}

interface Parsed {
  line: string;
  version: number[];
}

const VERSION = /(\d+(?:[.-]\d+)*)/;
/** Snapshot dates in ids (`-20251001`) and context sizes (`[1m]`) are not versions. */
const NOISE = /(?:[-_]?\d{8}\b)|\[[^\]]*\]|\(\s*[^)]*\)/g;

function parse(model: CuratedModel): Parsed | null {
  for (const source of [model.label, model.id.split("/").pop() ?? model.id]) {
    const text = (source ?? "").replace(NOISE, " ").trim();
    const match = VERSION.exec(text);
    if (!match) continue;
    const version = match[1].split(/[.-]/).map(Number);
    if (version.some((part) => !Number.isFinite(part)) || version[0] > 999) continue;
    const line = (text.slice(0, match.index) + " " + text.slice(match.index + match[0].length))
      .toLocaleLowerCase()
      .replace(/[^a-z]+/g, " ")
      .trim();
    return { line, version };
  }
  return null;
}

function compareVersions(a: number[], b: number[]): number {
  for (let i = 0; i < Math.max(a.length, b.length); i++) {
    const diff = (a[i] ?? 0) - (b[i] ?? 0);
    if (diff) return diff;
  }
  return 0;
}

/**
 * How strong a model line is, lower = better. Vendors name their tiers with
 * a word, and a newer version of a weaker tier is still the weaker model
 * (Haiku 5.5 sits below Opus 5.5, Fable 5.2 above both), so the tier decides
 * the order and the version only breaks ties inside a tier.
 */
const TIER: Record<string, number> = {
  fable: 0, mythos: 0,
  opus: 1, sol: 1, pro: 1, heavy: 1,
  sonnet: 2, terra: 2, astra: 2,
  flash: 3, luna: 3, fast: 3,
  haiku: 4, mini: 4,
  lite: 5, nano: 5,
};
/** A line with no tier word (a bare "GPT", "Grok") sits between the strong and the light tiers. */
const UNRATED = 2.5;

function tierOf(line: string): number {
  const words = line.split(" ");
  const rated = words.filter((word) => word !== "pro" && word in TIER).map((word) => TIER[word]);
  const pro = words.includes("pro");
  // "Sol Pro" outranks "Sol"; a lone "Pro" (Gemini Pro) is a top tier of its own.
  if (rated.length) return Math.max(...rated) - (pro ? 0.5 : 0);
  return pro ? TIER.pro : UNRATED;
}

export function rankModels<T extends CuratedModel>(models: T[]): RankedModels<T> {
  const parsed = models.map((model) => ({ model, info: model.id ? parse(model) : null }));
  if (!parsed.some((entry) => entry.info)) return { current: [...models], older: [] };

  const newest = new Map<string, number[]>();
  for (const { info } of parsed) {
    if (!info) continue;
    const best = newest.get(info.line);
    if (!best || compareVersions(info.version, best) > 0) newest.set(info.line, info.version);
  }

  const byVersion = (a: (typeof parsed)[number], b: (typeof parsed)[number]) =>
    compareVersions(b.info?.version ?? [], a.info?.version ?? []);
  const byStrength = (a: (typeof parsed)[number], b: (typeof parsed)[number]) =>
    // Aliases without a version ("opusplan") have no evidence of strength: last.
    (a.info ? tierOf(a.info.line) : 99) - (b.info ? tierOf(b.info.line) : 99) || byVersion(a, b);
  const current: typeof parsed = [];
  const older: typeof parsed = [];
  for (const entry of parsed) {
    if (entry.info && compareVersions(entry.info.version, newest.get(entry.info.line)!) === 0) current.push(entry);
    else older.push(entry);
  }
  return {
    // Array.prototype.sort is stable, so equal rank keeps catalog order.
    current: current.sort(byStrength).map((entry) => entry.model),
    older: older.sort(byStrength).map((entry) => entry.model),
  };
}

/** The strongest model of a provider's list, or "" when it has none. */
export function bestModelId(models: CuratedModel[]): string {
  return rankModels(models.filter((model) => model.id)).current[0]?.id ?? "";
}
