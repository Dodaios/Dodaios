/**
 * The typed client of `/api/progression` (dodaios/ui/web/progression_routes.py)
 * and the shape of the `ProgressionAwarded` push the WebSocket forwards.
 *
 * Parsing is forgiving: a ledger row may carry a source this build no longer
 * knows (the office tower's `dog_petted`, `floor_discovered`, …); it is kept as
 * a plain string, never dropped and never fatal.
 */
import type { RankTier } from "../starship/levels/ranks";
import type { RewardId, Slot, SubjectKind, WorldAction } from "./levelCatalog";
import { isRewardId } from "./levelCatalog";

export interface SubjectLevel {
  subjectId: string;
  kind: SubjectKind;
  xp: number;
  level: number;
  xpIntoLevel: number;
  xpForNext: number;
  title: string;
}

export interface XpRuleRow {
  /** A rulebook source; a string, so a newer server's rule still reads. */
  source: string;
  kind: SubjectKind;
  xp: number;
  trigger: "server" | "world";
  cooldownS: number;
  dailyCap: number;
}

export interface RewardRow {
  rewardId: RewardId;
  slot: Slot;
  levels: Record<SubjectKind, number | null>;
}

export interface RankRow {
  id: string;
  level: number;
  tier: RankTier;
}

export interface AwardRow {
  seq: number;
  subjectId: string;
  kind: SubjectKind;
  source: string;
  xp: number;
  levelBefore: number;
  levelAfter: number;
  /** What the award was for: a deck, `<destination>@<ms>` for a warp jump, a quest id, … */
  ref: string;
  tsMs: number;
}

export interface ProgressionSnapshot {
  subjects: SubjectLevel[];
  petId: string;
  recent: AwardRow[];
  latestSeq: number;
  maxLevel: number;
  /** Total XP at which each level starts, index 0 = level 1. */
  levelXp: number[];
  rules: XpRuleRow[];
  rewards: RewardRow[];
  /** The rank ladder as the server has it (empty from a server older than the ship). */
  ranks: RankRow[];
  titles: Record<SubjectKind, { level: number; title: string }[]>;
  /** The agent level each wearable look opens at (companion accessory ids). */
  looks: Record<string, number>;
}

/** One `ProgressionAwarded` from the bus, as the WebSocket delivers it. */
export interface AwardEvent {
  seq: number;
  subjectId: string;
  kind: SubjectKind;
  source: string;
  xp: number;
  totalXp: number;
  level: number;
  previousLevel: number;
  title: string;
  unlocked: RewardId[];
  /** Agent looks this level-up opened. */
  unlockedLooks?: string[];
}

type Raw = Record<string, unknown>;
const num = (value: unknown, fallback = 0): number => (typeof value === "number" && Number.isFinite(value) ? value : fallback);
const str = (value: unknown): string => (typeof value === "string" ? value : "");
const kindOf = (value: unknown): SubjectKind => (value === "agent" || value === "pet" ? value : "person");
const tierOf = (value: unknown): RankTier => (value === "warrant" || value === "officer" || value === "flag" ? value : "enlisted");
const list = (value: unknown): Raw[] => (Array.isArray(value) ? value.filter((v): v is Raw => !!v && typeof v === "object") : []);

