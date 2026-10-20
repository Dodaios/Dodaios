/**
 * The Verse's level data layer: the API parses forgivingly (old ledger
 * sources, an older server's rank and reward ids), the store applies awards
 * once and celebrates the right way per kind, the cosmetics pick the
 * commander's uniform, and the client's copy of the curve and the rewards
 * reads like the server's.
 */
import { beforeEach, describe, expect, it } from "vitest";
import { issuedUniforms, levelFraction, progressFor, rewardRoad, rewardsBetween, uniformFor, unlockedFor, xpUntilLevel } from "./cosmetics";
import { LEVEL_XP, MAX_LEVEL, REWARD_IDS, REWARD_LEVELS, levelForXp, slotOf, xpToNext } from "./levelCatalog";
import { LOCAL_REWARDS, parseAwardEvent, parseSnapshot, rewardsOf, type ProgressionSnapshot } from "./progressionApi";
import { CHEER_MS, awayCelebrations, looksBetween, useProgression } from "./progressionStore";

/** The rulebook's `level_xp` (total_xp_for_level for levels 1..50), unchanged since the first build. */
const RULEBOOK_LEVEL_XP = [
  0, 40, 105, 200, 325, 480, 665, 885, 1140, 1425, 1745, 2100, 2490, 2915, 3375, 3870, 4400, 4970, 5575, 6215,
  6895, 7610, 8360, 9150, 9975, 10840, 11740, 12680, 13660, 14675, 15730, 16825, 17960, 19130, 20340, 21590,
  22880, 24210, 25575, 26980, 28425, 29910, 31435, 33000, 34605, 36250, 37935, 39660, 41425, 43230,
];
const CURVE = RULEBOOK_LEVEL_XP.slice(0, 12);

function snapshot(over: Partial<ProgressionSnapshot> = {}): ProgressionSnapshot {
  return {
    subjects: [], petId: "gigi", recent: [], latestSeq: 0, maxLevel: 50, levelXp: [...LEVEL_XP], rules: [], rewards: [...LOCAL_REWARDS],
    ranks: [], titles: { person: [], agent: [], pet: [] }, looks: {}, ...over,
  };
}

describe("levelCatalog", () => {
  it("keeps the rulebook's curve", () => {
    expect([1, 2, 10, 49].map(xpToNext)).toEqual([40, 65, 320, 1805]);
    expect(xpToNext(MAX_LEVEL)).toBe(0);
    expect(LEVEL_XP).toHaveLength(MAX_LEVEL);
    expect(LEVEL_XP[MAX_LEVEL - 1]).toBe(43_230);
    expect(LEVEL_XP).toEqual(RULEBOOK_LEVEL_XP);
    expect(levelForXp(0)).toBe(1);
    expect(levelForXp(39)).toBe(1);
    expect(levelForXp(40)).toBe(2);
    expect(levelForXp(1745)).toBe(11);
    expect(levelForXp(10_000_000)).toBe(MAX_LEVEL);
  });

  it("names every reward by a slot it knows and gives each a level for the commander", () => {
    for (const id of REWARD_IDS) {
      expect(["uniform", "ribbon"]).toContain(slotOf(id));
      expect(REWARD_LEVELS[id].person).not.toBeNull();
    }
  });
});

