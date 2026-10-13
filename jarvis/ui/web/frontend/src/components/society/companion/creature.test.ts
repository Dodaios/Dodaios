import { describe, expect, it } from "vitest";
import {
  composeCreature, creatureBody, creatureColor, creatureCubes, creatureFromShape, creaturePose, creatureSchema,
  CREATURE_PALETTES, CREATURE_STATES, CREATURE_STILL_FRAME, GRID, growCreature, nearestPalette,
  STAGE_H, STAGE_W, STAGE_X, STAGE_Y,
} from "./creature";

const SEEDS = [0, 1, 5, 24, 4711, 99_999];

describe("growing a pixel creature", () => {
  it("gives the same mirrored figure for the same number, with a full middle", () => {
    for (const seed of SEEDS) {
      const cells = growCreature(seed);
      expect(cells).toEqual(growCreature(seed));
      expect(cells).toHaveLength(GRID);
      for (const row of cells) expect(row).toEqual([...row].reverse());
      for (let r = 2; r <= 6; r++) for (let c = 2; c <= 6; c++) expect(cells[r]![c]).toBe(true);
    }
    expect(growCreature(5)).not.toEqual(growCreature(24));
  });

  it("never leaves an ornament or a leg floating", () => {
    for (let seed = 0; seed < 200; seed++) {
      const cells = growCreature(seed);
      for (let c = 0; c < GRID; c++) {
        if (cells[0]![c]) expect(cells[1]![c]).toBe(true);
        if (cells[1]![c]) expect(cells[2]![c]).toBe(true);
        if (cells[7]![c]) expect(cells[6]![c]).toBe(true);
        if (cells[8]![c]) expect(cells[7]![c]).toBe(true);
      }
    }
  });

  it("builds a solid block three cubes deep with the face on its front", () => {
    const body = creatureBody({ seed: 24, palette: "neon", eyes: "dot" });
    const cubes = creatureCubes(body, creaturePose("idle", 5));
    const filled = body.cells.flat().filter(Boolean).length;
    expect(cubes).toHaveLength(filled * 3);
    const ink = cubes.filter((cube) => cube.color === body.palette.ink);
    expect(ink).toHaveLength(2);
    expect(ink.every((cube) => cube.z === 1)).toBe(true);
  });

  it("wears the first colour world and dot eyes for ids it does not know", () => {
    const body = creatureBody({ seed: 3, palette: "futureworld", eyes: "futureeyes" });
    expect(body.palette.id).toBe(CREATURE_PALETTES[0]!.id);
    expect(body.eyes).toBe("dot");
  });
});

describe("what a creature acts out", () => {
  it("keeps every sign and spark of every state inside the stage", () => {
    for (const state of CREATURE_STATES) for (let frame = 0; frame < 120; frame++) {
      for (const bit of creaturePose(state, frame).bits) {
        expect(bit.x).toBeGreaterThanOrEqual(-STAGE_X);
        expect(bit.x).toBeLessThan(STAGE_W - STAGE_X);
        expect(bit.y).toBeGreaterThanOrEqual(-STAGE_Y);
        expect(bit.y).toBeLessThan(STAGE_H - STAGE_Y);
      }
    }
  });

  it("gives each state its own still frame", () => {
    const stills = CREATURE_STATES.map((state) => JSON.stringify(creaturePose(state, CREATURE_STILL_FRAME[state])));
    expect(new Set(stills).size).toBe(CREATURE_STATES.length);
  });

  it("rests most of the time: an idle creature only blinks and glances", () => {
    const poses = new Set(Array.from({ length: 60 }, (_, frame) => JSON.stringify(creaturePose("idle", frame))));
    expect(poses.size).toBe(4);
  });

  it("draws the face on the body in every state, on every eye kind", () => {
    for (const eyes of ["dot", "tall", "wide", "visor"]) for (const state of CREATURE_STATES) {
      const body = creatureBody({ seed: 24, palette: "ocean", eyes });
      const cells = [...composeCreature(body, creaturePose(state, CREATURE_STILL_FRAME[state])).values()];
      expect(cells.some((cell) => cell.front !== null)).toBe(true);
    }
  });
});

describe("a creature for an agent that never chose one", () => {
  const shape = { shape: "drop", color: "#1174da", eyes: "dots", accessories: { head: "crown" } };

  it("is the same on every surface and passes the stored contract", () => {
    const creature = creatureFromShape(shape);
    expect(creature).toEqual(creatureFromShape({ ...shape, color: "#1174DA" }));
    expect(creatureSchema.safeParse(creature).success).toBe(true);
    expect(creature.eyes).toBe("dot");
    expect(creatureFromShape({ ...shape, shape: "cloud" }).seed).not.toBe(creature.seed);
  });

  it("lands in the colour world nearest the agent's own colour", () => {
    expect(nearestPalette("#029858")).toBe("moss");
    expect(nearestPalette("#dd2233")).toBe("lava");
    expect(creatureColor({ seed: 1, palette: "gold", eyes: "dot" })).toBe("#ffcd61");
  });
});
