import { describe, expect, it } from "vitest";
import { syntheticDeck } from "../testing/syntheticDeck";
import { worldToPlate } from "./plateMath";
import { pickBody, pickStation } from "./picking";

const deck = syntheticDeck();
const pose = (id: string, x: number, z: number, y = 0) => ({ id, x, y, z, height: 1.78, moving: false });

describe("picking", () => {
  it("hits a body between its feet and the top of its head", () => {
    const poses = [pose("a", -5, 2)];
    const chest = worldToPlate(deck.camera, -5, 1.2, 2);
    expect(pickBody(deck.camera, poses, chest, () => true)).toBe("a");
    const beside = worldToPlate(deck.camera, -4.4, 1.2, 2);
    expect(pickBody(deck.camera, poses, beside, () => true)).toBeNull();
    const above = worldToPlate(deck.camera, -5, 2.4, 2);
    expect(pickBody(deck.camera, poses, above, () => true)).toBeNull();
  });

  it("prefers the body nearer the camera where two overlap", () => {
    // b stands 0.5 m in front (toward +z): its head covers a's legs on the plate.
    const poses = [pose("a", 0, 0), pose("b", 0, 0.5)];
    const p = worldToPlate(deck.camera, 0, 0.9, 0.5);
    expect(pickBody(deck.camera, poses, p, () => true)).toBe("b");
    expect(pickBody(deck.camera, poses, p, (id) => id === "a")).toBe("a");
  });

  it("finds a station by its spot or its member sockets", () => {
    const station = deck.stations.find((s) => s.id === "brief")!;
    expect(pickStation(deck, worldToPlate(deck.camera, station.x, 0.5, station.z))?.id).toBe("brief");
    const seat = deck.sockets.find((s) => s.kind === "seat" && s.station === "brief")!;
    expect(pickStation(deck, worldToPlate(deck.camera, seat.x, 0.5, seat.z))?.id).toBe("brief");
    expect(pickStation(deck, worldToPlate(deck.camera, 20, 0, 10))).toBeNull();
  });
});
