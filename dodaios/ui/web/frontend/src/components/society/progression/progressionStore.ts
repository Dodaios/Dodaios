/**
 * The ship's level state, shared by the HUD, the service record and the
 * promotion layer.
 *
 * The first read hydrates it; every `ProgressionAwarded` push applies one
 * award, queues a floating "+XP" over whoever earned it and, on a level-up,
 * a celebration: the promotion ceremony for the captain and the pet, a quiet
 * toast for an android. Level-ups that happened while the ship was closed are
 * told once per subject.
 */
import { create } from "zustand";
import type { AwardEvent, ProgressionSnapshot, SubjectLevel } from "./progressionApi";
import { PERSON_SUBJECT } from "./progressionApi";
import type { RewardId, SubjectKind } from "./levelCatalog";
import { loadSuitChoice, progressFor, rewardsBetween, saveSuitChoice, type SuitChoice } from "./cosmetics";

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
  /** Earned while the ship was closed: told, not staged. */
  away: boolean;
}

export interface XpPopup { id: number; subjectId: string; xp: number; bornMs: number }

/** How long a floating "+XP" lives, in ms. */
export const POPUP_MS = 1600;
/** How long the captain's figure cheers after their own level-up. */
export const CHEER_MS = 2200;
const MAX_POPUPS = 12;
const MAX_TOASTS = 4;

/** The service record's pages. */
export type ServiceTab = "record" | "ranks" | "rewards" | "earn" | "crew";
export const SERVICE_TABS: readonly ServiceTab[] = ["record", "ranks", "rewards", "earn", "crew"];

interface ProgressionState {
  snapshot: ProgressionSnapshot | null;
  subjects: Record<string, SubjectLevel>;
  petId: string;
  /** Captain and pet level-ups waiting for the ceremony, oldest first. */
  banners: Celebration[];
  /** Android level-ups, newest last. */
  toasts: Celebration[];
  popups: XpPopup[];
  cheerUntil: number;
  /** The service record's open page; null = closed. */
  record: ServiceTab | null;
  suit: SuitChoice;
  hydrate: (snapshot: ProgressionSnapshot, away: Celebration[]) => void;
  apply: (award: AwardEvent, nowMs?: number) => void;
  setPetId: (petId: string) => void;
  dismissBanner: () => void;
  dismissToast: (id: number) => void;
  expire: (nowMs: number) => void;
  openRecord: (tab: ServiceTab | null) => void;
  chooseSuit: (choice: SuitChoice) => void;
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
  suit: loadSuitChoice(),
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
    const atCap = s.snapshot ? award.level >= s.snapshot.maxLevel : false;
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
      cheerUntil: award.subjectId === PERSON_SUBJECT ? nowMs + CHEER_MS : s.cheerUntil,
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
  chooseSuit: (suit) => {
    saveSuitChoice(suit);
    set({ suit });
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
    console.debug("Ship level marker unavailable", error);
    return null;
  }
}

export function writeSeenSeq(seq: number): void {
  try {
    localStorage.setItem(SEEN_KEY, String(seq));
  } catch (error) {
    console.debug("Ship level marker not saved", error);
  }
}

/**
 * Level-ups that happened while the ship was closed: the latest one per
 * subject, so a busy android that climbed three levels is told once.
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
      unlocked: rewardsBetween(snapshot.rewards, row.kind, from, row.levelAfter).map((r) => r.rewardId),
      unlockedLooks: row.kind === "agent" ? looksBetween(snapshot.looks, from, row.levelAfter) : [],
    }, true));
  }
  return [...latest.values()];
}
