import { describe, expect, it } from "vitest";
import { syntheticDeck } from "../testing/syntheticDeck";
import { commanderStart, commanderTarget, outOfLift } from "./commander";

const bridge = syntheticDeck();
const ops = { ...syntheticDeck(), id: "ops" as const };

describe("commander orders", () => {
  it("walks to an order given on the deck on screen", () => {
    expect(commanderTarget(bridge, { target: { deck: "bridge", x: 3, z: 4 }, order: 1, fromLift: false })).toEqual({ x: 3, z: 4 });
  });

  it("never carries an order over to another deck (regression: walking to the old deck's lift exit)", () => {
    const fromBridge = { target: { deck: "bridge" as const, x: 3, z: 4 }, order: 5, fromLift: true };
    // After a ride the commander steps out of this deck's lift, whatever was ordered upstairs.
    expect(commanderTarget(ops, fromBridge)).toEqual(outOfLift(ops));
    // A switch without a ride (the IDE panel going back to its deck) puts them at the spawn.
    expect(commanderTarget(ops, { ...fromBridge, fromLift: false })).toEqual(commanderStart(ops));
  });

  it("stands at the spawn on a first visit", () => {
    expect(commanderTarget(bridge, { target: null, order: 0, fromLift: false })).toEqual(commanderStart(bridge));
  });
});
