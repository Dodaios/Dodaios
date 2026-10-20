import { describe, expect, it } from "vitest";
import { worldToPlate } from "../engine/plateMath";
import { PIT, syntheticDeck } from "../testing/syntheticDeck";
import { pickFloor } from "./floorPick";

const deck = syntheticDeck();

describe("floor picking", () => {
  it("finds the deck floor under a plate point", () => {
    const p = worldToPlate(deck.camera, -8, 0, 3);
    const hit = pickFloor(deck.camera, deck.nav, p.u, p.v);
    expect(hit).not.toBeNull();
    expect(hit!.x).toBeCloseTo(-8, 1);
    expect(hit!.z).toBeCloseTo(3, 1);
    expect(hit!.y).toBe(0);
  });

  it("finds the sunken pit floor where the photograph shows it", () => {
    const at = { x: 16, z: -9 };
    const p = worldToPlate(deck.camera, at.x, PIT.depth, at.z);
    const hit = pickFloor(deck.camera, deck.nav, p.u, p.v);
    expect(hit!.y).toBeCloseTo(PIT.depth, 3);
    expect(hit!.x).toBeCloseTo(at.x, 1);
    expect(Math.abs(hit!.z - at.z)).toBeLessThan(0.15);
  });

  it("falls back to the nearest floor when the pointer is on a wall", () => {
    const p = worldToPlate(deck.camera, 0, 0.5, -3);
    const hit = pickFloor(deck.camera, deck.nav, p.u, p.v);
    expect(hit).not.toBeNull();
  });
});
