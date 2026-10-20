import { describe, expect, it } from "vitest";
import { huddlePlaces, studioOfTeam } from "./officeTeams";
import { campusOf } from "./officeFixtures";
import type { SocietyAgent } from "../data";
import { allDesks, buildOfficeLayout, type OfficeAgentInput } from "./officeLayout";
import { buildNavGrid, isWalkable } from "./officeNav";
import { createRng, planFor, SpotBook, type PlanInput } from "./officeBehavior";
import { boardSeats, MEETING_MS, meetingProgress, meetingSeats, minutesLeft } from "./teamMeeting";
import type { TeamMeeting } from "./officeStore";

const roster: OfficeAgentInput[] = Array.from({ length: 9 }, (_, i) => ({
  agentId: `a${i}`, name: `a${i}`, tier: "specialist", providerLabel: "Codex", state: "idle", createdMs: i,
}));
const layout = buildOfficeLayout(roster);
const grid = buildNavGrid(layout);
const ids = roster.map((r) => r.agentId);

function agent(agentId: string, state: SocietyAgent["state"]): SocietyAgent {
  return { agentId, name: agentId, state } as SocietyAgent;
}

function input(agentId: string, book: SpotBook, extra: Partial<PlanInput>): PlanInput {
  return {
    agentId, state: "idle", desk: allDesks(layout).find((d) => d.agentId === agentId) ?? null, layout, grid,
    rng: createRng(agentId), book, previous: null, workingColleagues: [], calledTo: null, ...extra,
  };
}

describe("meetingSeats", () => {
  it("gives every member its own chair, middle chairs first, facing pairs together", () => {
    const seats = meetingSeats(layout, ["a0", "a1"]);
    const [s0, s1] = [seats.a0, seats.a1];
    expect(s0.spotId).toMatch(/^meeting-/);
    expect(s1.spotId).toMatch(/^meeting-/);
    expect(s0.spotId).not.toBe(s1.spotId);
    // Across the table from each other: same x, opposite sides.
    expect(s0.target.x).toBeCloseTo(s1.target.x);
    expect(s0.target.z).not.toBeCloseTo(s1.target.z);
  });

  it("lets members beyond the chairs stand at the table's ends on walkable floor", () => {
    const seats = meetingSeats(layout, ids);
    const chairs = layout.spots.filter((s) => s.kind === "meeting").length;
    const standing = ids.filter((id) => !seats[id].spotId);
    expect(standing).toHaveLength(ids.length - chairs);
    for (const id of standing) expect(isWalkable(grid, seats[id].target)).toBe(true);
  });
});

describe("planFor with a meeting chair", () => {
  it("sits a called member on its chair", () => {
    const seat = meetingSeats(layout, ["a3"]).a3;
    const plan = planFor(input("a3", new SpotBook(), { calledTo: seat.target, calledSeat: seat.spotId }));
    expect(plan.kind).toBe("meeting");
    expect(plan.pose).toBe("sit");
    expect(plan.spotId).toBe(seat.spotId);
    expect(plan.target).toEqual(seat.target);
  });

  it("takes another free chair when its own is occupied", () => {
    const book = new SpotBook();
    const seat = meetingSeats(layout, ["a3"]).a3;
    book.claim(seat.spotId!, "stranger");
    const plan = planFor(input("a3", book, { calledTo: seat.target, calledSeat: seat.spotId }));
    expect(plan.kind).toBe("meeting");
    expect(plan.spotId).not.toBe(seat.spotId);
    expect(plan.spotId).toMatch(/^meeting-/);
  });

  it("never pulls a working agent away from its screen", () => {
    const seat = meetingSeats(layout, ["a3"]).a3;
    expect(planFor(input("a3", new SpotBook(), { state: "working", calledTo: seat.target, calledSeat: seat.spotId })).kind).toBe("work");
  });
});

describe("meetingProgress", () => {
  it("sorts members into seated, arriving, busy and missing", () => {
    const meeting: TeamMeeting = { groupId: "g", name: "Crew", members: ["a0", "a1", "a2", "gone"], untilMs: 1 };
    const seats = meetingSeats(layout, meeting.members);
    const summons = Object.fromEntries(Object.entries(seats).map(([id, s]) => [id, { ...s, untilMs: 1 }]));
    const positions = new Map([
      ["a0", seats.a0.target],
      ["a1", { x: seats.a1.target.x + 3, z: seats.a1.target.z }],
      ["a2", { x: 0, z: 0 }],
    ]);
    const progress = meetingProgress(meeting, [agent("a0", "idle"), agent("a1", "idle"), agent("a2", "working")], summons, positions);
    expect(progress).toEqual({ seated: ["a0"], arriving: ["a1"], busy: ["a2"], missing: ["gone"] });
  });

  it("counts minutes left, rounded up, and none after the end", () => {
    const meeting: TeamMeeting = { groupId: "g", name: "Crew", members: [], untilMs: 1_000 + MEETING_MS };
    expect(minutesLeft(meeting, 1_000)).toBe(10);
    expect(minutesLeft(meeting, 1_000 + MEETING_MS - 30_000)).toBe(1);
    expect(minutesLeft(meeting, 2_000 + MEETING_MS)).toBe(0);
  });
});