describe("progressionApi", () => {
  it("parses the snapshot, keeps old sources and drops an older server's rewards", () => {
    const parsed = parseSnapshot({
      subjects: [{ subject_id: "person", kind: "person", xp: 120, level: 3, xp_into_level: 15, xp_for_next: 90, title: "crewman" }],
      recent: [{ seq: 4, subject_id: "person", kind: "person", source: "warp_jump", xp: 5, level_before: 3, level_after: 3, ref: "home@1", ts_ms: 9 }],
      rewards: [{ reward_id: "suit_field_armor", slot: "suit", levels: { person: 6, agent: null, pet: null } },
        { reward_id: "uniform_line", slot: "uniform", levels: { person: 11, agent: null, pet: null } }],
      ranks: [{ id: "cadet", level: 1, tier: "enlisted" }, { id: "fleet_admiral", level: 50, tier: "flag" }, { id: "", level: 2 }],
      rules: [{ source: "holodeck_round", kind: "person", xp: 8, trigger: "world", cooldown_s: 45, daily_cap: 80 }],
      level_xp: CURVE, max_level: 50, pet_id: "miso", latest_seq: 4,
    });
    expect(parsed.recent[0]).toMatchObject({ source: "warp_jump", ref: "home@1" });
    expect(parsed.rewards.map((r) => r.rewardId)).toEqual(["uniform_line"]);
    // An older server's tier names read as the lowest tier; the Verse derives ranks from levels anyway.
    expect(parsed.ranks).toEqual([{ id: "cadet", level: 1, tier: "deck" }, { id: "fleet_admiral", level: 50, tier: "flag" }]);
    expect(parsed.rules[0].source).toBe("holodeck_round");
    expect(parsed.petId).toBe("miso");
    expect(parseSnapshot({}).ranks).toEqual([]);
  });

  it("falls back to the client's rewards when the server sends none it knows", () => {
    const old = parseSnapshot({ rewards: [{ reward_id: "suit_field_armor", slot: "suit", levels: { person: 6 } }] });
    expect(old.rewards).toEqual([]);
    expect(rewardsOf(old)).toBe(LOCAL_REWARDS);
    expect(rewardsOf(null).map((r) => r.rewardId)).toEqual([...REWARD_IDS]);
    const current = snapshot({ rewards: [LOCAL_REWARDS[1]] });
    expect(rewardsOf(current)).toEqual([LOCAL_REWARDS[1]]);
  });

  it("parses a push and keeps only reward ids it knows", () => {
    const award = parseAwardEvent({ subject_id: "agent:scout", subject_kind: "agent", xp_source: "task_done", xp: 40, total_xp: 300,
      level: 4, previous_level: 3, title: "deckhand", unlocked: ["ribbon_good_conduct", "decoration_service_ribbon"], seq: 7 });
    expect(award).toMatchObject({ kind: "agent", level: 4, unlocked: ["ribbon_good_conduct"] });
    expect(parseAwardEvent({})).toBeNull();
  });
});

describe("cosmetics", () => {
  it("opens rewards by level and orders the road", () => {
    expect(unlockedFor(LOCAL_REWARDS, "person", 6).map((r) => r.rewardId)).toEqual(["uniform_deck", "ribbon_good_conduct"]);
    expect(rewardRoad(LOCAL_REWARDS, "agent").map((r) => r.rewardId)).toEqual([
      "ribbon_good_conduct", "ribbon_meritorious", "ribbon_distinguished", "ribbon_fleet_cross",
    ]);
    expect(rewardRoad(LOCAL_REWARDS, "pet")).toEqual([]);
    expect(rewardsBetween(LOCAL_REWARDS, "person", 5, 12).map((r) => r.rewardId)).toEqual(["ribbon_good_conduct", "uniform_line"]);
  });

  it("issues the uniforms by tier and wears the highest unless the commander chose", () => {
    expect(issuedUniforms(LOCAL_REWARDS, 1)).toEqual(["deck"]);
    expect(issuedUniforms(LOCAL_REWARDS, 30)).toEqual(["deck", "line", "command"]);
    expect(issuedUniforms([], 30)).toEqual(["deck"]);
    expect(uniformFor(LOCAL_REWARDS, 1)).toBe("deck");
    expect(uniformFor(LOCAL_REWARDS, 12)).toBe("line");
    expect(uniformFor(LOCAL_REWARDS, 40, "line")).toBe("line");
    expect(uniformFor(LOCAL_REWARDS, 12, "flag")).toBe("line");
    expect(uniformFor(LOCAL_REWARDS, MAX_LEVEL)).toBe("flag");
  });

  it("measures the bar on the server's curve, or on the client's without one", () => {
    expect(progressFor(CURVE, 120, 3)).toEqual({ into: 15, size: 95 });
    expect(progressFor([], 120, 3)).toEqual({ into: 15, size: 95 });
    expect(progressFor(LEVEL_XP, 50_000, MAX_LEVEL)).toEqual({ into: 50_000 - 43_230, size: 0 });
    expect(xpUntilLevel(LEVEL_XP, 100, 3)).toBe(5);
    expect(xpUntilLevel(LEVEL_XP, 900, 3)).toBe(0);
    expect(levelFraction({ xpIntoLevel: 45, xpForNext: 90 })).toBe(0.5);
    expect(levelFraction({ xpIntoLevel: 0, xpForNext: 0 })).toBe(1);
  });
});

