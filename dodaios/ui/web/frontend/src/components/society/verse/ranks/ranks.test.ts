/**
 * The ladder, the plates and the duty model: the frontend's ladder equals the
 * rulebook's (read straight from dodaios/progression/rules.py), every rank has
 * its own plate, ranks follow levels, and the duty status reads the real run
 * states the way the brief says.
 */
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { LEVEL_XP, MAX_LEVEL } from "../../progression/levelCatalog";
import { DUTY, DUTY_ORDER, DUTY_STATUSES, dutyCounts, dutyOf, dutyOfPane, isDutyStatus } from "./dutyStatus";
import { rankView, crewRows, fill, figure, logOf, sourceKey } from "./rankModel";
import {
  RANK_IDS, RANK_TIERS, RANKS, TIER_STYLE, isPromotion, isRankId, nextRank, plateTiles, rankBadge, rankForLevel, ranksOfTier,
  tierOf, tierStart, uniformForLevel,
} from "./ranks";
import { RIBBON_STRIPES } from "./Ribbon";
import { NO_SIGNALS, applyDutyEvent } from "./useRanks";

const RULES_PY = join(__dirname, "..", "..", "..", "..", "..", "..", "..", "..", "progression", "rules.py");

/** `RANKS` as the backend declares it: (level, id, tier). */
function serverLadder(): [number, string, string][] {
  // A Windows checkout may hold the file with CRLF line endings.
  const py = readFileSync(RULES_PY, "utf8").replace(/\r\n/g, "\n");
  const block = /^RANKS: Final\[[^\n]*\] = \(\n([\s\S]*?)\n\)/m.exec(py);
  if (!block) throw new Error("RANKS is no longer a tuple literal in dodaios/progression/rules.py");
  return [...block[1].matchAll(/\((\d+), "([a-z_]+)", "([a-z]+)"\)/g)].map((m) => [Number(m[1]), m[2], m[3]]);
}

describe("the ladder", () => {
  it("is the rulebook's, rank for rank", () => {
    const server = serverLadder();
    expect(server).toHaveLength(15);
    expect(RANKS.map((r) => [r.level, r.id, r.tier])).toEqual(server);
    expect([...RANK_IDS]).toEqual(server.map(([, id]) => id));
  });

  it("climbs from recruit at 1 to fleet admiral at the cap, tiers in order", () => {
    expect(RANKS[0]).toMatchObject({ id: "recruit", level: 1, tier: "deck" });
    expect(RANKS[RANKS.length - 1]).toMatchObject({ id: "fleet_admiral", level: MAX_LEVEL, tier: "flag" });
    const tiers = RANKS.map((r) => RANK_TIERS.indexOf(r.tier));
    expect(tiers).toEqual([...tiers].sort((a, b) => a - b));
    expect(RANK_TIERS.map(tierStart)).toEqual([1, 11, 29, 37]);
    expect(ranksOfTier("command").map((r) => r.id)).toEqual(["line_captain", "commodore"]);
  });

  it("derives the rank from the level alone", () => {
    expect(rankForLevel(0).id).toBe("recruit");
    expect(rankForLevel(2).id).toBe("recruit");
    expect(rankForLevel(3).id).toBe("deckhand");
    expect(rankForLevel(10).id).toBe("senior_technician");
    expect(rankForLevel(11).id).toBe("ensign");
    expect(rankForLevel(36).id).toBe("commodore");
    expect(rankForLevel(49).id).toBe("admiral");
    expect(rankForLevel(50).id).toBe("fleet_admiral");
    expect(nextRank(11)?.id).toBe("lieutenant");
    expect(nextRank(50)).toBeUndefined();
    expect(tierOf("captain")).toBe("line");
    expect(isRankId("cadet")).toBe(false);
    expect(isRankId("commodore")).toBe(true);
  });

  it("calls a climb a promotion only when the rank changes", () => {
    expect(isPromotion(2, 3)).toBe(true);
    expect(isPromotion(3, 4)).toBe(false);
    expect(isPromotion(9, 12)).toBe(true);
    expect(isPromotion(12, 12)).toBe(false);
    expect(isPromotion(14, 13)).toBe(false);
  });

  it("dresses each tier in its own uniform", () => {
    expect([1, 11, 29, 37, 50].map(uniformForLevel)).toEqual(["deck", "line", "command", "flag", "flag"]);
    expect(new Set(RANK_TIERS.map((tier) => TIER_STYLE[tier].tile)).size).toBe(4);
  });
});