describe("a meeting at a studio's own board", () => {
  const campus = campusOf(12, [5]);
  const studio = studioOfTeam(campus.layout, "team-0")!;
  const places = huddlePlaces(campus.layout, campus.grid, studio);

  it("gives every member a place in the arcs, the arc nearest the board first", () => {
    const seats = boardSeats(campus.layout, studio, studio.members);
    expect(Object.keys(seats)).toEqual(studio.members);
    const ids = Object.values(seats).map((s) => s.spotId);
    expect(new Set(ids).size).toBe(studio.members.length);
    const from = (id: string) => { const seat = seats[id].target; return Math.hypot(seat.x - studio.board!.x, seat.z - studio.board!.z); };
    for (let i = 1; i < studio.members.length; i += 1) expect(from(studio.members[i])).toBeGreaterThanOrEqual(from(studio.members[i - 1]) - 0.11);
    for (const seat of Object.values(seats)) expect(places.some((p) => p.id === seat.spotId && p.x === seat.target.x && p.z === seat.target.z)).toBe(true);
  });

  it("leaves members beyond the places where they are, and has none for a studio without a board", () => {
    const crowd = Array.from({ length: places.length + 3 }, (_, i) => `m${i}`);
    expect(Object.keys(boardSeats(campus.layout, studio, crowd, campus.grid))).toHaveLength(places.length);
    // Both argument orders name the same places.
    expect(boardSeats(campus.layout, campus.grid, studio, studio.members)).toEqual(boardSeats(campus.layout, studio, studio.members, campus.grid));
    expect(boardSeats(campus.layout, null, studio, studio.members)).toEqual(boardSeats(campus.layout, studio, studio.members));
    expect(boardSeats(campus.layout, { ...studio, board: null }, studio.members, null)).toEqual({});
  });

  it("stands a called member on its place at the board, facing it, and leaves a working one at its screen", () => {
    const seats = boardSeats(campus.layout, studio, studio.members);
    const book = new SpotBook();
    const desks = campus.layout.departments.flatMap((d) => d.desks);
    const plan = (id: string, state: "idle" | "working") => planFor({
      agentId: id, state, desk: desks.find((d) => d.agentId === id) ?? null, layout: campus.layout, grid: campus.grid, rng: createRng(id), book,
      previous: null, workingColleagues: [], calledTo: seats[id].target, calledSeat: seats[id].spotId,
    });
    const first = plan(studio.members[0], "idle");
    const place = places.find((p) => p.id === seats[studio.members[0]].spotId)!;
    expect(first).toMatchObject({ kind: "huddle", pose: "stand", dwellMs: Infinity, spotId: place.id, target: { x: place.x, z: place.z } });
    expect(first.facing).toBeCloseTo(place.facing);
    expect(plan(studio.members[1], "working").kind).toBe("work");
    // The chairs at the team room's table stay free: this meeting is not there.
    expect(campus.layout.spots.filter((s) => s.kind === "meeting").every((s) => book.isFree(s.id))).toBe(true);
  });
});

describe("a board meeting of a team with a lead", () => {
  const led = campusOf(12, [5], [3]);
  const studio = studioOfTeam(led.layout, "team-0")!;
  const places = huddlePlaces(led.layout, led.grid, studio);

  it("gives the lead the centre of the front arc, wherever it comes in the list, and everybody else a place of their own", () => {
    const lead = studio.leadId!;
    expect(lead).toBe(led.teams[0].members[3]);
    const seats = boardSeats(led.layout, studio, studio.members);
    expect(seats[lead].spotId).toBe(`fan:${studio.deptId}:0:0`);
    const ids = Object.values(seats).map((s) => s.spotId);
    expect(new Set(ids).size).toBe(studio.members.length);
    expect(ids.every((id) => places.some((p) => p.id === id))).toBe(true);
  });

  it("uses the lead's place for somebody else when the lead is not among those called", () => {
    const withoutLead = studio.members.filter((id) => id !== studio.leadId);
    const seats = boardSeats(led.layout, studio, withoutLead);
    expect(Object.keys(seats)).toEqual(withoutLead);
    expect(Object.values(seats).map((s) => s.spotId)).toContain(`fan:${studio.deptId}:0:0`);
  });

  it("is the same seating as ever for a team without a lead", () => {
    const plain = { ...studio, leadId: null };
    const before = boardSeats(led.layout, plain, studio.members);
    // The first member takes the first place of the front arc, as it always did.
    expect(before[studio.members[0]].spotId).toBe(`fan:${studio.deptId}:0:0`);
    expect(Object.values(before).map((s) => s.spotId)).toEqual(places.slice(0, studio.members.length)
      .map((p, i) => ({ p, i, from: Math.hypot(p.x - studio.board!.x, p.z - studio.board!.z) }))
      .sort((a, b) => Math.round((a.from - b.from) * 10) || a.i - b.i).map((x) => x.p.id));
  });
});
