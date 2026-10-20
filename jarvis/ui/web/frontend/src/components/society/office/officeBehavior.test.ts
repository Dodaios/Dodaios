import { describe, expect, it } from "vitest";
import type { AgentRunState } from "../data";
import { allDesks, buildOfficeLayout, seatOf, standOf, type DeskSlot, type OfficeAgentInput, type Point } from "./officeLayout";
import { BODY_SPACING, paceFor } from "./officeMotion";
import { buildNavGrid, findPath, isWalkable } from "./officeNav";
import {
  COMMONS_WEIGHTS, HANDOFF_DWELL_MS, PERSON_SPACE_M, POOL_IDLE_WEIGHTS, TEAM_IDLE_WEIGHTS, TRIP_REACH, createRng, dwellAfter, planFor, planStillValid, shownActivity, SpotBook,
  tripReach, type ActivityKind, type Plan, type PlanInput,
} from "./officeBehavior";
import { HUDDLE_SPACE_M, homeStudio, huddlePlaces, leadPlace, mateDesks, studioRect, studioOfTeam, visitSlots } from "./officeTeams";
import { pathLength } from "./officeWalk";
import { campusOf } from "./officeFixtures";

const roster: OfficeAgentInput[] = Array.from({ length: 8 }, (_, i) => ({
  agentId: `a${i}`, name: `a${i}`, tier: "specialist", providerLabel: i % 2 ? "Codex" : "Gemini", state: "idle", createdMs: i,
}));
// A floor without team studios (the coding floor): the plain idle day.
const layout = buildOfficeLayout(roster, { variant: "coding" });
const grid = buildNavGrid(layout);
const deskOf = (id: string): DeskSlot => allDesks(layout).find((d) => d.agentId === id)!;

function input(agentId: string, state: AgentRunState, extra: Partial<PlanInput> = {}): PlanInput {
  return {
    agentId, state, desk: deskOf(agentId), layout, grid, rng: createRng(agentId), book: new SpotBook(),
    previous: null, workingColleagues: [], calledTo: null, ...extra,
  };
}

describe("createRng", () => {
  it("is deterministic per seed and stays in [0, 1)", () => {
    const a = createRng("x"), b = createRng("x"), c = createRng("y");
    const sa = Array.from({ length: 20 }, a);
    expect(Array.from({ length: 20 }, b)).toEqual(sa);
    expect(Array.from({ length: 20 }, c)).not.toEqual(sa);
    expect(sa.every((v) => v >= 0 && v < 1)).toBe(true);
  });
});

describe("SpotBook", () => {
  it("gives a spot to one agent at a time and one spot per agent", () => {
    const book = new SpotBook();
    expect(book.claim("s1", "a")).toBe(true);
    expect(book.claim("s1", "b")).toBe(false);
    expect(book.holder("s1")).toBe("a");
    expect(book.spotOf("a")).toBe("s1");
    expect(book.claim("s2", "a")).toBe(true);
    expect(book.isFree("s1")).toBe(true);
    expect(book.holder("s2")).toBe("a");
    book.release("a");
    expect(book.isFree("s2")).toBe(true);
    expect(book.holder("s2")).toBeNull();
    expect(book.spotOf("a")).toBeNull();
  });
});