describe("the rank plate", () => {
  it("lights a different, left-right symmetric pattern for every rank", () => {
    const patterns = RANKS.map((r) => r.plate);
    expect(new Set(patterns).size).toBe(RANKS.length);
    for (const rank of RANKS) {
      expect(rank.plate).toMatch(/^[01]{3}\|[01]{3}$/);
      const { lit } = plateTiles(rank.id);
      expect(lit).toHaveLength(6);
      expect(lit.some(Boolean)).toBe(true);
      expect([lit[0], lit[3]]).toEqual([lit[2], lit[5]]);
    }
  });

  it("adds tiles within a tier as the rank rises, and the fleet admiral wears all six", () => {
    for (const tier of RANK_TIERS) {
      const counts = ranksOfTier(tier).map((r) => plateTiles(r.id).lit.filter(Boolean).length);
      expect(counts).toEqual([...counts].sort((a, b) => a - b));
      expect(new Set(counts).size).toBe(counts.length);
    }
    expect(plateTiles("fleet_admiral").lit.every(Boolean)).toBe(true);
    expect(plateTiles("recruit").lit).toEqual([false, false, false, false, true, false]);
    expect(plateTiles("ensign")).toMatchObject({ colour: TIER_STYLE.line.tile, tier: "line" });
    expect(rankBadge(30)).toEqual({ id: "line_captain", level: 29, tier: "command", colour: TIER_STYLE.command.tile, lit: [false, true, false, false, true, false] });
  });
});

describe("the ribbons", () => {
  it("are 30 mm two-tone stripes from the palette, never gold", () => {
    for (const [id, stripes] of Object.entries(RIBBON_STRIPES)) {
      expect(stripes.reduce((sum, [width]) => sum + width, 0), id).toBe(30);
      expect(new Set(stripes.map(([, colour]) => colour)).size, id).toBe(2);
      expect(stripes.some(([, colour]) => colour === TIER_STYLE.flag.tile), id).toBe(false);
    }
  });
});

describe("the rank view", () => {
  it("measures a subject on the curve, and treats an unknown subject as a recruit", () => {
    expect(rankView(undefined)).toMatchObject({ level: 1, xp: 0, rank: { id: "recruit" }, into: 0, size: 40, toNextRank: 105 });
    const ensign = rankView({ xp: LEVEL_XP[11] + 10, level: 12 });
    expect(ensign).toMatchObject({ rank: { id: "ensign" }, next: { id: "lieutenant" }, into: 10 });
    expect(ensign.toNextRank).toBe(LEVEL_XP[13] - LEVEL_XP[11] - 10);
    const top = rankView({ xp: 50_000, level: 50 });
    expect(top).toMatchObject({ atCap: true, fraction: 1, size: 0, toNextRank: 0, next: undefined });
  });

  it("orders the crew by experience, then by name", () => {
    const rows = crewRows(
      [{ agentId: "b", name: "Beta" }, { agentId: "a", name: "Alpha" }, { agentId: "c", name: "Gamma" }],
      { "agent:c": { subjectId: "agent:c", kind: "agent", xp: 2000, level: 11, xpIntoLevel: 0, xpForNext: 0, title: "" } },
    );
    expect(rows.map((r) => r.name)).toEqual(["Gamma", "Alpha", "Beta"]);
    expect(rows[0].view.rank.id).toBe("ensign");
  });

  it("formats and names what the record shows", () => {
    expect(fill("{xp} XP to {rank}", { xp: 5, rank: "Ensign" })).toBe("5 XP to Ensign");
    expect(fill("{who}", {})).toBe("{who}");
    expect(figure(43230)).toBe("43 230");
    expect(sourceKey("simulator_round")).toBe("verse.ranks.source.simulator_round");
    expect(sourceKey("warp_jump")).toBe("verse.ranks.source.retired");
    const rows = [1, 2, 3].map((seq) => ({ seq, subjectId: seq === 2 ? "agent:x" : "person", kind: "person" as const, source: "chat_turn", xp: 5, levelBefore: 1, levelAfter: 1, ref: "", tsMs: seq }));
    expect(logOf(rows, "person").map((r) => r.seq)).toEqual([3, 1]);
  });
});

