import { describe, expect, it } from "vitest";
import { allDesks, chairRect, deskRect, seatOf, type DeskSlot, type Point, type Rect } from "./officeLayout";
import { type Mover } from "./officeMotion";
import { isWalkable } from "./officeNav";
import { PERSON_CLEAR_M, standingPlaceFor } from "./officeTeams";
import { advanceWalk, beginWalk } from "./officeWalk";
import { SEAT_REACH } from "./leadSeat";
import { campusOf } from "./officeFixtures";

// Fourteen agents, a team of five and a team of four; everybody sits at their desk.
const campus = campusOf(14, [5, 4]);
const benchDesks = allDesks(campus.layout).filter((d) => !d.size);
const occupied = benchDesks.filter((d) => d.agentId);
const seated: Point[] = occupied.map((d) => { const seat = seatOf(d); return { x: seat.x, z: seat.z }; });
const inside = (rect: Rect, p: Point) => p.x > rect.minX && p.x < rect.maxX && p.z > rect.minZ && p.z < rect.maxZ;

/** A place the person may stand on: floor, outside every chair and desk, and beside everybody rather than in them. */
function expectStandingPlace(place: Point | null, label: string): asserts place is Point {
  expect(place, label).not.toBeNull();
  expect(isWalkable(campus.grid, place!), label).toBe(true);
  for (const desk of benchDesks) {
    expect(inside(chairRect(seatOf(desk)), place!), `${label} in the chair of ${desk.id}`).toBe(false);
    expect(inside(deskRect(desk), place!), `${label} in the desk ${desk.id}`).toBe(false);
  }
  for (const body of seated) expect(Math.hypot(body.x - place!.x, body.z - place!.z), label).toBeGreaterThanOrEqual(PERSON_CLEAR_M);
}

/** Walk the person's character to wherever a click on \`goal\` resolves, as OfficePlayer does; returns where it ends. */
function clickAndWalk(goal: Point, from: Point = campus.layout.spawn): Point {
  const place = standingPlaceFor(campus.layout, campus.grid, goal, seated)!;
  const m: Mover = { x: from.x, z: from.z, heading: 0, path: [] };
  const walk = beginWalk(campus.grid, m, place, seated)!;
  for (let i = 0; i < 60 * 240; i += 1) {
    const step = advanceWalk(walk, m, campus.grid, 1 / 60, seated, { speed: 2, place: false });
    if (step.arrived || step.event === "blocked" || step.event === "lost") break;
  }
  return { x: m.x, z: m.z };
}

describe("where a click sends the person", () => {
  it("is the clicked point itself on free floor", () => {
    const goal = campus.layout.arrival;
    expect(standingPlaceFor(campus.layout, campus.grid, goal, seated)).toEqual({ x: goal.x, z: goal.z });
  });

  it("is a place beside the chair for a click on a seated agent, never the chair or the agent", () => {
    for (const desk of occupied) {
      const seat = seatOf(desk);
      // On the figure, a little off its centre, as a click on it lands.
      for (const goal of [{ x: seat.x + 0.3, z: seat.z + 0.2 }, { x: seat.x, z: seat.z }, { x: seat.x - 0.2, z: seat.z - 0.1 }]) {
        const place = standingPlaceFor(campus.layout, campus.grid, goal, seated);
        expectStandingPlace(place, desk.id);
        // Beside this desk, within a step or two of what was clicked.
        expect(Math.hypot(place.x - seat.x, place.z - seat.z), desk.id).toBeLessThan(1.4);
      }
    }
  });

  it("walks there and ends beside the seated agent, on its feet", () => {
    for (const desk of occupied.slice(0, 6)) {
      const seat = seatOf(desk);
      const end = clickAndWalk({ x: seat.x + 0.3, z: seat.z + 0.2 });
      expectStandingPlace(end, desk.id);
      expect(Math.hypot(end.x - seat.x, end.z - seat.z), desk.id).toBeLessThan(1.4);
    }
  });

  it("is a place at the desk for a click on a desk top", () => {
    for (const desk of benchDesks.slice(0, 10)) {
      const place = standingPlaceFor(campus.layout, campus.grid, { x: desk.x + 0.1, z: desk.z }, seated);
      expectStandingPlace(place, desk.id);
      expect(Math.hypot(place.x - desk.x, place.z - desk.z), desk.id).toBeLessThan(2.2);
      expectStandingPlace(clickAndWalk({ x: desk.x + 0.1, z: desk.z }), desk.id);
    }
  });

  it("does not sit the person on an empty chair either: it stands beside it", () => {
    const empty: DeskSlot[] = benchDesks.filter((d) => !d.agentId);
    expect(empty.length).toBeGreaterThan(0);
    for (const desk of empty) {
      const seat = seatOf(desk);
      const place = standingPlaceFor(campus.layout, campus.grid, { x: seat.x, z: seat.z }, seated);
      expectStandingPlace(place, desk.id);
      expect(Math.hypot(place.x - seat.x, place.z - seat.z), desk.id).toBeGreaterThan(0.5);
      expect(Math.hypot(place.x - seat.x, place.z - seat.z), desk.id).toBeLessThan(1.4);
      expectStandingPlace(clickAndWalk({ x: seat.x, z: seat.z }), desk.id);
    }
  });

  it("steps aside when a visitor already stands in the place beside the chair", () => {
    const desk = occupied[0];
    const seat = seatOf(desk);
    const first = standingPlaceFor(campus.layout, campus.grid, seat, seated)!;
    const second = standingPlaceFor(campus.layout, campus.grid, seat, [...seated, first]);
    expectStandingPlace(second, desk.id);
    expect(Math.hypot(second.x - first.x, second.z - first.z)).toBeGreaterThanOrEqual(PERSON_CLEAR_M);
  });

  it("stops beside a standing agent instead of in it", () => {
    const agent = campus.layout.arrival;
    const place = standingPlaceFor(campus.layout, campus.grid, { x: agent.x + 0.1, z: agent.z }, [agent])!;
    expect(isWalkable(campus.grid, place)).toBe(true);
    expect(Math.hypot(place.x - agent.x, place.z - agent.z)).toBeGreaterThanOrEqual(PERSON_CLEAR_M);
    expect(Math.hypot(place.x - agent.x, place.z - agent.z)).toBeLessThan(1.3);
  });

  it("still brings the person within reach of the lead's chair, which has its own sit action", () => {
    for (const desk of campus.layout.lead.desks) {
      const seat = seatOf(desk);
      const place = standingPlaceFor(campus.layout, campus.grid, seat, seated)!;
      expect(isWalkable(campus.grid, place)).toBe(true);
      expect(Math.hypot(place.x - seat.x, place.z - seat.z)).toBeLessThanOrEqual(SEAT_REACH);
    }
  });

  it("finds floor beside any piece of furniture that was clicked", () => {
    for (const item of campus.layout.furniture.slice(0, 40)) {
      const place = standingPlaceFor(campus.layout, campus.grid, { x: item.x, z: item.z }, seated);
      expect(place, item.id).not.toBeNull();
      expect(isWalkable(campus.grid, place!), item.id).toBe(true);
    }
  });
});