describe("progressionStore", () => {
  beforeEach(() => {
    useProgression.setState({ snapshot: null, subjects: {}, banners: [], toasts: [], popups: [], cheerUntil: 0, record: null });
  });

  it("applies an award once, logs it and celebrates per kind", () => {
    useProgression.getState().hydrate(snapshot(), []);
    const push = { seq: 1, subjectId: "person", kind: "person" as const, source: "chat_turn", xp: 5, totalXp: 45, level: 2, previousLevel: 1, title: "recruit", unlocked: [] };
    useProgression.getState().apply(push, 100);
    useProgression.getState().apply(push, 200);
    const s = useProgression.getState();
    expect(s.subjects.person).toMatchObject({ xp: 45, level: 2, xpIntoLevel: 5, xpForNext: 65 });
    expect(s.banners).toHaveLength(1);
    expect(s.popups).toHaveLength(1);
    // Level 2 is still a recruit: a level-up, not a promotion, so nobody salutes.
    expect(s.cheerUntil).toBe(0);
    expect(s.snapshot?.recent.map((r) => r.source)).toEqual(["chat_turn"]);
    useProgression.getState().apply({ ...push, seq: 2, subjectId: "agent:scout", kind: "agent", totalXp: 45 }, 300);
    expect(useProgression.getState().toasts).toHaveLength(1);
    expect(useProgression.getState().banners).toHaveLength(1);
  });

  it("salutes the commander on a promotion only", () => {
    useProgression.getState().hydrate(snapshot(), []);
    const push = { seq: 1, subjectId: "person", kind: "person" as const, source: "chat_turn", xp: 5, totalXp: 45, level: 2, previousLevel: 1, title: "recruit", unlocked: [] };
    useProgression.getState().apply(push, 100);
    expect(useProgression.getState().cheerUntil).toBe(0);
    // An officer's promotion is theirs: the commander's crew does not salute it.
    useProgression.getState().apply({ ...push, seq: 2, subjectId: "agent:scout", kind: "agent", totalXp: 120, level: 3, previousLevel: 2 }, 200);
    expect(useProgression.getState().cheerUntil).toBe(0);
    // Level 3 makes the commander a deckhand: a new rank.
    useProgression.getState().apply({ ...push, seq: 3, totalXp: 120, level: 3, previousLevel: 2, title: "deckhand" }, 300);
    expect(useProgression.getState().cheerUntil).toBe(300 + CHEER_MS);
    // The next level keeps the rank: a salute already under way is left alone.
    useProgression.getState().apply({ ...push, seq: 4, totalXp: 215, level: 4, previousLevel: 3, title: "deckhand" }, 400);
    expect(useProgression.getState().cheerUntil).toBe(300 + CHEER_MS);
  });

  it("measures a push that lands before the first read on the client's curve", () => {
    useProgression.getState().apply({ seq: 1, subjectId: "person", kind: "person", source: "chat_turn", xp: 5, totalXp: 120, level: 3, previousLevel: 3, title: "", unlocked: [] }, 0);
    expect(useProgression.getState().subjects.person).toMatchObject({ xpIntoLevel: 15, xpForNext: 95 });
  });

  it("tells the level-ups missed while away once per subject, with what opened", () => {
    const snap = snapshot({
      subjects: [{ subjectId: "person", kind: "person", xp: 1800, level: 11, xpIntoLevel: 55, xpForNext: 380, title: "ensign" }],
      recent: [
        { seq: 3, subjectId: "person", kind: "person", source: "chat_turn", xp: 5, levelBefore: 4, levelAfter: 5, ref: "", tsMs: 1 },
        { seq: 4, subjectId: "person", kind: "person", source: "chat_turn", xp: 5, levelBefore: 10, levelAfter: 11, ref: "", tsMs: 2 },
      ],
    });
    expect(awayCelebrations(snap, null)).toEqual([]);
    const away = awayCelebrations(snap, 2);
    expect(away).toHaveLength(1);
    expect(away[0]).toMatchObject({ level: 11, previousLevel: 4, away: true, unlocked: ["ribbon_good_conduct", "uniform_line"] });
    // An older server sent no rewards this build knows: the client's own table names what opened.
    const old = awayCelebrations({ ...snap, rewards: [] }, 2);
    expect(old[0].unlocked).toEqual(["ribbon_good_conduct", "uniform_line"]);
    expect(looksBetween({ cap: 1, crown: 10 }, 1, 10)).toEqual(["crown"]);
  });

  it("opens and closes the service record and remembers the uniform", () => {
    useProgression.getState().openRecord("ladder");
    expect(useProgression.getState().record).toBe("ladder");
    useProgression.getState().openRecord(null);
    expect(useProgression.getState().record).toBeNull();
    useProgression.getState().chooseUniform("line");
    expect(useProgression.getState().uniform).toBe("line");
    useProgression.getState().chooseUniform("auto");
  });
});
