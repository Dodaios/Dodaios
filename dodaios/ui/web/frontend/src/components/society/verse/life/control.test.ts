import { describe, expect, it } from "vitest";
import { syntheticDeck } from "../testing/syntheticDeck";
import { CommanderControl, STATION_REACH_M, stationWithin } from "./control";

describe("commander control", () => {
  it("starts in third person and frames the commander first", () => {
    const c = new CommanderControl();
    expect(c.mode).toBe("follow");
    expect(c.reframe).toBe(true);
    expect(c.direction()).toBeNull();
  });

  it("reads the keys screen-relative: up is −Z, right is +X", () => {
    const c = new CommanderControl();
    c.setKey("up", true);
    expect(c.direction()).toEqual({ x: 0, z: -1 });
    c.setKey("up", false);
    c.setKey("right", true);
    expect(c.direction()).toEqual({ x: 1, z: 0 });
  });

  it("walks diagonals at the same speed as straight lines", () => {
    const c = new CommanderControl();
    c.setKey("down", true);
    c.setKey("left", true);
    const d = c.direction()!;
    expect(Math.hypot(d.x, d.z)).toBeCloseTo(1, 9);
    expect(d.x).toBeLessThan(0);
    expect(d.z).toBeGreaterThan(0);
  });

  it("stands still when opposite keys cancel, and lets go of everything on clear", () => {
    const c = new CommanderControl();
    c.setKey("left", true);
    c.setKey("right", true);
    expect(c.direction()).toBeNull();
    c.setKey("up", true, true);
    expect(c.run).toBe(true);
    c.clearKeys();
    expect(c.direction()).toBeNull();
    expect(c.run).toBe(false);
  });
});

describe("station within reach", () => {
  const deck = syntheticDeck();

  it("offers the nearest station the commander stands at", () => {
    expect(stationWithin(deck.stations, -15, 0.4)?.id).toBe("command");
    expect(stationWithin(deck.stations, -22, 0.5)?.id).toBe("lift");
  });

  it("offers nothing out of reach", () => {
    expect(stationWithin(deck.stations, -16 + STATION_REACH_M + 0.3, 0)).toBeNull();
    expect(stationWithin(deck.stations, 20, 8)).toBeNull();
  });
});