export function parseSnapshot(body: Raw): ProgressionSnapshot {
  const titles = (body.titles && typeof body.titles === "object" ? body.titles : {}) as Record<string, unknown>;
  const bands = (kind: SubjectKind) => list(titles[kind]).map((b) => ({ level: num(b.level, 1), title: str(b.title) }));
  return {
    subjects: list(body.subjects).map((row) => ({
      subjectId: str(row.subject_id), kind: kindOf(row.kind), xp: num(row.xp), level: num(row.level, 1),
      xpIntoLevel: num(row.xp_into_level), xpForNext: num(row.xp_for_next), title: str(row.title),
    })),
    petId: str(body.pet_id) || "gigi",
    recent: list(body.recent).map((row) => ({
      seq: num(row.seq), subjectId: str(row.subject_id), kind: kindOf(row.kind), source: str(row.source), xp: num(row.xp),
      levelBefore: num(row.level_before, 1), levelAfter: num(row.level_after, 1), ref: str(row.ref), tsMs: num(row.ts_ms),
    })),
    latestSeq: num(body.latest_seq),
    maxLevel: num(body.max_level, 50),
    levelXp: Array.isArray(body.level_xp) ? body.level_xp.map((v) => num(v)) : [0],
    rules: list(body.rules).map((row) => ({
      source: str(row.source), kind: kindOf(row.kind), xp: num(row.xp),
      trigger: row.trigger === "world" ? "world" : "server", cooldownS: num(row.cooldown_s), dailyCap: num(row.daily_cap),
    })),
    // A reward id this build does not know (an older or newer server's) is left out: nothing could draw it.
    rewards: list(body.rewards).filter((row) => isRewardId(row.reward_id)).map((row) => {
      const levels = (row.levels && typeof row.levels === "object" ? row.levels : {}) as Raw;
      const at = (kind: SubjectKind) => (typeof levels[kind] === "number" ? (levels[kind] as number) : null);
      return { rewardId: row.reward_id as RewardId, slot: str(row.slot) as Slot, levels: { person: at("person"), agent: at("agent"), pet: at("pet") } };
    }),
    ranks: list(body.ranks).filter((row) => str(row.id)).map((row) => ({ id: str(row.id), level: num(row.level, 1), tier: tierOf(row.tier) })),
    titles: { person: bands("person"), agent: bands("agent"), pet: bands("pet") },
    looks: Object.fromEntries(list(body.looks).filter((row) => str(row.look_id)).map((row) => [str(row.look_id), num(row.agent, 1)])),
  };
}

export function parseAwardEvent(payload: unknown): AwardEvent | null {
  if (!payload || typeof payload !== "object") return null;
  const p = payload as Raw;
  const subjectId = str(p.subject_id);
  if (!subjectId) return null;
  return {
    seq: num(p.seq), subjectId, kind: kindOf(p.subject_kind), source: str(p.xp_source), xp: num(p.xp),
    totalXp: num(p.total_xp), level: num(p.level, 1), previousLevel: num(p.previous_level, 1), title: str(p.title),
    unlocked: Array.isArray(p.unlocked) ? p.unlocked.filter(isRewardId) : [],
    unlockedLooks: Array.isArray(p.unlocked_looks) ? p.unlocked_looks.filter((v): v is string => typeof v === "string") : [],
  };
}

export async function fetchProgression(afterSeq = 0): Promise<ProgressionSnapshot> {
  const res = await fetch(`/api/progression${afterSeq > 0 ? `?after_seq=${afterSeq}` : ""}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return parseSnapshot((await res.json()) as Raw);
}

/**
 * The office tower's arcade names, still sent by the shared retro games:
 * they are the holodeck's rounds now.
 */
const RENAMED_ACTIONS = { arcade_round: "holodeck_round", arcade_record: "holodeck_record" } as const satisfies Record<string, WorldAction>;
export type RenamedAction = keyof typeof RENAMED_ACTIONS;

/** Report a world action; the server decides whether it pays. Never throws; a report the server refuses is logged. */
export async function reportWorldAction(action: WorldAction | RenamedAction, ref = ""): Promise<void> {
  const name: WorldAction = action in RENAMED_ACTIONS ? RENAMED_ACTIONS[action as RenamedAction] : (action as WorldAction);
  try {
    const res = await fetch("/api/progression/actions", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: name, ref }),
    });
    // A refusal means this client and the server disagree about an action or a deck: say so, play on.
    if (!res.ok) console.warn("Level action refused", name, ref, res.status);
  } catch (error) {
    // XP is a garnish: an unreachable backend never disturbs the ship.
    console.debug("Level action not reported", name, error);
  }
}

export const agentSubject = (agentId: string): string => `agent:${agentId}`;
export const petSubject = (petId: string): string => `pet:${petId}`;
export const PERSON_SUBJECT = "person";
