/**
 * Heavy balance run from a shell (not part of the test suite):
 *
 *   npx esbuild src/components/society/verse/combat/harness/cli.ts --bundle \
 *     --platform=node --format=esm --outfile=<tmp>/balance.mjs
 *   node <tmp>/balance.mjs [duelsPerPairing] [ladder|humans|exploits|elite|cross|all|a:b,c:d] [seed] [tuningPatchJson|-] [jobs]
 *
 * e.g. `node balance.mjs 300 hard:dodger 1 '{"dodge":{"iframeTicks":9}}'` to
 * try a change, or `node balance.mjs 300 elite:skilled+kiter` for one trick.
 * Strategy ids: normal, hard, elite, skilled, average, a trick (on the hard
 * bot), or base+trick; harness/strategies.ts lists them. With `jobs` > 1 every
 * pairing runs in its own process (same seeds, same results as one process).
 * Prints one line per pairing and a JSON summary at the end.
 */
import { spawn } from "node:child_process";
import { DEFAULT_TUNING, withTuning, type CombatTuning, type DeepPartial } from "../tuning";
import { CROSS, EXPLOITS, formatReport, HUMANS, runBalance, TIER_LADDER, VS_ELITE, type PairingReport } from "./balance";
import type { StrategyId } from "./strategies";

const duels = Number(process.argv[2] ?? 200);
const which = process.argv[3] ?? "all";
const seed = Number(process.argv[4] ?? 1);
const patchArg = process.argv[5] && process.argv[5] !== "-" ? process.argv[5] : "";
const jobs = Number(process.argv[6] ?? 1);
const patch = patchArg ? (JSON.parse(patchArg) as DeepPartial<CombatTuning>) : null;
const sets: Record<string, readonly (readonly [StrategyId, StrategyId])[]> = {
  ladder: TIER_LADDER, humans: HUMANS, exploits: EXPLOITS, elite: VS_ELITE, cross: CROSS,
  all: [...TIER_LADDER, ...HUMANS, ...EXPLOITS, ...VS_ELITE, ...CROSS],
};
const pairings = sets[which] ?? which.split(",").map((p) => p.split(":") as [StrategyId, StrategyId]);
const tuning = patch ? withTuning(DEFAULT_TUNING, patch) : DEFAULT_TUNING;
const started = Date.now();

/** Run pairing i in a child process (seeded exactly as the sequential run seeds it). */
function child(i: number): Promise<PairingReport> {
  const [a, b] = pairings[i];
  const args = [process.argv[1], String(duels), `${a}:${b}`, String(seed + i * 104729), patchArg || "-", "1"];
  return new Promise((resolve, reject) => {
    const p = spawn(process.execPath, args, { stdio: ["ignore", "pipe", "inherit"] });
    let out = "";
    p.stdout.on("data", (d: Buffer) => { out += d.toString(); });
    p.on("close", (code) => {
      const last = out.trim().split("\n").pop() ?? "";
      try { resolve((JSON.parse(last) as PairingReport[])[0]); } catch { reject(new Error(`pairing ${a}:${b} failed (${code})`)); }
    });
  });
}

async function main(): Promise<void> {
  let reports: PairingReport[];
  if (jobs > 1 && pairings.length > 1) {
    reports = new Array(pairings.length);
    let next = 0;
    const worker = async () => {
      while (next < pairings.length) {
        const i = next++;
        reports[i] = await child(i);
        console.log(formatReport(reports[i]));
      }
    };
    await Promise.all(Array.from({ length: Math.min(jobs, pairings.length) }, worker));
    console.log("in order:");
    for (const r of reports) console.log(formatReport(r));
  } else {
    reports = runBalance({ pairings, duels, seed, tuning, onPairing: (r) => console.log(formatReport(r)) });
  }
  console.log(`done: ${reports.length} pairings x ${duels} duels in ${((Date.now() - started) / 1000).toFixed(1)} s`);
  console.log(JSON.stringify(reports));
}

void main();
