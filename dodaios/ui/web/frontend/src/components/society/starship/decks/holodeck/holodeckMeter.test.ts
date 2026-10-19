import { beforeEach, describe, expect, it } from "vitest";
import type { RetroGame } from "../../../arcade/retroGame";
import { clearBestMemory, saveBest } from "../../../arcade/retroScores";
import { meteredGame, type HolodeckAction } from "./holodeckMeter";

interface S { score: number; over: boolean }

const game: RetroGame<S> = {
  id: "neon-snake", width: 10, height: 10,
  create: () => ({ score: 0, over: false }),
  step: (s) => { s.score += 10; },
  draw: () => undefined,
  status: (s) => ({ score: s.score, over: s.over }),
};

describe("holodeck metering", () => {
  beforeEach(() => { window.localStorage.clear(); clearBestMemory(); });

  it("reports a finished, scored run once, a record when it beats the best", () => {
    const reports: [HolodeckAction, string][] = [];
    const metered = meteredGame(game, "neon-snake", (a, id) => reports.push([a, id]));
    const run = metered.create(Math.random);
    metered.step(run, {} as never, 1, Math.random);
    expect(metered.status(run).over).toBe(false);
    run.over = true;
    metered.status(run);
    metered.status(run);
    expect(reports).toEqual([["holodeck_record", "neon-snake"]]);

    saveBest("neon-snake", 500);
    const second = metered.create(Math.random);
    second.score = 40; second.over = true;
    metered.status(second);
    expect(reports[1]).toEqual(["holodeck_round", "neon-snake"]);
  });

  it("does not report a run that scored nothing", () => {
    const reports: string[] = [];
    const metered = meteredGame(game, "neon-snake", (a) => reports.push(a));
    const run = metered.create(Math.random);
    run.over = true;
    metered.status(run);
    expect(reports).toEqual([]);
  });

  it("keeps the rest of the game as it was", () => {
    const metered = meteredGame(game, "neon-snake", () => undefined);
    expect(metered.width).toBe(10);
    expect(metered.create(Math.random)).toEqual({ score: 0, over: false });
  });
});
