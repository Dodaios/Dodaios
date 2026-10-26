// @vitest-environment node
/**
 * Balance smoke test: a handful of headless duels per key pairing, enough to
 * catch a balance regression. The full matrix (hundreds of duels per
 * pairing) runs from harness/cli.ts, or here with COMBAT_BALANCE=full.
 */
import { describe, expect, it } from "vitest";
import { createContext } from "../sim";
import { CROSS, EXPLOITS, formatReport, HUMANS, runBalance, runPairing, TIER_LADDER, VS_ELITE } from "./balance";
import { runDuel } from "./duel";
import { strategy } from "./strategies";

const full = typeof process !== "undefined" && process.env.COMBAT_BALANCE === "full";

describe("balance (smoke)", () => {
  const ctx = createContext();

  it("higher tiers win more", () => {
    const { report } = runPairing(ctx, "elite", "normal", 6, 11);
    expect(report.winRateA).toBeGreaterThanOrEqual(4 / 6);
    expect(report.timeoutRounds).toBe(0);
    expect(report.accuracy[0]).toBeGreaterThan(report.accuracy[1]);
  });

  it("one-trick strategies do not beat the hard bot", () => {
    for (const trick of ["spam", "turtle", "camper"] as const) {
      const { report } = runPairing(ctx, "hard", trick, 6, 17);
      expect(report.winRateA, trick).toBeGreaterThanOrEqual(0.5);
    }
  });

  it("a headless duel is reproducible from its seed", () => {
    const a = runDuel({ ctx, seed: 99, players: [strategy("hard"), strategy("elite")] });
    const b = runDuel({ ctx, seed: 99, players: [strategy("hard"), strategy("elite")] });
    expect(a).toEqual(b);
    expect(a.rounds.length).toBeGreaterThanOrEqual(2);
  });

  it.runIf(full)("full matrix", () => {
    const pairings = [...TIER_LADDER, ...HUMANS, ...EXPLOITS, ...VS_ELITE, ...CROSS];
    const reports = runBalance({ pairings, duels: 200, seed: 1, onPairing: (r) => console.log(formatReport(r)) });
    expect(reports.length).toBe(pairings.length);
  }, 3_600_000);
});
