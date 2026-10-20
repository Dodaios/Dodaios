import { describe, expect, it } from "vitest";
import { roomsAt } from "./useWorldActions";

describe("world actions", () => {
  const rooms = [
    { id: "hall", name: "Hall", floorY: 0, polygon: [[0, 0], [10, 0], [10, 10], [0, 10]] as [number, number][], main: true },
    { id: "pit", name: "Pit", floorY: -1.4, polygon: [[2, 2], [4, 2], [4, 4], [2, 4]] as [number, number][], main: false },
  ];

  it("knows which room the commander stands in, by floor and height", () => {
    expect(roomsAt({ rooms }, 5, 0, 5)).toEqual(["hall"]);
    // Down in the pit the commander is in the pit, not on the hall floor 1.4 m above.
    expect(roomsAt({ rooms }, 3, -1.4, 3)).toEqual(["pit"]);
    expect(roomsAt({ rooms }, 20, 0, 5)).toEqual([]);
  });
});
