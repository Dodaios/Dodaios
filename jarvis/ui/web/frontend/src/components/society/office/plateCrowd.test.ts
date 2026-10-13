import { beforeEach, describe, expect, it } from "vitest";
import {
  arrangePlates, BUBBLE_ROOM, joinPlates, PLATE_GAP, plateSeating, plateStages, reportPlate, resetPlateSeating, type PlateBox,
} from "./plateCrowd";

/** A plate 150 px wide and 22 px high, like a name plate with a rank chip. */
function plate(id: string, x: number, y: number, extra: Partial<PlateBox> = {}): PlateBox {
  return { id, x, y, w: 150, h: 22, pinned: false, speaker: false, shown: false, distance: 5, ...extra };
}

/** Five figures 60 px apart on screen: every plate covers its neighbours. */
function huddle(extra: Record<string, Partial<PlateBox>> = {}): PlateBox[] {
  return ["a", "b", "c", "d", "e"].map((id, i) => plate(id, 400 + i * 60, 300, { distance: 3 + i, ...extra[id] }));
}

function coversAnother(boxes: PlateBox[], open: Set<string>): boolean {
  const seated = boxes.filter((box) => open.has(box.id));
  return seated.some((a, i) => seated.slice(i + 1).some((b) => Math.abs(a.x - b.x) * 2 < a.w + b.w && Math.abs(a.y - b.y) * 2 < a.h + b.h));
}

describe("name plates in a crowd", () => {
  it("opens every plate when nobody stands in anybody's way", () => {
    const row = [plate("a", 100, 100), plate("b", 400, 100), plate("c", 700, 100), plate("d", 400, 200)];
    expect(arrangePlates(row)).toEqual(new Set(["a", "b", "c", "d"]));
  });

  it("keeps a huddle of five readable: open plates never cover one another", () => {
    const boxes = huddle();
    const open = arrangePlates(boxes);
    expect(open.size).toBeGreaterThan(0);
    expect(open.size).toBeLessThan(boxes.length);
    expect(coversAnother(boxes, open)).toBe(false);
    // Among equals the one nearest to the person is the one that opens.
    expect(open.has("a")).toBe(true);
  });

  it("always opens the selected or pointed-at agent, and seats the others round it", () => {
    const boxes = huddle({ c: { pinned: true } });
    const open = arrangePlates(boxes);
    expect(open.has("c")).toBe(true);
    // The neighbours its plate covers stay dots.
    expect(open.has("b")).toBe(false);
    expect(open.has("d")).toBe(false);
    expect(coversAnother(boxes, open)).toBe(false);
  });

  it("puts the speaker ahead of the bystanders, even the nearer ones", () => {
    const boxes = huddle({ d: { speaker: true } });
    const open = arrangePlates(boxes);
    expect(open.has("d")).toBe(true);
    expect(open.has("c")).toBe(false);
    expect(open.has("e")).toBe(false);
  });

  it("keeps a speaker's bubble clear: no plate opens in the room above it", () => {
    const speaker = plate("s", 400, 300, { speaker: true });
    const behind = plate("x", 400, 300 - BUBBLE_ROOM.h + 10);
    const far = plate("y", 400, 300 - BUBBLE_ROOM.h - 60);
    const open = arrangePlates([behind, far, speaker]);
    expect(open).toEqual(new Set(["s", "y"]));
    // Without a speaker the same two plates do not touch and both open.
    expect(arrangePlates([behind, plate("s", 400, 300)])).toEqual(new Set(["s", "x"]));
  });

  it("does not reshuffle while people shift: an open plate keeps its seat against a nearer newcomer", () => {
    const boxes = [plate("old", 400, 300, { shown: true, distance: 6 }), plate("new", 460, 300, { distance: 2 })];
    expect(arrangePlates(boxes)).toEqual(new Set(["old"]));
  });

  it("opens and closes at different gaps, so a plate at the edge of another does not flicker", () => {
    const gap = (PLATE_GAP.keep + PLATE_GAP.open) / 2;
    const anchor = plate("a", 400, 300, { shown: true, distance: 1 });
    const beside = (shown: boolean) => plate("b", 400 + 150 + gap, 300, { shown, distance: 2 });
    // Just outside the other plate: a closed one stays closed, an open one stays open.
    expect(arrangePlates([anchor, beside(false)]).has("b")).toBe(false);
    expect(arrangePlates([anchor, beside(true)]).has("b")).toBe(true);
  });

  it("keeps clear of the person's own plate", () => {
    const person = { x: 400, y: 300, w: 150, h: 26 };
    expect(arrangePlates([plate("a", 430, 300), plate("b", 700, 300)], [person])).toEqual(new Set(["b"]));
    // The agent the person points at opens all the same.
    expect(arrangePlates([plate("a", 430, 300, { pinned: true })], [person])).toEqual(new Set(["a"]));
  });

  it("is the same answer whatever order the plates report in", () => {
    const boxes = huddle({ b: { speaker: true } });
    expect(arrangePlates([...boxes].reverse())).toEqual(arrangePlates(boxes));
  });
});