describe("planFor on a floor without studios", () => {
  it("seats a working agent at its desk, typing, until the state changes", () => {
    const plan = planFor(input("a1", "working"));
    const seat = seatOf(deskOf("a1"));
    expect(plan).toMatchObject({ kind: "work", target: { x: seat.x, z: seat.z }, facing: seat.facing, pose: "work", dwellMs: Infinity });
  });

  it("puts a deskless worker at a window", () => {
    const plan = planFor(input("ghost", "working", { desk: null }));
    expect(plan.kind).toBe("work");
    expect(plan.pose).toBe("work");
    expect(plan.spotId).toMatch(/^window-/);
  });

  it("stands a waiting agent beside its chair, waving", () => {
    const plan = planFor(input("a2", "waiting"));
    const stand = standOf(deskOf("a2"));
    expect(plan).toMatchObject({ kind: "wait", target: { x: stand.x, z: stand.z }, pose: "wave", dwellMs: Infinity });
  });

  it("sends paused agents to sleep, then to the couch, then to their desk", () => {
    const book = new SpotBook();
    const sleepSpots = layout.spots.filter((s) => s.pose === "sleep").length;
    // More seats than paused agents: the couches fill up with whoever is left after the beds.
    const couchSeats = Math.min(layout.spots.filter((s) => s.kind === "couch" && s.pose !== "sleep").length, roster.length - sleepSpots);
    const plans = roster.map((a) => planFor(input(a.agentId, "paused", { book })));
    expect(plans.every((p) => p.kind === "nap" && p.dwellMs === Infinity)).toBe(true);
    expect(plans.filter((p) => p.pose === "sleep")).toHaveLength(sleepSpots);
    const onCouch = plans.filter((p) => p.spotId && layout.spots.find((s) => s.id === p.spotId)?.kind === "couch" && p.pose === "sit");
    expect(onCouch).toHaveLength(couchSeats);
    const atDesk = plans.filter((p) => p.spotId === null);
    expect(atDesk.length).toBe(roster.length - sleepSpots - couchSeats);
    for (const p of atDesk) expect(p.pose).toBe("sit");
    const ids = plans.map((p) => p.spotId).filter(Boolean);
    expect(new Set(ids).size).toBe(ids.length);
  });

  it("answers a call by walking up to the caller and talking", () => {
    const caller = layout.checkpoints.find((c) => c.id === "break")!;
    const plan = planFor(input("a3", "idle", { calledTo: caller }));
    expect(plan.kind).toBe("called");
    expect(plan.pose).toBe("talk");
    expect(plan.dwellMs).toBe(15000);
    expect(isWalkable(grid, plan.target)).toBe(true);
    expect(Math.hypot(plan.target.x - caller.x, plan.target.z - caller.z)).toBeLessThan(2);
  });

  it("keeps a working agent at its screen even when called", () => {
    const caller = layout.checkpoints.find((c) => c.id === "break")!;
    expect(planFor(input("a3", "working", { calledTo: caller })).kind).toBe("work");
  });

  function idleSequence(seed: string, steps: number, colleagues: PlanInput["workingColleagues"] = []): ActivityKind[] {
    const rng = createRng(seed);
    const book = new SpotBook();
    const kinds: ActivityKind[] = [];
    let previous: ActivityKind | null = null;
    for (let i = 0; i < steps; i += 1) {
      const plan = planFor({ ...input("a4", "idle", { rng, book, previous, workingColleagues: colleagues }) });
      kinds.push(plan.kind);
      previous = plan.kind;
      expect(plan.dwellMs).toBeGreaterThanOrEqual(6000);
      expect(plan.dwellMs).toBeLessThanOrEqual(45000);
    }
    return kinds;
  }

  it("gives the same idle life for the same seed and never repeats an activity back to back", () => {
    const colleagues = [{ agentId: "a5", desk: deskOf("a5") }];
    const first = idleSequence("seed-1", 200, colleagues);
    expect(idleSequence("seed-1", 200, colleagues)).toEqual(first);
    expect(idleSequence("seed-2", 200, colleagues)).not.toEqual(first);
    for (let i = 1; i < first.length; i += 1) {
      // A full-spot fallback may land on wander after wander; a chosen activity never repeats.
      if (first[i] !== "wander") expect(first[i]).not.toBe(first[i - 1]);
    }
    expect(new Set(first).size).toBeGreaterThan(6);
    // No studios, no team life.
    for (const kind of ["huddle", "mate", "studio", "handoff"]) expect(first).not.toContain(kind);
  });

  it("looks in on a working colleague from a place of its own beside their chair, without pretending to talk", () => {
    const colleague = { agentId: "a5", desk: deskOf("a5") };
    const seat = seatOf(colleague.desk);
    const book = new SpotBook();
    const visits: Plan[] = [];
    for (let i = 0; i < 400 && visits.length < 2; i += 1) {
      const plan = planFor(input(`a${visits.length === 0 ? 4 : 6}`, "idle", { rng: createRng(`visit-${i}`), book, workingColleagues: [colleague] }));
      if (plan.kind === "visit") visits.push(plan); else book.release(`a${visits.length === 0 ? 4 : 6}`);
    }
    expect(visits).toHaveLength(2);
    for (const plan of visits) {
      expect(plan).toMatchObject({ with: "a5", pose: "stand" });
      expect(plan.spotId).toMatch(/^visit:/);
      expect(isWalkable(grid, plan.target)).toBe(true);
      // Beside the chair: within reach, outside the body spacing, looking at the colleague.
      const gap = Math.hypot(plan.target.x - seat.x, plan.target.z - seat.z);
      expect(gap).toBeGreaterThan(BODY_SPACING);
      expect(gap).toBeLessThan(1.3);
      expect(plan.facing).toBeCloseTo(Math.atan2(seat.x - plan.target.x, seat.z - plan.target.z));
    }
    // Two visitors never stand on each other.
    expect(Math.hypot(visits[0].target.x - visits[1].target.x, visits[0].target.z - visits[1].target.z)).toBeGreaterThanOrEqual(BODY_SPACING);
    expect(visits[0].spotId).not.toBe(visits[1].spotId);
  });

  it("falls back to wandering when every spot of the chosen kind is taken", () => {
    const book = new SpotBook();
    for (const spot of layout.spots) book.claim(spot.id, `holder-${spot.id}`);
    const office = layout.departments;
    for (let i = 0; i < 50; i += 1) {
      const plan = planFor(input("a6", "idle", { rng: createRng(`full-${i}`), book, desk: null }));
      expect(["wander", "visit"]).toContain(plan.kind);
      expect(plan.spotId).toBeNull();
      if (plan.kind === "wander") {
        expect(plan.facing).toBeNull();
        expect(isWalkable(grid, plan.target)).toBe(true);
        expect(office.some((d) => plan.target.x >= d.minX - 3.3 && plan.target.x <= d.maxX + 3.3)).toBe(true);
      }
    }
  });

  it("releases an agent's spot when it goes back to work", () => {
    const book = new SpotBook();
    const idle = planFor(input("a7", "paused", { book }));
    expect(idle.spotId).not.toBeNull();
    expect(book.holder(idle.spotId!)).toBe("a7");
    planFor(input("a7", "working", { book }));
    expect(book.isFree(idle.spotId!)).toBe(true);
  });
});

