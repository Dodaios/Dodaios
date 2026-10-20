/**
 * The Verse's level state, shared by the rank card, the service record and
 * the promotion notice.
 *
 * The first read hydrates it; every `ProgressionAwarded` push applies one
 * award, queues a floating "+XP" over whoever earned it and, on a level-up,
 * a celebration: the promotion notice for the commander and the companion
 * drone, a quiet toast for an officer. Level-ups that happened while the
 * Verse was closed are told once per subject.
 */
import { create } from "zustand";
import type { AwardEvent, ProgressionSnapshot, SubjectLevel } from "./progressionApi";
import { PERSON_SUBJECT, rewardsOf } from "./progressionApi";
import { MAX_LEVEL, type RewardId, type SubjectKind } from "./levelCatalog";
import { loadUniformChoice, progressFor, rewardsBetween, saveUniformChoice, type UniformChoice } from "./cosmetics";
import { isPromotion } from "../verse/ranks/ranks";

export interface Celebration {
  id: number;
  subjectId: string;
  kind: SubjectKind;
  level: number;
  previousLevel: number;
  title: string;
  unlocked: RewardId[];
  /** Agent looks the level-up opened (agents only). */
  looks: string[];
  /** Earned while the Verse was closed: told, not staged. */
  away: boolean;
}

export interface XpPopup { id: number; subjectId: string; xp: number; bornMs: number }

/** How long a floating "+XP" lives, in ms. */
export const POPUP_MS = 1600;
/** How long the commander's figure salutes after their own promotion. */
export const CHEER_MS = 2200;
const MAX_POPUPS = 12;
const MAX_TOASTS = 4;

/** The service record's pages. */
export type ServiceTab = "record" | "ladder" | "rewards" | "earn" | "crew";
export const SERVICE_TABS: readonly ServiceTab[] = ["record", "ladder", "rewards", "earn", "crew"];

interface ProgressionState {
  snapshot: ProgressionSnapshot | null;
  subjects: Record<string, SubjectLevel>;
  petId: string;
  /** Commander and companion level-ups waiting for the notice, oldest first. */
  banners: Celebration[];
  /** Officer level-ups, newest last. */
  toasts: Celebration[];
  popups: XpPopup[];
  cheerUntil: number;
  /** The service record's open page; null = closed. */
  record: ServiceTab | null;
  uniform: UniformChoice;
  hydrate: (snapshot: ProgressionSnapshot, away: Celebration[]) => void;
  apply: (award: AwardEvent, nowMs?: number) => void;
  setPetId: (petId: string) => void;
  dismissBanner: () => void;
  dismissToast: (id: number) => void;
  expire: (nowMs: number) => void;
  openRecord: (tab: ServiceTab | null) => void;
  chooseUniform: (choice: UniformChoice) => void;
}

let nextId = 1;

export function celebrationOf(award: Pick<AwardEvent, "subjectId" | "kind" | "level" | "previousLevel" | "title" | "unlocked"> & { unlockedLooks?: string[] }, away = false): Celebration {
  return {
    id: nextId++, subjectId: award.subjectId, kind: award.kind, level: award.level, previousLevel: award.previousLevel,
    title: award.title, unlocked: award.unlocked, looks: award.unlockedLooks ?? [], away,
  };
}

/** Agent looks opened by a climb from `before` to `after`, in the order they unlock. */
export function looksBetween(looks: Readonly<Record<string, number>>, before: number, after: number): string[] {
  return Object.entries(looks ?? {}).filter(([, at]) => at > before && at <= after).sort((a, b) => a[1] - b[1]).map(([id]) => id);
}

