/**
 * The level UI's pure side: every rank wears the insignia its ladder entry
 * promises, the catalog agrees with ranks.ts, destinations.ts and the Python
 * rulebook, and the record's lists (ladder, shelves, log, rules, crew) come
 * out in the order the dialog shows them.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { RANK_IDS, REWARD_IDS, SLOTS, XP_SOURCES, rewardKey, slotOf } from "../../progression/levelCatalog";
import type { AwardRow, RewardRow, XpRuleRow } from "../../progression/progressionApi";
import { DESTINATIONS } from "../space/destinations";
import { RANKS, rankFor } from "./ranks";
import {
  crewRanking, insigniaFor, isPromotion, nextReward, rankLadder, rewardShelves, ruleGroups, ruleLimit, shipLog, xpToReach,
} from "./levelModel";
import { fill, LEGACY_SOURCES, sourceKey } from "./levelText";

const RULES_PY = readFileSync(join(__dirname, "..", "..", "..", "..", "..", "..", "..", "..", "progression", "rules.py"), "utf8");

/** The person level of every reward in rules.py, by id. */
function pythonRewards(): Map<string, number | null> {
  const out = new Map<string, number | null>();
  for (const m of RULES_PY.matchAll(/Reward\("([a-z_]+)", "[a-z]+", person=(\d+|None)/g)) out.set(m[1], m[2] === "None" ? null : Number(m[2]));
  return out;
}

/** A full curve shaped like the server's (exact numbers do not matter here). */
const CURVE = Array.from({ length: 50 }, (_, i) => i * i * 20);

describe("insignia", () => {
  it("has a design for every rank, in the metal of its tier", () => {
    for (const rank of RANKS) {
      const spec = insigniaFor(rank.id);
      if (rank.tier === "enlisted") expect(["bar", "chevrons"]).toContain(spec.kind);
      if (rank.tier === "warrant") expect(spec).toEqual({ kind: "pips", solid: 1, hollow: 0, warrant: true });
      if (rank.tier === "officer") expect(spec.kind).toBe("pips");
      if (rank.tier === "flag") expect(spec.kind).toBe("flag");
      // Silver for the enlisted ranks only; gold from the warrant officer up.
      expect(rank.gold).toBe(rank.tier !== "enlisted");
    }
  });

  it("counts as many marks as the ladder's pips below the flag ranks", () => {
    for (const rank of RANKS.filter((r) => r.tier !== "flag")) {
      const spec = insigniaFor(rank.id);
      const marks = spec.kind === "bar" ? 0 : spec.kind === "chevrons" ? spec.count + (spec.rocker ? 1 : 0)
        : spec.kind === "pips" ? spec.solid + spec.hollow : 0;
      expect(marks, rank.id).toBe(rank.pips);
    }
  });

  it("follows the officers' ladder and gives the flag ranks one to four stars", () => {
    const pips = (id: string) => { const s = insigniaFor(id); return s.kind === "pips" ? [s.solid, s.hollow] : null; };
    expect(pips("ensign")).toEqual([1, 0]);
    expect(pips("lieutenant_junior_grade")).toEqual([1, 1]);
    expect(pips("lieutenant")).toEqual([2, 0]);
    expect(pips("lieutenant_commander")).toEqual([2, 1]);
    expect(pips("commander")).toEqual([3, 0]);
    expect(pips("captain")).toEqual([4, 0]);
    expect(["commodore", "rear_admiral", "vice_admiral", "admiral"].map((id) => insigniaFor(id))).toEqual(
      [1, 2, 3, 4].map((stars) => ({ kind: "flag", stars })));
    expect(insigniaFor("cadet")).toEqual({ kind: "bar" });
    expect(insigniaFor("general_of_the_army")).toEqual({ kind: "bar" });
  });

  it("tells a promotion from a level between two ranks", () => {
    expect(isPromotion(2, 3)).toBe(true);
    expect(isPromotion(3, 4)).toBe(false);
    expect(isPromotion(12, 17)).toBe(true);
  });
});

describe("the catalog", () => {
  it("lists the ranks of ranks.ts, lowest first", () => {
    expect([...RANK_IDS]).toEqual(RANKS.map((r) => r.id));
    expect(RANKS[0].level).toBe(1);
    expect(RANKS[RANKS.length - 1].level).toBe(50);
  });

  it("opens each destination at the level destinations.ts says, and the rulebook agrees", () => {
    const py = pythonRewards();
    expect([...py.keys()]).toEqual([...REWARD_IDS]);
    const fromCatalog = REWARD_IDS.filter((id) => slotOf(id) === "destination").map((id) => [rewardKey(id), py.get(id)]);
    expect(fromCatalog).toEqual(DESTINATIONS.filter((d) => d.id !== "home").map((d) => [d.id, d.level]));
    expect(DESTINATIONS[0]).toMatchObject({ id: "home", level: 1 });
  });

  it("names every reward by its slot", () => {
    for (const id of REWARD_IDS) expect(SLOTS).toContain(slotOf(id));
  });
});

const row = (rewardId: RewardRow["rewardId"], person: number | null, agent: number | null = null): RewardRow =>
  ({ rewardId, slot: slotOf(rewardId), levels: { person, agent, pet: null } });
const REWARDS: RewardRow[] = [
  row("suit_command_coat", 16), row("suit_field_armor", 6), row("destination_gas_giant", 5),
  row("destination_ice_moon", 15), row("decoration_service_ribbon", 8, 3),
];

describe("the record's lists", () => {
  it("measures what is missing on the curve", () => {
    expect(xpToReach(CURVE, 100, 4)).toBe(80);
    expect(xpToReach(CURVE, 999, 2)).toBe(0);
    expect(xpToReach(CURVE, 0, 99)).toBeNull();
  });

  it("lays out the ladder by tier with the viewer's place on it", () => {
    const groups = rankLadder(17, CURVE[16], CURVE);
    expect(groups.map((g) => g.tier)).toEqual(["enlisted", "warrant", "officer", "flag"]);
    expect(groups.flatMap((g) => g.rungs.map((r) => r.rank.id))).toEqual(RANKS.map((r) => r.id));
    const state = Object.fromEntries(groups.flatMap((g) => g.rungs.map((r) => [r.rank.id, r.state])));
    expect(state.cadet).toBe("held");
    expect(state.warrant_officer).toBe("held");
    expect(state.ensign).toBe("current");
    expect(state.lieutenant_junior_grade).toBe("ahead");
    const ltjg = groups[2].rungs.find((r) => r.rank.id === "lieutenant_junior_grade");
    expect(ltjg?.xpToGo).toBe(CURVE[18] - CURVE[16]);
    expect(rankFor(17).id).toBe("ensign");
  });

  it("puts each reward on its shelf in the order it opens, and finds the next one", () => {
    const shelves = rewardShelves(REWARDS, 10, CURVE[9], CURVE);
    expect(shelves.map((s) => [s.slot, s.items.map((i) => [i.reward.rewardId, i.open])])).toEqual([
      ["suit", [["suit_field_armor", true], ["suit_command_coat", false]]],
      ["destination", [["destination_gas_giant", true], ["destination_ice_moon", false]]],
      ["decoration", [["decoration_service_ribbon", true]]],
    ]);
    expect(nextReward(REWARDS, "person", 10)).toMatchObject({ level: 15, reward: { rewardId: "destination_ice_moon" } });
    expect(nextReward(REWARDS, "agent", 3)).toBeNull();
  });

  it("writes the ship's log newest first, for the captain and the companion only, without losing old sources", () => {
    const award = (seq: number, subjectId: string, source: string, ref = "", before = 1, after = 1): AwardRow =>
      ({ seq, subjectId, kind: subjectId === "person" ? "person" : subjectId.startsWith("pet:") ? "pet" : "agent", source, xp: 5, levelBefore: before, levelAfter: after, ref, tsMs: seq });
    const recent = [
      award(1, "person", "dog_petted"),
      award(2, "agent:scout", "task_done"),
      award(3, "person", "warp_jump", "ice_moon@1790000000000"),
      award(4, "person", "deck_discovered", "holodeck"),
      award(5, "pet:gigi", "jarvis_answered", "", 3, 4),
      award(6, "person", "chat_turn", "", 2, 3),
    ];
    const log = shipLog(recent, new Set(["person", "pet:gigi"]));
    expect(log.map((e) => [e.seq, e.line])).toEqual([
      [6, { kind: "promoted", rank: "crewman" }],
      [5, { kind: "level", level: 4 }],
      [4, { kind: "deck", deck: "holodeck" }],
      [3, { kind: "warp", destination: "ice_moon" }],
      [1, { kind: "source", source: "dog_petted" }],
    ]);
    expect(shipLog(recent, new Set(["person"]), 2).map((e) => e.seq)).toEqual([6, 4]);
  });

  it("reads every source in words, the office tower's too", () => {
    for (const source of XP_SOURCES) expect(sourceKey(source)).toBe(`ship.levels.source.${source}`);
    for (const source of LEGACY_SOURCES) expect(sourceKey(source)).toBe(`ship.levels.legacy_source.${source}`);
    expect(sourceKey("something_new")).toBe("ship.levels.legacy_source.other");
    expect(fill("{a} and {b}", { a: 1 })).toBe("1 and {b}");
  });

  it("groups the rules for the captain, the companion and the crew, richest first, with their limits", () => {
    const rule = (source: string, kind: XpRuleRow["kind"], xp: number, cooldownS = 0, dailyCap = 0): XpRuleRow =>
      ({ source, kind, xp, trigger: "world", cooldownS, dailyCap });
    const groups = ruleGroups([rule("chat_turn", "person", 5, 0, 100), rule("task_done", "agent", 40), rule("agent_hired", "person", 50),
      rule("walk_together", "pet", 3, 20, 60), rule("daily_visit", "person", 25), rule("deck_discovered", "person", 20)]);
    expect(groups.map((g) => [g.kind, g.rules.map((r) => r.rule.source)])).toEqual([
      ["person", ["agent_hired", "daily_visit", "deck_discovered", "chat_turn"]],
      ["pet", ["walk_together"]],
      ["agent", ["task_done"]],
    ]);
    expect(ruleLimit(rule("walk_together", "pet", 3, 20, 60))).toEqual({ kind: "metered", cooldownS: 20, dailyCap: 60 });
    expect(ruleLimit(rule("daily_visit", "person", 25))).toEqual({ kind: "once_day" });
    expect(ruleLimit(rule("task_done", "agent", 40))).toEqual({ kind: "none" });
  });

  it("ranks the crew best first and leaves the lead to the companion", () => {
    const agents = [
      { agentId: "jarvis", name: "Jarvis", tier: "lead" },
      { agentId: "a", name: "Ada", tier: "member" },
      { agentId: "b", name: "Bo", tier: "member" },
      { agentId: "c", name: "Cy", tier: "member" },
    ];
    const subject = (level: number, xp: number) => ({ subjectId: "", kind: "agent" as const, xp, level, xpIntoLevel: 0, xpForNext: 1, title: "" });
    const rows = crewRanking(agents, { "agent:a": subject(3, 50), "agent:b": subject(8, 400), "agent:c": subject(3, 60) });
    expect(rows.map((r) => [r.name, r.level, r.rank.id])).toEqual([["Bo", 8, "petty_officer"], ["Cy", 3, "crewman"], ["Ada", 3, "crewman"]]);
  });
});