describe("SpotBook.retain", () => {
  it("keeps claims on surviving spots and drops the rest", () => {
    const book = new SpotBook();
    book.claim("couch-a1", "a1");
    book.claim("window-dept-9", "a2");
    book.retain(new Set(["couch-a1"]));
    expect(book.holder("couch-a1")).toBe("a1");
    expect(book.isFree("window-dept-9")).toBe(true);
    // The dropped agent can claim again.
    expect(book.claim("couch-a2", "a2")).toBe(true);
  });

  it("keeps the places the plan does not list, so a rebuilt floor never hands an occupied one out again", () => {
    const book = new SpotBook();
    book.claim("fan:studio-team-0:0:1", "a1");
    book.claim("visit:6.32,-3.87", "a2");
    book.claim("couch-of-the-old-plan", "a3");
    book.retain(new Set(["couch-a1"]));
    expect(book.holder("fan:studio-team-0:0:1")).toBe("a1");
    expect(book.holder("visit:6.32,-3.87")).toBe("a2");
    expect(book.isFree("couch-of-the-old-plan")).toBe(true);
    // Nobody else is given the place at the board while a1 stands on it.
    expect(book.claim("fan:studio-team-0:0:1", "a4")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// Team studios: agents belong somewhere.
// ---------------------------------------------------------------------------

// 26 agents: teams of 7, 6 and 5, and 8 agents without a team (the pool).
const campus = campusOf(26, [7, 6, 5]);
const cDesk = (id: string): DeskSlot | null => allDesks(campus.layout).find((d) => d.agentId === id) ?? null;

function cInput(agentId: string, state: AgentRunState, extra: Partial<PlanInput> = {}): PlanInput {
  return {
    agentId, state, desk: cDesk(agentId), layout: campus.layout, grid: campus.grid, rng: createRng(agentId), book: new SpotBook(),
    previous: null, workingColleagues: [], calledTo: null, ...extra,
  };
}

/** A plan keeps the agent at home when it is in its studio or a few steps round the corner. */
function atHome(agentId: string, plan: Plan): boolean {
  const studio = homeStudio(campus.layout, agentId, cDesk(agentId))!;
  const rect = studioRect(campus.layout, studio);
  const reach = Math.hypot(rect.maxX - rect.minX, rect.maxZ - rect.minZ) / 2 + 3.5;
  return Math.hypot(plan.target.x - studio.centre.x, plan.target.z - studio.centre.z) <= reach;
}

function idleDay(agentId: string, steps: number, seed = agentId): Plan[] {
  const rng = createRng(seed);
  const book = new SpotBook();
  const studio = homeStudio(campus.layout, agentId, cDesk(agentId))!;
  const mates = mateDesks(campus.layout, studio, agentId).map((d) => ({ agentId: d.agentId as string, desk: d }));
  const plans: Plan[] = [];
  let previous: ActivityKind | null = null;
  let position: Point | null = null;
  for (let i = 0; i < steps; i += 1) {
    const plan = planFor(cInput(agentId, "idle", { rng, book, previous, position, matesAtDesk: mates }));
    plans.push(plan);
    previous = plan.kind;
    position = plan.target;
  }
  return plans;
}

describe("the campus", () => {
  it("gives every team a studio with a board and places to stand at it, and seats the rest in the pool", () => {
    const studios = campus.layout.studios ?? [];
    expect(studios.filter((s) => s.teamId !== null).map((s) => s.members.length)).toEqual([7, 6, 5]);
    expect(studios.filter((s) => s.teamId === null).flatMap((s) => s.members)).toHaveLength(8);
    for (const studio of studios.filter((s) => s.teamId !== null)) {
      expect(studio.board).not.toBeNull();
      const places = huddlePlaces(campus.layout, campus.grid, studio);
      // Room for the whole team at its board, in loose arcs: everybody has more than a metre to themselves.
      expect(places.length).toBeGreaterThanOrEqual(studio.members.length);
      for (const [i, p] of places.entries()) {
        expect(isWalkable(campus.grid, p), p.id).toBe(true);
        // Facing the board, from in front of it.
        expect(p.facing).toBeCloseTo(Math.atan2(studio.board!.x - p.x, studio.board!.z - p.z));
        for (const q of places.slice(i + 1)) expect(Math.hypot(p.x - q.x, p.z - q.z), `${p.id} ${q.id}`).toBeGreaterThanOrEqual(HUDDLE_SPACE_M);
      }
    }
  });

  it("offers a visitor a walkable place of its own at every occupied desk", () => {
    for (const desk of allDesks(campus.layout).filter((d) => d.agentId && !d.size)) {
      const slots = visitSlots(desk, campus.grid);
      expect(slots.length, desk.id).toBeGreaterThanOrEqual(1);
      const seat = seatOf(desk);
      for (const slot of slots) expect(Math.hypot(slot.x - seat.x, slot.z - seat.z), slot.id).toBeGreaterThan(BODY_SPACING);
    }
  });
});

describe("idle life with a home", () => {
  it("weights a team member four fifths at home and a pool agent far more towards the shared places", () => {
    const share = (table: readonly (readonly [string, number])[], keys: string[]) =>
      table.filter(([k]) => keys.includes(k)).reduce((s, [, w]) => s + w, 0) / table.reduce((s, [, w]) => s + w, 0);
    expect(share(TEAM_IDLE_WEIGHTS, ["desk", "mate", "huddle", "studio", "near"])).toBeCloseTo(0.8, 2);
    expect(share(TEAM_IDLE_WEIGHTS, ["commons"])).toBeCloseTo(0.14, 2);
    expect(share(POOL_IDLE_WEIGHTS, ["commons"])).toBeCloseTo(0.4, 2);
    expect(POOL_IDLE_WEIGHTS.map(([k]) => k)).not.toContain("huddle");
    expect(COMMONS_WEIGHTS.every(([, w]) => w > 0)).toBe(true);
  });

  it("keeps a team member mostly in and around its own studio", () => {
    const plans = idleDay("a1", 400);
    const home = plans.filter((p) => atHome("a1", p)).length / plans.length;
    expect(home).toBeGreaterThan(0.68);
    expect(home).toBeLessThan(0.95);
    const kinds = new Set(plans.map((p) => p.kind));
    for (const kind of ["desk", "mate", "huddle", "studio"] as const) expect(kinds, kind).toContain(kind);
    // It still gets out: a coffee or the couch now and then.
    expect(plans.some((p) => !atHome("a1", p))).toBe(true);
  });

  it("sends an agent without a team to the shared places far more often", () => {
    const member = idleDay("a1", 400).filter((p) => !atHome("a1", p)).length;
    const pooled = idleDay("a20", 400).filter((p) => !atHome("a20", p)).length;
    expect(homeStudio(campus.layout, "a20", cDesk("a20"))!.teamId).toBeNull();
    expect(pooled).toBeGreaterThan(member * 1.5);
    expect(idleDay("a20", 400).map((p) => p.kind)).not.toContain("huddle");
  });

  it("is the same day for the same agent, and a different one for another", () => {
    const day = idleDay("a3", 120).map((p) => [p.kind, p.spotId, p.target.x, p.target.z, p.dwellMs]);
    expect(idleDay("a3", 120).map((p) => [p.kind, p.spotId, p.target.x, p.target.z, p.dwellMs])).toEqual(day);
    expect(idleDay("a4", 120).map((p) => p.kind)).not.toEqual(day.map((d) => d[0]));
  });

  it("never takes the same home activity twice in a row, and every place is real floor or a real seat", () => {
    const plans = idleDay("a2", 300);
    for (let i = 1; i < plans.length; i += 1) {
      if (["desk", "mate", "huddle"].includes(plans[i].kind)) expect(plans[i].kind, `step ${i}`).not.toBe(plans[i - 1].kind);
    }
    for (const plan of plans) {
      if (plan.pose === "stand") expect(isWalkable(campus.grid, plan.target), `${plan.kind} ${plan.spotId}`).toBe(true);
      expect(findPath(campus.grid, campus.layout.spawn, plan.target), `${plan.kind} ${plan.spotId}`).not.toBeNull();
    }
  });

  it("stands at a teammate's desk only while that teammate sits there, and only watches", () => {
    const studio = homeStudio(campus.layout, "a1", cDesk("a1"))!;
    const mate = mateDesks(campus.layout, studio, "a1")[0];
    const seat = seatOf(mate);
    for (let i = 0; i < 300; i += 1) {
      const plan = planFor(cInput("a1", "idle", { rng: createRng(`mate-${i}`), matesAtDesk: [{ agentId: mate.agentId as string, desk: mate }] }));
      if (plan.kind !== "mate") continue;
      expect(plan).toMatchObject({ with: mate.agentId, pose: "stand" });
      expect(Math.hypot(plan.target.x - seat.x, plan.target.z - seat.z)).toBeLessThan(1.3);
      // Nobody at their desk: nobody to look in on.
      for (let j = 0; j < 200; j += 1) expect(planFor(cInput("a1", "idle", { rng: createRng(`alone-${j}`), matesAtDesk: [] })).kind).not.toBe("mate");
      return;
    }
    throw new Error("no visit to a teammate in 300 seeds");
  });

  it("gives everyone a place of their own, whatever they pick", () => {
    const book = new SpotBook();
    const taken = new Map<string, string>();
    for (let round = 0; round < 6; round += 1) {
      for (const agent of campus.roster) {
        const plan = planFor(cInput(agent.agentId, "idle", { rng: createRng(`${agent.agentId}:${round}`), book }));
        if (plan.spotId) {
          for (const [id, spot] of taken) if (id !== agent.agentId) expect(spot, `${agent.agentId} vs ${id}`).not.toBe(plan.spotId);
          taken.set(agent.agentId, plan.spotId);
        } else taken.delete(agent.agentId);
      }
    }
  });
});

describe("a round of the team", () => {
  const team = (campus.layout.studios ?? []).find((s) => s.teamId === "team-0")!;

  it("brings the free members to their own studio board, each on a place of its own, until it ends", () => {
    const book = new SpotBook();
    const plans = team.members.map((id) => planFor(cInput(id, "idle", { book, round: { speaker: false } })));
    const places = huddlePlaces(campus.layout, campus.grid, team);
    for (const plan of plans) {
      expect(plan).toMatchObject({ kind: "huddle", pose: "stand", dwellMs: Infinity });
      const place = places.find((p) => p.id === plan.spotId)!;
      expect(place).toBeDefined();
      // Facing the board.
      expect(plan.facing).toBeCloseTo(place.facing);
      expect(Math.hypot(plan.target.x - team.board!.x, plan.target.z - team.board!.z)).toBeLessThan(5);
    }
    expect(new Set(plans.map((p) => p.spotId)).size).toBe(team.members.length);
  });

  it("never pulls a working member away from its screen, nor a waiting or a resting one", () => {
    const id = team.members[2];
    const seat = seatOf(cDesk(id)!);
    expect(planFor(cInput(id, "working", { round: { speaker: false } }))).toMatchObject({ kind: "work", target: { x: seat.x, z: seat.z } });
    expect(planFor(cInput(id, "waiting", { round: { speaker: false } })).kind).toBe("wait");
    expect(planFor(cInput(id, "paused", { round: { speaker: false } })).kind).toBe("nap");
  });

  it("places the member contributing right now at the board, although its run state reads working", () => {
    const plan = planFor(cInput(team.members[1], "working", { round: { speaker: true } }));
    expect(plan.kind).toBe("huddle");
    expect(huddlePlaces(campus.layout, campus.grid, team).map((p) => p.id)).toContain(plan.spotId);
  });

  it("fills the arc nearest the board first, so nobody has to squeeze through the people already there", () => {
    const book = new SpotBook();
    const board = team.board!;
    const places = huddlePlaces(campus.layout, campus.grid, team);
    const depth = (id: string | null) => { const p = places.find((q) => q.id === id)!; return Math.hypot(p.x - board.x, p.z - board.z); };
    const depths = team.members.map((id) => depth(planFor(cInput(id, "idle", { book, round: { speaker: false } })).spotId));
    for (let i = 1; i < depths.length; i += 1) expect(depths[i]).toBeGreaterThanOrEqual(depths[i - 1] - 0.01);
    expect(depths[0]).toBeLessThan(depths[depths.length - 1]);
  });

  it("leaves the person room: nobody takes a place on the person's toes, and whoever stands there moves aside", () => {
    const places = huddlePlaces(campus.layout, campus.grid, team);
    const person = { x: places[0].x + 0.2, z: places[0].z };
    const book = new SpotBook();
    const plans = team.members.slice(0, 4).map((id) => planFor(cInput(id, "idle", { book, person, round: { speaker: false } })));
    for (const plan of plans) expect(Math.hypot(plan.target.x - person.x, plan.target.z - person.z)).toBeGreaterThanOrEqual(PERSON_SPACE_M);
    // An agent already standing where the person walks to gives the place up for another one.
    const mover = team.members[5];
    const before = planFor(cInput(mover, "idle", { book, round: { speaker: false } }));
    const here = { x: before.target.x, z: before.target.z + 0.3 };
    const after = planFor(cInput(mover, "idle", { book, person: here, round: { speaker: false } }));
    expect(after.kind).toBe("huddle");
    expect(after.spotId).not.toBe(before.spotId);
    expect(Math.hypot(after.target.x - here.x, after.target.z - here.z)).toBeGreaterThanOrEqual(PERSON_SPACE_M);
    // With no other place left it stays rather than leaving the round.
    const full = new SpotBook();
    for (const p of places) if (p.id !== before.spotId) full.claim(p.id, `holder-${p.id}`);
    full.claim(before.spotId!, mover);
    expect(planFor(cInput(mover, "idle", { book: full, person: here, round: { speaker: false } })).spotId).toBe(before.spotId);
  });

  it("keeps a member on its place when it is planned again mid-round", () => {
    const book = new SpotBook();
    const id = team.members[0];
    const first = planFor(cInput(id, "idle", { book, round: { speaker: false } }));
    for (let i = 0; i < 20; i += 1) {
      const again = planFor(cInput(id, i % 2 ? "working" : "idle", { book, rng: createRng(`again-${i}`), round: { speaker: true } }));
      expect(again.spotId).toBe(first.spotId);
    }
  });

  it("gathers a member that sits in another studio at the board of the team whose round it is", () => {
    const outsider = "a20";
    const plan = planFor(cInput(outsider, "idle", { round: { speaker: false, teamId: "team-0" } }));
    expect(plan.kind).toBe("huddle");
    expect(huddlePlaces(campus.layout, campus.grid, team).map((p) => p.id)).toContain(plan.spotId);
  });

  it("goes back to its desk first when the round has ended", () => {
    const id = team.members[3];
    const seat = seatOf(cDesk(id)!);
    for (let i = 0; i < 20; i += 1) {
      expect(planFor(cInput(id, "idle", { rng: createRng(`back-${i}`), backToDesk: true }))).toMatchObject({ kind: "desk", target: { x: seat.x, z: seat.z }, pose: "sit" });
    }
  });

  it("lets the person's call outrank a round", () => {
    const caller = campus.layout.checkpoints.find((c) => c.id === "break")!;
    expect(planFor(cInput(team.members[0], "idle", { calledTo: caller, round: { speaker: false } })).kind).toBe("called");
  });
});

describe("a team with a lead", () => {
  // The same campus, and the same with the first team led by its third member.
  const led = campusOf(26, [7, 6, 5], [2]);
  const team = studioOfTeam(led.layout, "team-0")!;
  const plain = studioOfTeam(campus.layout, "team-0")!;
  const places = huddlePlaces(led.layout, led.grid, team);
  const centre = leadPlace(places, team)!;
  const lInput = (agentId: string, state: AgentRunState, extra: Partial<PlanInput> = {}): PlanInput => ({
    agentId, state, desk: allDesks(led.layout).find((d) => d.agentId === agentId) ?? null, layout: led.layout, grid: led.grid,
    rng: createRng(agentId), book: new SpotBook(), previous: null, workingColleagues: [], calledTo: null, ...extra,
  });

  it("knows its lead, and the lead's place is the middle of the front arc", () => {
    expect(team.leadId).toBe(led.teams[0].members[2]);
    expect(plain.leadId).toBeNull();
    expect(centre.id).toBe(`fan:${team.deptId}:0:0`);
    const board = team.board!;
    const aside = (p: { x: number; z: number }) => Math.abs((p.x - board.x) * Math.cos(board.facing) - (p.z - board.z) * Math.sin(board.facing));
    const front = places.filter((p) => p.id.startsWith(`fan:${team.deptId}:0:`));
    for (const p of front) expect(aside(centre)).toBeLessThanOrEqual(aside(p) + 1e-6);
    // A studio without a lead has no special place.
    expect(leadPlace(huddlePlaces(campus.layout, campus.grid, plain), plain)).toBeNull();
  });

  it("stands the lead at the centre of the front arc in a round, whenever it comes", () => {
    const lead = team.leadId!;
    // First to arrive.
    expect(planFor(lInput(lead, "idle", { round: { speaker: false } })).spotId).toBe(centre.id);
    // Last to arrive: the others left the place free.
    const book = new SpotBook();
    const others = team.members.filter((id) => id !== lead).map((id) => planFor(lInput(id, "idle", { book, round: { speaker: false } })));
    expect(others.map((p) => p.spotId)).not.toContain(centre.id);
    expect(new Set(others.map((p) => p.spotId)).size).toBe(others.length);
    expect(planFor(lInput(lead, "idle", { book, round: { speaker: false } })).spotId).toBe(centre.id);
    // As the speaker, too.
    expect(planFor(lInput(lead, "working", { round: { speaker: true } })).spotId).toBe(centre.id);
  });

  it("does not move a working lead, and invents nothing for an idle one", () => {
    const lead = team.leadId!;
    expect(planFor(lInput(lead, "working", { round: { speaker: false } })).kind).toBe("work");
    expect(planFor(lInput(lead, "waiting", { round: { speaker: false } })).kind).toBe("wait");
    // No round: the lead's idle day is drawn exactly like a member's, place by place.
    const rng = () => createRng("same-seed");
    const asLead = Array.from({ length: 1 }, () => { const r = rng(); return Array.from({ length: 60 }, () => planFor(lInput(lead, "idle", { rng: r }))); })[0];
    const noLead = { ...led.layout, studios: (led.layout.studios ?? []).map((s) => ({ ...s, leadId: null })) };
    const r = rng();
    const asMember = Array.from({ length: 60 }, () => planFor(lInput(lead, "idle", { rng: r, layout: noLead })));
    expect(asLead.map((p) => [p.kind, p.spotId, p.target.x, p.target.z, p.dwellMs])).toEqual(asMember.map((p) => [p.kind, p.spotId, p.target.x, p.target.z, p.dwellMs]));
  });

  it("gives the lead's place to a member only when no other is left, and to the lead another when the person stands on it", () => {
    const lead = team.leadId!;
    const book = new SpotBook();
    for (const p of places) if (p.id !== centre.id) book.claim(p.id, `holder-${p.id}`);
    expect(planFor(lInput(team.members[0], "idle", { book, round: { speaker: false } })).spotId).toBe(centre.id);
    const plan = planFor(lInput(lead, "idle", { person: { x: centre.x, z: centre.z + 0.2 }, round: { speaker: false } }));
    expect(plan.kind).toBe("huddle");
    expect(plan.spotId).not.toBe(centre.id);
  });

  it("plans a team without a lead exactly as before", () => {
    // Round by round and seed by seed, the same places as on the campus that never heard of leads.
    const withNull = { ...campus.layout, studios: (campus.layout.studios ?? []).map((s) => ({ ...s, leadId: null })) };
    for (let seed = 0; seed < 20; seed += 1) {
      const a = new SpotBook(), b = new SpotBook();
      for (const id of plain.members) {
        const first = planFor(cInput(id, "idle", { book: a, rng: createRng(`${id}:${seed}`), round: { speaker: false } }));
        const second = planFor(cInput(id, "idle", { book: b, rng: createRng(`${id}:${seed}`), layout: withNull, round: { speaker: false } }));
        expect(second).toEqual(first);
      }
    }
  });
});

describe("a message walked over", () => {
  const giver = "a8", receiver = "a1";
  const receiverDesk = cDesk(receiver)!;

  it("takes the free sender to a place beside the receiver's chair, to talk for a moment", () => {
    const seat = seatOf(receiverDesk);
    const plan = planFor(cInput(giver, "idle", { handoff: { to: receiver, desk: receiverDesk, seated: true, at: seat } }));
    expect(plan).toMatchObject({ kind: "handoff", pose: "talk", with: receiver, dwellMs: HANDOFF_DWELL_MS });
    expect(plan.spotId).toMatch(/^visit:/);
    expect(isWalkable(campus.grid, plan.target)).toBe(true);
    const gap = Math.hypot(plan.target.x - seat.x, plan.target.z - seat.z);
    expect(gap).toBeGreaterThan(BODY_SPACING);
    expect(gap).toBeLessThan(1.3);
  });

  it("walks to where the receiver stands when it is away from its desk", () => {
    const at = campus.layout.spots.find((s) => s.kind === "coffee")!;
    const plan = planFor(cInput(giver, "idle", { position: campus.layout.spawn, handoff: { to: receiver, desk: receiverDesk, seated: false, at } }));
    expect(plan.kind).toBe("handoff");
    expect(isWalkable(campus.grid, plan.target)).toBe(true);
    const gap = Math.hypot(plan.target.x - at.x, plan.target.z - at.z);
    expect(gap).toBeGreaterThan(BODY_SPACING);
    expect(gap).toBeLessThan(1.6);
    expect(plan.facing).toBeCloseTo(Math.atan2(at.x - plan.target.x, at.z - plan.target.z));
  });

  it("never moves a sender that is working, waiting or resting", () => {
    const handoff = { to: receiver, desk: receiverDesk, seated: true, at: seatOf(receiverDesk) };
    expect(planFor(cInput(giver, "working", { handoff })).kind).toBe("work");
    expect(planFor(cInput(giver, "waiting", { handoff })).kind).toBe("wait");
    expect(planFor(cInput(giver, "paused", { handoff })).kind).toBe("nap");
  });

  it("is skipped when the receiver is nowhere to be found", () => {
    expect(planFor(cInput(giver, "idle", { handoff: { to: "gone", desk: null, seated: false, at: null } })).kind).not.toBe("handoff");
  });
});

describe("trips on a small roster", () => {
  it("reaches less far the fewer agents there are", () => {
    expect(tripReach(1)).toBe(TRIP_REACH.fewM);
    expect(tripReach(5)).toBe(TRIP_REACH.fewM);
    expect(tripReach(60)).toBe(TRIP_REACH.manyM);
    expect(tripReach(18)).toBeGreaterThan(TRIP_REACH.fewM);
    expect(tripReach(18)).toBeLessThan(TRIP_REACH.manyM);
  });

  it("keeps five agents round their studio and the commons near it instead of crossing the campus", () => {
    const small = campusOf(5, [3]);
    const desks = new Map(allDesks(small.layout).filter((d) => d.agentId).map((d) => [d.agentId as string, d]));
    const far: number[] = [];
    let trips = 0, longTrips = 0, plans = 0;
    for (const agent of small.roster) {
      const studio = homeStudio(small.layout, agent.agentId, desks.get(agent.agentId)!)!;
      const rng = createRng(agent.agentId);
      const book = new SpotBook();
      let previous: ActivityKind | null = null;
      for (let i = 0; i < 300; i += 1) {
        const plan = planFor({
          agentId: agent.agentId, state: "idle", desk: desks.get(agent.agentId)!, layout: small.layout, grid: small.grid, rng, book,
          previous, workingColleagues: [], calledTo: null,
        });
        previous = plan.kind;
        plans += 1;
        const away = Math.hypot(plan.target.x - studio.centre.x, plan.target.z - studio.centre.z);
        if (away > 14) { trips += 1; far.push(away); }
        if (away > 30) longTrips += 1;
      }
    }
    // The floor is far larger than that: without the bias its windows and far rooms would take a good share.
    const spread = Math.max(...small.layout.spots.map((s) => Math.hypot(s.x, s.z)));
    expect(spread).toBeGreaterThan(30);
    expect(trips).toBeGreaterThan(0);
    expect(longTrips / plans).toBeLessThan(0.03);
    expect(trips / plans).toBeLessThan(0.3);
  });

  it("still lets a full floor range further", () => {
    const share = (count: number, sizes: number[]) => {
      const floor = campusOf(count, sizes);
      const desks = new Map(allDesks(floor.layout).filter((d) => d.agentId).map((d) => [d.agentId as string, d]));
      let long = 0, plans = 0;
      for (const agent of floor.roster.slice(0, 5)) {
        const studio = homeStudio(floor.layout, agent.agentId, desks.get(agent.agentId)!)!;
        const rng = createRng(agent.agentId);
        const book = new SpotBook();
        for (let i = 0; i < 400; i += 1) {
          const plan = planFor({ agentId: agent.agentId, state: "idle", desk: desks.get(agent.agentId)!, layout: floor.layout, grid: floor.grid, rng, book, previous: null, workingColleagues: [], calledTo: null });
          plans += 1;
          if (Math.hypot(plan.target.x - studio.centre.x, plan.target.z - studio.centre.z) > 22) long += 1;
        }
      }
      return long / plans;
    };
    // The same five agents of the same first team, alone on the floor and among sixty.
    expect(share(60, [5, 9, 8, 7, 6, 6])).toBeGreaterThan(share(5, [5]));
  });
});

describe("what a name plate says", () => {
  it("calls idle life in the studio what it is, and keeps the team board for a real gathering", () => {
    // Standing at the board or beside a studio mate on an ordinary idle day says nothing about teamwork.
    expect(shownActivity("huddle", false)).toBe("studio");
    expect(shownActivity("mate", false)).toBe("studio");
    expect(shownActivity("mate", true)).toBe("studio");
    // A running round, or a meeting the person called at the board.
    expect(shownActivity("huddle", true)).toBe("huddle");
    // Everything else is itself.
    for (const kind of ["work", "wait", "desk", "coffee", "studio", "wander", "visit", "handoff", "called", "meeting"] as const) {
      expect(shownActivity(kind, false)).toBe(kind);
      expect(shownActivity(kind, true)).toBe(kind);
    }
  });

  it("is never the team board for an idle day without a round, whatever the agent picks", () => {
    for (const plan of idleDay("a1", 300)) expect(shownActivity(plan.kind, false)).not.toBe("huddle");
  });
});

describe("a rebuilt floor plan", () => {
  it("keeps a plan whose place is still there and drops one whose spot is gone or built over", () => {
    const spot = campus.layout.spots.find((s) => s.kind === "coffee")!;
    const atSpot: Plan = { kind: "coffee", target: { x: spot.x, z: spot.z }, facing: spot.facing, pose: "stand", dwellMs: 9000, spotId: spot.id, with: null };
    expect(planStillValid(atSpot, campus.layout, campus.grid)).toBe(true);
    expect(planStillValid({ ...atSpot, spotId: "coffee-of-another-floor" }, campus.layout, campus.grid)).toBe(false);
    expect(planStillValid({ ...atSpot, target: { x: spot.x + 2, z: spot.z } }, campus.layout, campus.grid)).toBe(false);
    const desk = cDesk("a1")!;
    const stroll: Plan = { kind: "studio", target: campus.layout.spawn, facing: null, pose: "stand", dwellMs: 8000, spotId: null, with: null };
    expect(planStillValid(stroll, campus.layout, campus.grid)).toBe(true);
    expect(planStillValid({ ...stroll, target: { x: desk.x, z: desk.z } }, campus.layout, campus.grid)).toBe(false);
    // A place of our own (at a board, beside a desk) holds while that board or desk still stands there.
    const studio = (campus.layout.studios ?? []).find((s) => s.teamId === "team-0")!;
    const place = huddlePlaces(campus.layout, campus.grid, studio)[0];
    const atBoard: Plan = { kind: "huddle", target: { x: place.x, z: place.z }, facing: place.facing, pose: "stand", dwellMs: Infinity, spotId: place.id, with: null };
    expect(planStillValid(atBoard, campus.layout, campus.grid)).toBe(true);
    const slot = visitSlots(desk, campus.grid)[0];
    const beside: Plan = { kind: "mate", target: { x: slot.x, z: slot.z }, facing: slot.facing, pose: "stand", dwellMs: 9000, spotId: slot.id, with: "a1" };
    expect(planStillValid(beside, campus.layout, campus.grid)).toBe(true);
    // The same plans on a floor where the team's studio stands elsewhere: the places are gone.
    const moved = campusOf(26, [5, 7, 6]);
    expect(planStillValid({ ...atBoard, spotId: "fan:studio-gone:0:0" }, moved.layout, moved.grid)).toBe(false);
    expect(planStillValid({ ...atBoard, target: { x: place.x + 3, z: place.z } }, campus.layout, campus.grid)).toBe(false);
    expect(planStillValid({ ...beside, spotId: "visit:999.00,999.00", target: { x: 999, z: 999 } }, campus.layout, campus.grid)).toBe(false);
    // Plans at the agent's own desk are checked by their desk, not here.
    expect(planStillValid({ ...stroll, kind: "work", target: { x: desk.x, z: desk.z } }, campus.layout, campus.grid)).toBe(true);
  });
});

describe("a floor several times larger", () => {
  it("stretches a stay after a long walk and leaves calls and open-ended stays alone", () => {
    const plan: Plan = { kind: "coffee", target: { x: 0, z: 0 }, facing: 0, pose: "stand", dwellMs: 10000, spotId: "coffee-1", with: null };
    expect(dwellAfter(plan, 3)).toBe(10000);
    expect(dwellAfter(plan, 54)).toBeCloseTo(128000, -2);
    expect(dwellAfter(plan, 500)).toBe(150000);
    expect(dwellAfter({ ...plan, dwellMs: Infinity }, 54)).toBe(Infinity);
    expect(dwellAfter({ ...plan, kind: "handoff" }, 54)).toBe(10000);
    expect(dwellAfter({ ...plan, kind: "called" }, 54)).toBe(10000);
  });

  it("shows people being somewhere: at any moment about one idle agent in six is on the move, the rest are somewhere", () => {
    // 60 idle agents over twenty simulated minutes, each living its seeded day on a shared reservation book.
    const big = campusOf(60, [10, 9, 8, 7, 6, 6]);
    const book = new SpotBook();
    const desks = new Map(allDesks(big.layout).filter((d) => d.agentId).map((d) => [d.agentId as string, d]));
    const people = big.roster.map((a) => ({
      id: a.agentId, rng: createRng(a.agentId), clock: 0, walked: 0, away: 0, at: seatOf(desks.get(a.agentId)!) as Point,
      previous: null as ActivityKind | null, seated: true,
    }));
    const END_S = 20 * 60;
    for (;;) {
      const person = people.reduce((a, b) => (a.clock <= b.clock ? a : b));
      if (person.clock >= END_S) break;
      const studio = homeStudio(big.layout, person.id, desks.get(person.id)!)!;
      const matesAtDesk = mateDesks(big.layout, studio, person.id)
        .filter((d) => people.find((p) => p.id === d.agentId)?.seated).map((d) => ({ agentId: d.agentId as string, desk: d }));
      const plan = planFor({
        agentId: person.id, state: "idle", desk: desks.get(person.id)!, layout: big.layout, grid: big.grid, rng: person.rng, book,
        previous: person.previous, workingColleagues: [], calledTo: null, position: person.at, matesAtDesk,
      });
      const path = findPath(big.grid, person.at, plan.target);
      expect(path, `${person.id} ${plan.kind}`).not.toBeNull();
      const metres = pathLength(person.at, path!);
      // The pace at the start of the leg is the fastest it gets; the walk is at least this long.
      const walkS = metres / paceFor(metres);
      const stayS = dwellAfter(plan, metres) / 1000;
      person.walked += walkS;
      if (Math.hypot(plan.target.x - studio.centre.x, plan.target.z - studio.centre.z) > 14) person.away += stayS;
      person.clock += walkS + stayS;
      person.at = plan.target;
      person.previous = plan.kind;
      person.seated = plan.kind === "desk";
    }
    const total = people.reduce((s, p) => s + p.clock, 0);
    const walking = people.reduce((s, p) => s + p.walked, 0) / total;
    expect(walking).toBeLessThan(0.22);
    expect(walking).toBeGreaterThan(0.05);
    // Nobody is a commuter, and the team members' time is spent near home.
    for (const p of people) expect(p.walked / p.clock, p.id).toBeLessThan(0.3);
    const members = people.filter((p) => homeStudio(big.layout, p.id, desks.get(p.id)!)!.teamId !== null);
    const awayShare = (list: typeof people) => list.reduce((s, p) => s + p.away, 0) / list.reduce((s, p) => s + p.clock, 0);
    expect(awayShare(members)).toBeLessThan(0.33);
    // Agents without a team are out and about clearly more.
    expect(awayShare(people.filter((p) => !members.includes(p)))).toBeGreaterThan(awayShare(members) * 1.25);
  });
});
