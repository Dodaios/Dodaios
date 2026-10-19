/**
 * The ship's level data layer: the API parses forgivingly (old ledger
 * sources, unknown rewards, the new rank list), the store applies awards
 * once and celebrates the right way per kind, and the cosmetics pick the
 * captain's suit.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { levelFraction, progressFor, rewardRoad, rewardsBetween, suitFor, unlockedFor } from "./cosmetics";
import { REWARD_IDS, slotOf } from "./levelCatalog";
import { parseAwardEvent, parseSnapshot, type ProgressionSnapshot, type RewardRow } from "./progressionApi";
import { awayCelebrations, looksBetween, useProgression } from "./progressionStore";

const CURVE = [0, 40, 105, 195, 310, 450, 615, 805, 1020, 1260];
const row = (rewardId: RewardRow["rewardId"], person: number | null, agent: number | null = null): RewardRow =>
  ({ rewardId, slot: slotOf(rewardId), levels: { person, agent, pet: null } });
const REWARDS: RewardRow[] = [
  row("suit_field_armor", 6), row("suit_command_coat", 16), row("destination_gas_giant", 5),
  row("decoration_service_ribbon", 8, 3),
];

function snapshot(over: Partial<ProgressionSnapshot> = {}): ProgressionSnapshot {
  return {
    subjects: [], petId: "gigi", recent: [], latestSeq: 0, maxLevel: 50, levelXp: CURVE, rules: [], rewards: REWARDS,
    ranks: [], titles: { person: [], agent: [], pet: [] }, looks: {}, ...over,
  };
}

describe("progressionApi", () => {
  it("parses the snapshot with the ship's ranks, keeps old sources and drops unknown rewards", () => {
    const parsed = parseSnapshot({
      subjects: [{ subject_id: "person", kind: "person", xp: 120, level: 3, xp_into_level: 15, xp_for_next: 90, title: "crewman" }],
      recent: [{ seq: 4, subject_id: "person", kind: "person", source: "dog_petted", xp: 3, level_before: 3, level_after: 3, ref: "", ts_ms: 9 }],
      rewards: [{ reward_id: "suit_field_armor", slot: "suit", levels: { person: 6, agent: null, pet: null } },
        { reward_id: "uniform_dress_blues", slot: "uniform", levels: { person: 26 } }],
      ranks: [{ id: "cadet", level: 1, tier: "enlisted" }, { id: "admiral", level: 50, tier: "flag" }, { id: "", level: 2 }],
      rules: [{ source: "arcade_round", kind: "person", xp: 8, trigger: "world", cooldown_s: 45, daily_cap: 80 }],
      level_xp: CURVE, max_level: 50, pet_id: "miso", latest_seq: 4,
    });
    expect(parsed.recent[0]).toMatchObject({ source: "dog_petted", ref: "" });
    expect(parsed.rewards.map((r) => r.rewardId)).toEqual(["suit_field_armor"]);
    expect(parsed.ranks).toEqual([{ id: "cadet", level: 1, tier: "enlisted" }, { id: "admiral", level: 50, tier: "flag" }]);
    expect(parsed.rules[0].source).toBe("arcade_round");
    expect(parsed.petId).toBe("miso");
    // A server older than the ship sends no ranks.
    expect(parseSnapshot({}).ranks).toEqual([]);
  });

  it("parses a push and keeps only reward ids it knows", () => {
    const award = parseAwardEvent({ subject_id: "agent:scout", subject_kind: "agent", xp_source: "task_done", xp: 40, total_xp: 45,
      level: 2, previous_level: 1, title: "cadet", unlocked: ["decoration_service_ribbon", "decoration_medals"], seq: 7 });
    expect(award).toMatchObject({ kind: "agent", level: 2, unlocked: ["decoration_service_ribbon"] });
    expect(parseAwardEvent({})).toBeNull();
  });
});

describe("cosmetics", () => {
  it("opens rewards by level and orders the road", () => {
    expect(unlockedFor(REWARDS, "person", 6).map((r) => r.rewardId)).toEqual(["suit_field_armor", "destination_gas_giant"]);
    expect(rewardRoad(REWARDS, "agent").map((r) => r.rewardId)).toEqual(["decoration_service_ribbon"]);
    expect(rewardsBetween(REWARDS, "person", 5, 8).map((r) => r.rewardId)).toEqual(["suit_field_armor", "decoration_service_ribbon"]);
  });

  it("wears the finest open suit unless the captain chose", () => {
    expect(suitFor(REWARDS, 1)).toBeNull();
    expect(suitFor(REWARDS, 20)).toBe("suit_command_coat");
    expect(suitFor(REWARDS, 20, "suit_field_armor")).toBe("suit_field_armor");
    expect(suitFor(REWARDS, 10, "suit_command_coat")).toBe("suit_field_armor");
    expect(suitFor(REWARDS, 20, "none")).toBeNull();
  });

  it("measures the bar on the server's curve", () => {
    expect(progressFor(CURVE, 120, 3)).toEqual({ into: 15, size: 90 });
    expect(progressFor(CURVE, 2000, 10)).toEqual({ into: 740, size: 0 });
    expect(levelFraction({ xpIntoLevel: 45, xpForNext: 90 })).toBe(0.5);
    expect(levelFraction({ xpIntoLevel: 0, xpForNext: 0 })).toBe(1);
  });

  it("names every reward by a slot the catalog knows", () => {
    for (const id of REWARD_IDS) expect(["suit", "destination", "decoration"]).toContain(slotOf(id));
  });
});

describe("progressionStore", () => {
  beforeEach(() => {
    useProgression.setState({ snapshot: null, subjects: {}, banners: [], toasts: [], popups: [], cheerUntil: 0, record: null });
  });

  it("applies an award once, logs it and celebrates per kind", () => {
    useProgression.getState().hydrate(snapshot(), []);
    const push = { seq: 1, subjectId: "person", kind: "person" as const, source: "chat_turn", xp: 5, totalXp: 45, level: 2, previousLevel: 1, title: "cadet", unlocked: [] };
    useProgression.getState().apply(push, 100);
    useProgression.getState().apply(push, 200);
    const s = useProgression.getState();
    expect(s.subjects.person).toMatchObject({ xp: 45, level: 2, xpIntoLevel: 5, xpForNext: 65 });
    expect(s.banners).toHaveLength(1);
    expect(s.popups).toHaveLength(1);
    expect(s.cheerUntil).toBeGreaterThan(100);
    expect(s.snapshot?.recent.map((r) => r.source)).toEqual(["chat_turn"]);
    useProgression.getState().apply({ ...push, seq: 2, subjectId: "agent:scout", kind: "agent", totalXp: 45 }, 300);
    expect(useProgression.getState().toasts).toHaveLength(1);
    expect(useProgression.getState().banners).toHaveLength(1);
  });

  it("tells the level-ups missed while away once per subject, with what opened", () => {
    const snap = snapshot({
      subjects: [{ subjectId: "person", kind: "person", xp: 700, level: 7, xpIntoLevel: 85, xpForNext: 190, title: "petty_officer" }],
      recent: [
        { seq: 3, subjectId: "person", kind: "person", source: "chat_turn", xp: 5, levelBefore: 4, levelAfter: 5, ref: "", tsMs: 1 },
        { seq: 4, subjectId: "person", kind: "person", source: "chat_turn", xp: 5, levelBefore: 6, levelAfter: 7, ref: "", tsMs: 2 },
      ],
    });
    expect(awayCelebrations(snap, null)).toEqual([]);
    const away = awayCelebrations(snap, 2);
    expect(away).toHaveLength(1);
    expect(away[0]).toMatchObject({ level: 7, previousLevel: 4, away: true, unlocked: ["destination_gas_giant", "suit_field_armor"] });
    expect(looksBetween({ cap: 1, crown: 10 }, 1, 10)).toEqual(["crown"]);
  });

  it("opens and closes the service record and remembers the suit", () => {
    useProgression.getState().openRecord("ranks");
    expect(useProgression.getState().record).toBe("ranks");
    useProgression.getState().openRecord(null);
    expect(useProgression.getState().record).toBeNull();
    useProgression.getState().chooseSuit("none");
    expect(useProgression.getState().suit).toBe("none");
  });
});