export const useProgression = create<ProgressionState>((set, get) => ({
  snapshot: null,
  subjects: {},
  petId: "gigi",
  banners: [],
  toasts: [],
  popups: [],
  cheerUntil: 0,
  record: null,
  uniform: loadUniformChoice(),
  hydrate: (snapshot, away) => set((s) => {
    // A push can land before the read that was already on its way: never roll a subject back.
    const subjects: Record<string, SubjectLevel> = { ...s.subjects };
    for (const row of snapshot.subjects) {
      const known = subjects[row.subjectId];
      if (!known || known.xp <= row.xp) subjects[row.subjectId] = row;
    }
    // A push applied before the first read had no curve to measure the level by: measure it now.
    for (const [id, subject] of Object.entries(subjects)) {
      const atCap = subject.level >= snapshot.maxLevel;
      const { into, size } = progressFor(snapshot.levelXp, subject.xp, subject.level);
      if (!atCap && subject.xpForNext <= 0) subjects[id] = { ...subject, xpIntoLevel: into, xpForNext: size };
    }
    const banners = [...s.banners, ...away.filter((c) => c.kind !== "agent")];
    const toasts = [...s.toasts, ...away.filter((c) => c.kind === "agent")].slice(-MAX_TOASTS);
    return { snapshot, subjects, petId: snapshot.petId, banners, toasts };
  }),
  apply: (award, nowMs = performance.now()) => set((s) => {
    const known = s.subjects[award.subjectId];
    // A push older than what the subject already shows (a late duplicate) changes nothing.
    if (known && known.xp >= award.totalXp) return s;
    const curve = s.snapshot?.levelXp ?? [];
    const { into, size } = progressFor(curve, award.totalXp, award.level);
    const atCap = award.level >= (s.snapshot?.maxLevel ?? MAX_LEVEL);
    const subject: SubjectLevel = {
      subjectId: award.subjectId, kind: award.kind, xp: award.totalXp, level: award.level,
      xpIntoLevel: atCap ? 0 : into, xpForNext: atCap ? 0 : size, title: award.title,
    };
    const subjects = { ...s.subjects, [award.subjectId]: subject };
    const popups = [...s.popups, { id: nextId++, subjectId: award.subjectId, xp: award.xp, bornMs: nowMs }].slice(-MAX_POPUPS);
    // The award went to the ledger too: keep the snapshot's log current for the service record.
    const snapshot = s.snapshot && award.seq > s.snapshot.latestSeq ? {
      ...s.snapshot,
      latestSeq: award.seq,
      recent: [...s.snapshot.recent, {
        seq: award.seq, subjectId: award.subjectId, kind: award.kind, source: award.source, xp: award.xp,
        levelBefore: award.previousLevel, levelAfter: award.level, ref: "", tsMs: Date.now(),
      }].slice(-50),
    } : s.snapshot;
    if (award.level <= award.previousLevel) return { subjects, popups, snapshot };
    const party = celebrationOf(award);
    return {
      subjects,
      popups,
      snapshot,
      banners: award.kind === "agent" ? s.banners : [...s.banners, party],
      toasts: award.kind === "agent" ? [...s.toasts, party].slice(-MAX_TOASTS) : s.toasts,
      // The crew salutes a new rank, not every level on the way to it.
      cheerUntil: award.subjectId === PERSON_SUBJECT && isPromotion(award.previousLevel, award.level) ? nowMs + CHEER_MS : s.cheerUntil,
    };
  }),
  setPetId: (petId) => set((s) => (s.petId === petId || !petId ? s : { petId })),
  dismissBanner: () => set((s) => ({ banners: s.banners.slice(1) })),
  dismissToast: (id) => set((s) => ({ toasts: s.toasts.filter((t) => t.id !== id) })),
  expire: (nowMs) => {
    const s = get();
    const popups = s.popups.filter((p) => nowMs - p.bornMs < POPUP_MS);
    if (popups.length !== s.popups.length) set({ popups });
  },
  openRecord: (record) => set({ record }),
  chooseUniform: (uniform) => {
    saveUniformChoice(uniform);
    set({ uniform });
  },
}));

const SEEN_KEY = "jarvis.verse.levels.seen.v1";

/** The last award this browser has shown; null on a first visit. */
export function readSeenSeq(): number | null {
  try {
    const raw = typeof localStorage === "undefined" ? null : localStorage.getItem(SEEN_KEY);
    const value = raw === null ? NaN : Number(raw);
    return Number.isFinite(value) ? value : null;
  } catch (error) {
    console.debug("Verse level marker unavailable", error);
    return null;
  }
}

export function writeSeenSeq(seq: number): void {
  try {
    localStorage.setItem(SEEN_KEY, String(seq));
  } catch (error) {
    console.debug("Verse level marker not saved", error);
  }
}

/**
 * Level-ups that happened while the Verse was closed: the latest one per
 * subject, so a busy officer that climbed three levels is told once.
 */
export function awayCelebrations(snapshot: ProgressionSnapshot, seenSeq: number | null): Celebration[] {
  if (seenSeq === null) return [];
  const latest = new Map<string, Celebration>();
  for (const row of snapshot.recent) {
    if (row.seq <= seenSeq || row.levelAfter <= row.levelBefore) continue;
    const prior = latest.get(row.subjectId);
    const from = prior?.previousLevel ?? row.levelBefore;
    const subject = snapshot.subjects.find((s) => s.subjectId === row.subjectId);
    latest.set(row.subjectId, celebrationOf({
      subjectId: row.subjectId, kind: row.kind, level: row.levelAfter, previousLevel: from,
      title: subject?.title ?? "",
      unlocked: rewardsBetween(rewardsOf(snapshot), row.kind, from, row.levelAfter).map((r) => r.rewardId),
      unlockedLooks: row.kind === "agent" ? looksBetween(snapshot.looks, from, row.levelAfter) : [],
    }, true));
  }
  return [...latest.values()];
}