describe("plate seating from frame to frame", () => {
  beforeEach(resetPlateSeating);
  const nothingTaken = () => [];
  const stage = {};

  it("seats this frame from what the plates reported in the frame before", () => {
    expect(plateSeating(stage, 1, nothingTaken).size).toBe(0);
    for (const box of huddle()) reportPlate(stage, box);
    // Still frame 1: the answer does not change under the plates that already asked.
    expect(plateSeating(stage, 1, nothingTaken).size).toBe(0);
    const next = plateSeating(stage, 2, nothingTaken);
    expect(next.has("a")).toBe(true);
    expect(next.size).toBeLessThan(5);
  });

  it("forgets a plate that stopped reporting", () => {
    reportPlate(stage, plate("gone", 100, 100));
    expect(plateSeating(stage, 1, nothingTaken).has("gone")).toBe(true);
    reportPlate(stage, plate("here", 100, 100));
    expect(plateSeating(stage, 2, nothingTaken)).toEqual(new Set(["here"]));
  });
});

describe("two offices awake at once", () => {
  beforeEach(resetPlateSeating);
  const nothingTaken = () => [];

  it("seat their plates apart: the same agent sits on different screens, on different clocks", () => {
    const agentsView = {}, idePanel = {};
    // The same agent id, far apart on one screen and under another plate on the other.
    reportPlate(agentsView, plate("a", 100, 100));
    reportPlate(agentsView, plate("b", 600, 100));
    reportPlate(idePanel, plate("b", 100, 100, { distance: 1 }));
    reportPlate(idePanel, plate("a", 130, 100, { distance: 9 }));
    expect(plateSeating(agentsView, 10.5, nothingTaken)).toEqual(new Set(["a", "b"]));
    expect(plateSeating(idePanel, 3.25, nothingTaken)).toEqual(new Set(["b"]));
    // One stage asking again on its own clock does not re-seat or empty the other.
    reportPlate(agentsView, plate("a", 100, 100, { shown: true }));
    expect(plateSeating(agentsView, 10.6, nothingTaken)).toEqual(new Set(["a"]));
    expect(plateSeating(idePanel, 3.25, nothingTaken)).toEqual(new Set(["b"]));
  });

  it("releases a stage's seating when its last plate has left", () => {
    const stage = {}, other = {};
    const leaveA = joinPlates(stage), leaveB = joinPlates(stage), leaveOther = joinPlates(other);
    reportPlate(stage, plate("a", 100, 100));
    expect(plateStages()).toBe(2);
    leaveA();
    expect(plateStages()).toBe(2);
    leaveB();
    // Leaving twice (an effect cleaned up again) must not take somebody else's count.
    leaveB();
    expect(plateStages()).toBe(1);
    leaveOther();
    expect(plateStages()).toBe(0);
    // A stage that mounts again starts clean: nothing of the old reports is seated.
    const leaveAgain = joinPlates(stage);
    expect(plateSeating(stage, 1, nothingTaken).size).toBe(0);
    leaveAgain();
    expect(plateStages()).toBe(0);
  });
});
