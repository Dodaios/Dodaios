/**
 * Pure view model of the rank surfaces: what the rank card, the service
 * record and the promotion notice show for a subject. Every rank is derived
 * from the subject's level with the Verse's own ladder, so an older backend's
 * rank ids never reach the screen.
 */
import { LEVEL_XP, MAX_LEVEL, isXpSource, type SubjectKind } from "../../progression/levelCatalog";
import { xpUntilLevel } from "../../progression/cosmetics";
import type { AwardRow, SubjectLevel, XpRuleRow } from "../../progression/progressionApi";
import { nextRank, rankForLevel, type RankDef } from "./ranks";

export interface RankView {
  level: number;
  xp: number;
  rank: RankDef;
  next: RankDef | undefined;
  /** XP gathered into the current level, and the level's size (0 at the cap). */
  into: number;
  size: number;
  /** Place on the level bar, 0..1 (1 at the cap). */
  fraction: number;
  /** XP still missing for the next rank; 0 at the top. */
  toNextRank: number;
  atCap: boolean;
}

/** A subject's rank view; an unknown subject is a new recruit with 0 XP. */
export function rankView(subject: Pick<SubjectLevel, "xp" | "level"> | undefined, levelXp: readonly number[] = LEVEL_XP): RankView {
  const curve = levelXp.length > 1 ? levelXp : LEVEL_XP;
  const xp = Math.max(0, subject?.xp ?? 0);
  const level = Math.max(1, Math.min(MAX_LEVEL, subject?.level ?? 1));
  const start = curve[level - 1] ?? 0;
  const end = curve[level];
  const atCap = level >= MAX_LEVEL || end === undefined;
  const size = atCap ? 0 : Math.max(1, end - start);
  const into = Math.max(0, xp - start);
  const next = nextRank(level);
  return {
    level, xp, rank: rankForLevel(level), next, into, size,
    fraction: atCap ? 1 : Math.max(0, Math.min(1, into / size)),
    toNextRank: next ? xpUntilLevel(curve, xp, next.level) : 0,
    atCap,
  };
}

export interface CrewMember {
  agentId: string;
  name: string;
}

export interface CrewRow extends CrewMember {
  subjectId: string;
  view: RankView;
}

/** The crew's ranks, highest level first, then by name. */
export function crewRows(crew: readonly CrewMember[], subjects: Readonly<Record<string, SubjectLevel>>, levelXp?: readonly number[]): CrewRow[] {
  return crew
    .map((member) => {
      const subjectId = `agent:${member.agentId}`;
      return { ...member, subjectId, view: rankView(subjects[subjectId], levelXp) };
    })
    .sort((a, b) => b.view.xp - a.view.xp || a.name.localeCompare(b.name));
}

/** Fill `{key}` placeholders. */
export function fill(template: string, vars: Readonly<Record<string, string | number>>): string {
  return template.replace(/\{(\w+)\}/g, (whole, key: string) => (key in vars ? String(vars[key]) : whole));
}

/** A number in the record's monospace style: grouped thousands, no decimals. */
export function figure(value: number): string {
  return Math.round(value).toLocaleString("en-US").replace(/,/g, " ");
}

/** The locale key naming an award's source; sources this build no longer pays share one word. */
export function sourceKey(source: string): string {
  return isXpSource(source) ? `verse.ranks.source.${source}` : "verse.ranks.source.retired";
}

export type LogFilter = (row: AwardRow) => boolean;

/** The newest awards of one subject, newest first. */
export function logOf(recent: readonly AwardRow[], subjectId: string, limit = 8): AwardRow[] {
  return recent.filter((row) => row.subjectId === subjectId).slice(-limit).reverse();
}

/** Rules grouped by who they pay, in rulebook order. */
export function rulesByKind(rules: readonly XpRuleRow[]): Record<SubjectKind, XpRuleRow[]> {
  const out: Record<SubjectKind, XpRuleRow[]> = { person: [], agent: [], pet: [] };
  for (const rule of rules) if (isXpSource(rule.source)) out[rule.kind].push(rule);
  return out;
}

/** "45 s" / "10 min" for a cooldown. */
export function cooldownText(seconds: number): string {
  return seconds >= 60 ? `${Math.round(seconds / 60)} min` : `${seconds} s`;
}