describe("duty status", () => {
  it("reads the roster's run states", () => {
    expect(dutyOf({ state: "working" })).toBe("working");
    expect(dutyOf({ state: "idle" })).toBe("idle");
    expect(dutyOf({ state: "paused" })).toBe("paused");
    expect(dutyOf({ state: "waiting" })).toBe("waiting");
    expect(dutyOf({ state: "idle", lifecycle: "paused" })).toBe("paused");
  });

  it("puts the person's rest first, then what needs the person, then work, then an old failure", () => {
    expect(dutyOf({ state: "paused" }, { asking: true, error: true })).toBe("paused");
    expect(dutyOf({ state: "working" }, { asking: true })).toBe("waiting");
    expect(dutyOf({ state: "working" }, { error: true })).toBe("working");
    expect(dutyOf({ state: "idle" }, { error: true })).toBe("error");
    expect(dutyOf({ state: "idle" }, { asking: true, error: true })).toBe("waiting");
  });

  it("reads a coding pane's own dot", () => {
    expect(dutyOfPane("working")).toBe("working");
    expect(dutyOfPane("waiting")).toBe("waiting");
    expect(dutyOfPane("error")).toBe("error");
    expect(dutyOfPane("idle")).toBe("idle");
    expect(dutyOfPane("idle", "stopped")).toBe("paused");
  });

  it("gives each status a place, a word and a beacon as the brief says", () => {
    expect(DUTY.working).toMatchObject({ place: "console", screenLive: true, pulse: false });
    expect(DUTY.waiting).toMatchObject({ place: "stand", beacon: "#f2a33a", pulse: true });
    expect(DUTY.idle).toMatchObject({ place: "offduty", beacon: null });
    expect(DUTY.paused).toMatchObject({ place: "bunk", beacon: null });
    expect(DUTY.error).toMatchObject({ place: "console", beacon: "#e3242b" });
    for (const status of DUTY_STATUSES) expect(DUTY[status].labelKey).toBe(`verse.ranks.duty.${status}`);
    expect(DUTY_ORDER).toEqual(["waiting", "error", "working", "idle", "paused"]);
    expect(dutyCounts(["working", "working", "error"])).toEqual({ working: 2, waiting: 0, idle: 0, paused: 0, error: 1 });
    expect(isDutyStatus("error")).toBe(true);
    expect(isDutyStatus("busy")).toBe(false);
  });

  it("follows blocked results and open questions on the bus", () => {
    const blocked = applyDutyEvent(NO_SIGNALS, { name: "SocietyResultPosted", payload: { agent_id: "scout", status: "blocked" } });
    expect(blocked.errors.has("scout")).toBe(true);
    const asked = applyDutyEvent(blocked, { name: "SocietyMessageSent", payload: { msg_type: "QUERY", from_agent: "scout", to_agent: "user" } });
    expect(asked.asking.has("scout")).toBe(true);
    const answered = applyDutyEvent(asked, { name: "SocietyMessageSent", payload: { msg_type: "SAY", from_agent: "user", to_agent: "scout" } });
    expect(answered.asking.has("scout")).toBe(false);
    const done = applyDutyEvent(answered, { name: "SocietyResultPosted", payload: { agent_id: "scout", status: "done" } });
    expect(done.errors.has("scout")).toBe(false);
    // A question between two officers, or one asked into a room, is not a question to the person.
    expect(applyDutyEvent(NO_SIGNALS, { name: "SocietyMessageSent", payload: { msg_type: "QUERY", from_agent: "a", to_agent: "b" } })).toBe(NO_SIGNALS);
    expect(applyDutyEvent(NO_SIGNALS, { name: "SocietyMessageSent", payload: { msg_type: "QUERY", from_agent: "a", to_agent: "", room_id: "r1" } })).toBe(NO_SIGNALS);
    expect(applyDutyEvent(NO_SIGNALS, { name: "Other" })).toBe(NO_SIGNALS);
  });
});
