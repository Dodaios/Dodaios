import { describe, expect, it } from "vitest";
import { ambienceObstacles, type AgentsAmbienceKind } from "./agentsAmbience";
import { CAMPUS, MAX_STUDIOS, planStudios, STUDIO_SEAT_CAP, studioShape, studioWallRect } from "./campusLayout";
import {
  allDesks, ARCH, archPosts, benchPlanters, buildOfficeLayout, deskRect, FLOOR_EDGE, footprint, FURNITURE_SIZE, leadDesks, seatedCount, seatOf, standOf, STUDIO_BOARD_FACE, studioBoardFace,
  type OfficeAgentInput, type OfficeLayout, type OfficeTeamInput, type Point, type Rect,
} from "./officeLayout";
import { buildNavGrid, findPath, isWalkable } from "./officeNav";

const agent = (n: number, extra: Partial<OfficeAgentInput> = {}): OfficeAgentInput => ({
  agentId: `a${n}`, name: `Agent ${n}`, tier: "specialist", providerLabel: n % 2 ? "Codex" : "Claude", state: "idle", createdMs: n, ...extra,
});
const staff = (count: number): OfficeAgentInput[] => Array.from({ length: count }, (_, i) => agent(i + 1));
const team = (n: number, members: number[], extra: Partial<OfficeTeamInput> = {}): OfficeTeamInput => ({
  id: `team-${n}`, name: `Team ${n}`, members: members.map((m) => `a${m}`), createdMs: n * 10, ...extra,
});
/** `count` teams of `size`, filled with consecutive agents from a1 on. */
const teamsOf = (count: number, size: number): OfficeTeamInput[] =>
  Array.from({ length: count }, (_, t) => team(t + 1, Array.from({ length: size }, (_, i) => t * size + i + 1)));

const overlaps = (a: Rect, b: Rect) => a.minX < b.maxX - 1e-9 && b.minX < a.maxX - 1e-9 && a.minZ < b.maxZ - 1e-9 && b.minZ < a.maxZ - 1e-9;
const inside = (p: Point, r: Rect) => p.x >= r.minX && p.x <= r.maxX && p.z >= r.minZ && p.z <= r.maxZ;
const area = (r: Rect) => (r.maxX - r.minX) * (r.maxZ - r.minZ);
const size = (layout: OfficeLayout) => ({ w: layout.bounds.maxX - layout.bounds.minX, d: layout.bounds.maxZ - layout.bounds.minZ });
const seatOfAgent = (layout: OfficeLayout, id: string) => allDesks(layout).find((d) => d.agentId === id)?.id;
const kindsOf = (layout: OfficeLayout, ...kinds: string[]) => layout.zones!.filter((z) => kinds.includes(z.kind)).map((z) => z.kind);

/** The three sizes the floor must look right at: 5, 15 and 40 people. */
const SIZES: [string, OfficeAgentInput[], OfficeTeamInput[]][] = [
  ["5 agents, no team", staff(5), []],
  ["15 agents, 3 teams", staff(15), teamsOf(3, 4)],
  ["40 agents, 8 teams", staff(40), teamsOf(8, 4)],
];

describe("campus: who sits where", () => {
  it("gives every team a studio of its own and puts everyone else in the pool", () => {
    const layout = buildOfficeLayout(staff(9), { teams: [team(1, [1, 2, 3]), team(2, [4, 5])] });
    expect(layout.departments.map((d) => [d.id, d.label, d.teamId])).toEqual([
      ["studio-pool", "", null], ["studio-team-1", "Team 1", "team-1"], ["studio-team-2", "Team 2", "team-2"],
    ]);
    const studios = layout.studios!;
    expect(studios.map((s) => [s.deptId, s.teamId, s.name, s.members])).toEqual([
      ["studio-pool", null, "", ["a6", "a7", "a8", "a9"]],
      ["studio-team-1", "team-1", "Team 1", ["a1", "a2", "a3"]],
      ["studio-team-2", "team-2", "Team 2", ["a4", "a5"]],
    ]);
    // Each agent sits in its own studio's desks, in arrival order.
    for (const studio of studios) {
      const dept = layout.departments.find((d) => d.id === studio.deptId)!;
      expect(dept.desks.map((d) => d.agentId).filter(Boolean)).toEqual(studio.members);
    }
    expect(seatedCount(layout)).toBe(9);
  });

  it("seats an agent of several teams in the oldest one, ties by id", () => {
    const teams = [team(2, [1, 2], { createdMs: 50 }), team(1, [2, 3], { createdMs: 20 }), team(3, [3, 4], { createdMs: 20 })];
    const plans = planStudios(staff(4), teams);
    // Oldest first: team-1 and team-3 share an age, team-1 wins by id; team-2 is the youngest.
    expect(plans.map((p) => [p.teamId, p.members.map((a) => a.agentId)])).toEqual([
      [null, []], ["team-1", ["a2", "a3"]], ["team-3", ["a4"]], ["team-2", ["a1"]],
    ]);
    // The input order of the teams does not matter.
    expect(planStudios(staff(4), [...teams].reverse())).toEqual(plans);
  });

  it("keeps a studio for a team whose members are unknown, and never guesses a team lead", () => {
    const layout = buildOfficeLayout(staff(3), { teams: [team(1, [41, 42]), team(2, [1], { leadId: "a1" })] });
    const ghost = layout.studios!.find((s) => s.teamId === "team-1")!;
    expect(ghost.members).toEqual([]);
    expect(ghost.leadId).toBeNull();
    expect(layout.departments.find((d) => d.id === ghost.deptId)!.desks).toHaveLength(4);
    expect(layout.studios!.find((s) => s.teamId === "team-2")!.leadId).toBe("a1");
    expect(layout.studios![0].members).toEqual(["a2", "a3"]);
  });

  it("keeps lead-tier agents in the lead office even when a team lists them", () => {
    const roster = [agent(1, { tier: "lead" }), agent(2), agent(3)];
    const layout = buildOfficeLayout(roster, { teams: [team(1, [1, 2])] });
    expect(layout.lead.desks.map((d) => d.agentId)).toEqual(["a1"]);
    expect(layout.studios!.find((s) => s.teamId === "team-1")!.members).toEqual(["a2"]);
    // A third lead has no place in the office for two: it works from the pool.
    const three = buildOfficeLayout([1, 2, 3].map((n) => agent(n, { tier: "lead" })));
    expect(three.lead.desks.map((d) => d.agentId)).toEqual(["a1", "a2"]);
    expect(three.studios![0].members).toEqual(["a3"]);
  });

  it("never re-seats anyone while roster and teams are unchanged", () => {
    const roster = staff(23), teams = [team(1, [1, 2, 3, 4, 5]), team(2, [6, 7]), team(3, [8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19])];
    const before = buildOfficeLayout(roster, { teams });
    // A refetch: other object identities, another order, other run states, members listed in another order.
    const again = buildOfficeLayout([...roster].reverse().map((a) => ({ ...a, state: "working" as const })),
      { teams: [...teams].reverse().map((t) => ({ ...t, members: [...t.members].reverse() })) });
    expect(again).toEqual(before);
    // A newcomer without a team takes a pool desk; nobody in a team moves.
    const grown = buildOfficeLayout([...roster, agent(24)], { teams });
    for (const id of teams.flatMap((t) => t.members)) expect(seatOfAgent(grown, id), id).toBe(seatOfAgent(before, id));
    for (const dept of before.departments.filter((d) => d.teamId)) {
      const now = grown.departments.find((d) => d.id === dept.id)!;
      expect([now.minX, now.minZ, now.maxX, now.maxZ]).toEqual([dept.minX, dept.minZ, dept.maxX, dept.maxZ]);
    }
  });

  it("folds teams beyond the last cell into the pool and a team too large for one studio spills there", () => {
    const many = buildOfficeLayout(staff(30), { teams: teamsOf(14, 2) });
    expect(many.departments).toHaveLength(MAX_STUDIOS);
    expect(many.departments.filter((d) => d.teamId !== null)).toHaveLength(MAX_STUDIOS - 1);
    expect(seatedCount(many)).toBe(30);
    expect(many.studios![0].members).toEqual(["a23", "a24", "a25", "a26", "a27", "a28", "a29", "a30"]);
    const huge = buildOfficeLayout(staff(40), { teams: [team(1, Array.from({ length: 40 }, (_, i) => i + 1))] });
    expect(huge.studios!.find((s) => s.teamId === "team-1")!.members).toHaveLength(STUDIO_SEAT_CAP);
    expect(huge.studios![0].members).toHaveLength(40 - STUDIO_SEAT_CAP);
    expect(seatedCount(huge)).toBe(40);
  });

  it("opens a second pool studio only when the pool outgrows one", () => {
    const layout = buildOfficeLayout(staff(40));
    expect(layout.departments.map((d) => [d.id, d.teamId])).toEqual([["studio-pool", null], ["studio-pool-2", null]]);
    expect(seatedCount(layout)).toBe(40);
    expect(buildOfficeLayout(staff(STUDIO_SEAT_CAP)).departments).toHaveLength(1);
  });
});

describe("campus: a studio", () => {
  it("sizes the desks to the team: one free desk, whole pairs, as few benches as hold them", () => {
    const shape = (n: number) => studioShape(n).benches;
    expect(shape(0)).toEqual([2]);
    expect(shape(2)).toEqual([2]);
    expect(shape(5)).toEqual([3]);
    expect(shape(7)).toEqual([4]);
    expect(shape(8)).toEqual([3, 2]);
    expect(shape(12)).toEqual([4, 3]);
    expect(shape(STUDIO_SEAT_CAP)).toEqual([4, 4, 4, 4]);
    for (let n = 0; n <= STUDIO_SEAT_CAP; n += 1) {
      const s = studioShape(n);
      expect(s.seats, `${n} members`).toBeGreaterThanOrEqual(n);
      // Never a row of empty benches: at most three free desks, and that only in the smallest studio.
      expect(s.seats - n, `${n} members`).toBeLessThanOrEqual(n === 0 ? 4 : n < STUDIO_SEAT_CAP ? 3 : 0);
    }
    // Only the desks grow with the team: the huddle zone and the front zone are the same in every studio.
    expect(studioShape(12).depth - studioShape(2).depth).toBeCloseTo(4.2, 9);
    expect(studioShape(2).depth).toBeCloseTo(CAMPUS.studioHeader + 4.2 + CAMPUS.studioFront, 9);
  });

  it("has a name wall, a board on it, huddle places in front of the board and its own colour", () => {
    const layout = buildOfficeLayout(staff(20), { teams: [team(1, [1, 2]), team(2, [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14])] });
    const grid = buildNavGrid(layout);
    expect(new Set(layout.departments.map((d) => d.tint)).size).toBe(layout.departments.length);
    for (const studio of layout.studios!) {
      const dept = layout.departments.find((d) => d.id === studio.deptId)!;
      const board = layout.furniture.find((f) => f.id === studio.board!.id)!;
      expect(board.kind).toBe("studioBoard");
      expect(board.id).toBe(`studio-board:${dept.id}`);
      // The board stands inside the studio, right in front of the name wall, facing south.
      const box = footprint(board), wall = studioWallRect(dept);
      expect(box.minX).toBeGreaterThan(wall.minX);
      expect(box.maxX).toBeLessThan(wall.maxX);
      expect(box.minZ).toBeGreaterThanOrEqual(wall.maxZ);
      expect(box.minZ - wall.maxZ).toBeLessThan(0.1);
      expect(layout.obstacles.some((o) => o.minX === wall.minX && o.minZ === wall.minZ && o.maxX === wall.maxX)).toBe(true);
      // Its face is where the layout says, inside the board's footprint.
      const face = studioBoardFace(studio.board!);
      expect(face.rotationY).toBe(0);
      expect(face.size).toEqual([STUDIO_BOARD_FACE.w, STUDIO_BOARD_FACE.h]);
      expect(face.position[0]).toBe(board.x);
      expect(face.position[2] - board.z).toBeCloseTo(STUDIO_BOARD_FACE.z, 9);
      expect(face.position[2]).toBeLessThan(box.maxZ);
      // Huddle places: at least as many as the team (up to six), apart, walkable, facing the board, clear of the desks.
      const spots = studio.huddleSpotIds.map((id) => layout.spots.find((s) => s.id === id)!);
      expect(spots.length).toBeGreaterThanOrEqual(Math.max(4, Math.min(6, studio.members.length)));
      spots.forEach((spot, n) => {
        expect(spot.id).toBe(`huddle:${dept.id}:${n}`);
        expect([spot.kind, spot.pose, spot.room]).toEqual(["huddle", "stand", "floor"]);
        expect(isWalkable(grid, spot), spot.id).toBe(true);
        expect(inside(spot, dept), spot.id).toBe(true);
        const ahead = { x: spot.x + Math.sin(spot.facing) * 0.5, z: spot.z + Math.cos(spot.facing) * 0.5 };
        expect(Math.hypot(ahead.x - studio.board!.x, ahead.z - studio.board!.z)).toBeLessThan(Math.hypot(spot.x - studio.board!.x, spot.z - studio.board!.z));
        for (const other of spots) if (other !== spot) expect(Math.hypot(other.x - spot.x, other.z - spot.z)).toBeGreaterThanOrEqual(0.75);
        for (const desk of dept.desks) expect(Math.hypot(seatOf(desk).x - spot.x, seatOf(desk).z - spot.z)).toBeGreaterThan(1.5);
      });
      expect(inside(studio.centre, dept)).toBe(true);
      // Every desk stands inside its studio.
      for (const desk of dept.desks) expect(inside(desk, dept), desk.id).toBe(true);
    }
  });

  it("is a furnished room at every team size: screens on both sides, a planted front with the entrance, sofa, table, storage", () => {
    const layout = buildOfficeLayout(staff(15), { teams: [team(1, [1, 2, 3]), team(2, [4, 5, 6, 7, 8, 9, 10, 11, 12])] });
    const grid = buildNavGrid(layout);
    const item = (id: string) => layout.ambience!.find((i) => i.id === id);
    for (const dept of layout.departments) {
      const cx = (dept.minX + dept.maxX) / 2, cz = (dept.minZ + dept.maxZ) / 2;
      // A whole cell, whatever the head count.
      expect(dept.maxX - dept.minX).toBeCloseTo(CAMPUS.cellW, 9);
      for (const part of ["cabinet", "sofa", "table", "front-w", "front-e", "screen-e"]) expect(item(`${dept.id}-${part}`), `${dept.id}-${part}`).toBeDefined();
      for (const part of ["cabinet", "sofa", "table"]) {
        const piece = item(`${dept.id}-${part}`)!;
        expect(piece.minX >= dept.minX && piece.maxX <= dept.maxX && piece.minZ >= dept.minZ && piece.maxZ <= dept.maxZ, piece.id).toBe(true);
        // In the studio's own colour where the piece wears one.
        if (part !== "table") expect(piece.tint).toBe(dept.tint);
      }
      // Both sides are closed over the studio's whole depth; the middle of the front is the way in.
      for (const x of [dept.minX + 0.06, dept.maxX - 0.06]) {
        for (const z of [dept.minZ + 1, cz, dept.maxZ - 1]) expect(isWalkable(grid, { x, z }), `side ${x},${z}`).toBe(false);
      }
      for (const dz of [-0.9, -0.37, 0.6]) expect(isWalkable(grid, { x: cx, z: dept.maxZ + dz }), `entrance ${dz}`).toBe(true);
      for (const x of [dept.minX + 1.5, dept.maxX - 1.5]) expect(isWalkable(grid, { x, z: dept.maxZ - 0.37 }), `front ${x}`).toBe(false);
      // Somewhere to sit and somewhere to stand, each a spot of its own.
      for (const id of [`${dept.id}-sofa-0`, `${dept.id}-sofa-1`, `${dept.id}-table-0`, `${dept.id}-table-1`]) {
        const spot = layout.spots.find((s) => s.id === id)!;
        expect(spot, id).toBeDefined();
        expect(inside(spot, dept), id).toBe(true);
      }
    }
    // Two studios shoulder to shoulder share one screen: the pool (west of the boulevard) stands alone, the two
    // teams east of the boulevard... do not: the second team took the cell on the pool's other side.
    const [pool, first, second] = layout.departments;
    expect(first.minX).toBeCloseTo(CAMPUS.boulevard / 2, 9);
    expect(pool.maxX).toBeCloseTo(-CAMPUS.boulevard / 2, 9);
    expect(second.maxX).toBeCloseTo(pool.minX, 9);
    // The shared screen stands on the line between the two and wears neither colour.
    const shared = item(`${second.id}-screen-e`)!;
    expect((shared.minX + shared.maxX) / 2).toBeCloseTo(pool.minX, 9);
    expect(shared.tint).toBeUndefined();
    expect(item(`${pool.id}-screen-w`)).toBeUndefined();
    expect(item(`${second.id}-screen-w`)!.tint).toBe(second.tint);
  });
});

describe("campus: a team's lead", () => {
  const roster = staff(8);
  const members = [1, 2, 3, 4, 5];
  const plan = (leadId?: string | null, extra: OfficeTeamInput[] = []) =>
    buildOfficeLayout(roster, { teams: [team(1, members, leadId === undefined ? {} : { leadId }), ...extra] });
  const studioOf = (layout: OfficeLayout, teamId: string) => layout.studios!.find((s) => s.teamId === teamId)!;
  /** Agent id -> desk id, for everyone seated on the floor. */
  const seats = (layout: OfficeLayout) => new Map(allDesks(layout).filter((d) => d.agentId).map((d) => [d.agentId!, d.id] as const));
  const moved = (a: OfficeLayout, b: OfficeLayout) => [...seats(a)].filter(([id, desk]) => seats(b).get(id) !== desk).map(([id]) => id).sort();

  it("sits at the head desk: the first desk of the bench nearest the name wall", () => {
    const layout = plan("a3");
    const studio = studioOf(layout, "team-1");
    expect(studio.leadId).toBe("a3");
    // The lead first, the earliest arrival in the lead's place, everyone else by arrival.
    expect(studio.members).toEqual(["a3", "a2", "a1", "a4", "a5"]);
    const dept = layout.departments.find((d) => d.id === studio.deptId)!;
    const head = dept.desks[0];
    expect(head.id).toBe("studio-team-1:0:north:0");
    expect(head.agentId).toBe("a3");
    // It is on the bench nearest the name wall, and no desk of that bench stands further west.
    const nearest = Math.min(...dept.desks.map((d) => d.z));
    expect(head.z - nearest).toBeLessThan(1);
    expect(dept.desks.every((d) => d.x >= head.x - 1e-9)).toBe(true);
    expect(leadDesks(layout).map(({ desk, dept: of }) => [desk.id, of.id])).toEqual([["studio-team-1:0:north:0", "studio-team-1"]]);
    // The lead can be walked to like anyone else.
    expect(findPath(buildNavGrid(layout), layout.spawn, standOf(head))).not.toBeNull();
  });

  it("is the same plan for the same teams and lead, however the answer is ordered", () => {
    const other = team(2, [6, 7], { leadId: "a7" });
    const a = buildOfficeLayout(roster, { teams: [team(1, members, { leadId: "a3" }), other] });
    const b = buildOfficeLayout([...roster].reverse(), { teams: [other, team(1, [...members].reverse(), { leadId: "a3" })] });
    expect(b).toEqual(a);
    expect(studioOf(a, "team-2").members).toEqual(["a7", "a6"]);
  });

  it("is never guessed: a lead who is no member, not on the roster or in the lead office leaves the studio without one", () => {
    const plain = plan();
    for (const leadId of ["a7", "ghost", "", null]) {
      const layout = plan(leadId);
      expect(studioOf(layout, "team-1").leadId, String(leadId)).toBeNull();
      expect(layout, String(leadId)).toEqual(plain);
      expect(leadDesks(layout)).toEqual([]);
    }
    // A lead-tier agent sits in the lead office, whatever team names it lead.
    const boss = agent(0, { tier: "lead" });
    const withBoss = (leadId?: string) => buildOfficeLayout([boss, ...roster], { teams: [team(1, [0, ...members], leadId ? { leadId } : {})] });
    expect(studioOf(withBoss("a0"), "team-1").leadId).toBeNull();
    expect(withBoss("a0")).toEqual(withBoss());
    expect(withBoss("a0").lead.desks[0].agentId).toBe("a0");
  });

  it("moves only who has to move: two people when a lead is named, three at most when it changes", () => {
    const none = plan(), third = plan("a3"), fifth = plan("a5"), first = plan("a1");
    // Named: the lead and the earliest arrival change places.
    expect(moved(none, third)).toEqual(["a1", "a3"]);
    // The earliest arrival already sits at the head desk.
    expect(moved(none, first)).toEqual([]);
    expect(studioOf(first, "team-1").leadId).toBe("a1");
    // Changed: the old lead goes back to its own place, the new one to the head, the earliest arrival to the new lead's place.
    expect(moved(third, fifth)).toEqual(["a1", "a3", "a5"]);
    expect(moved(third, first)).toEqual(["a1", "a3"]);
    // Nobody outside the team moves, and the studio keeps its size.
    for (const next of [third, fifth, first]) {
      expect(next.bounds).toEqual(none.bounds);
      expect(next.departments.map((d) => [d.id, d.desks.length])).toEqual(none.departments.map((d) => [d.id, d.desks.length]));
    }
  });

  it("sits with the team it leads, not with an older team it is only a member of", () => {
    const older = team(1, [1, 2, 3]), younger = team(2, [3, 4], { leadId: "a3" });
    const layout = buildOfficeLayout(roster, { teams: [older, younger] });
    expect(studioOf(layout, "team-1").members).toEqual(["a1", "a2"]);
    expect(studioOf(layout, "team-2").members).toEqual(["a3", "a4"]);
    expect(studioOf(layout, "team-2").leadId).toBe("a3");
    // Named lead of two teams: at the head of the older one; the other has no lead on the floor.
    const both = buildOfficeLayout(roster, { teams: [{ ...older, leadId: "a3" }, younger] });
    expect(studioOf(both, "team-1").members).toEqual(["a3", "a2", "a1"]);
    expect(studioOf(both, "team-1").leadId).toBe("a3");
    expect(studioOf(both, "team-2").leadId).toBeNull();
    expect(studioOf(both, "team-2").members).toEqual(["a4"]);
    expect(seatedCount(both)).toBe(roster.length);
  });

  it("keeps its head desk in a studio that is full: the newest member sits in the pool instead", () => {
    const crowd = staff(STUDIO_SEAT_CAP + 3), newest = `a${STUDIO_SEAT_CAP + 3}`;
    const everyone = Array.from({ length: STUDIO_SEAT_CAP + 3 }, (_, i) => i + 1);
    const layout = buildOfficeLayout(crowd, { teams: [team(1, everyone, { leadId: newest })] });
    const studio = studioOf(layout, "team-1");
    expect(studio.members).toHaveLength(STUDIO_SEAT_CAP);
    expect(studio.members[0]).toBe(newest);
    expect(studio.leadId).toBe(newest);
    // Three do not fit: the newest three who are not the lead.
    expect(layout.studios![0].members).toEqual([`a${STUDIO_SEAT_CAP}`, `a${STUDIO_SEAT_CAP + 1}`, `a${STUDIO_SEAT_CAP + 2}`]);
    expect(seatedCount(layout)).toBe(crowd.length);
  });
});

describe("campus: the plan", () => {
  it("is four cells wide at every size and grows southwards by a row of studios", () => {
    const [small, mid, large] = SIZES.map(([, roster, teams]) => buildOfficeLayout(roster, { teams }));
    // Four cells, the boulevard, a walk along each window and the strip at the glass.
    expect(CAMPUS.cellsPerRow * CAMPUS.cellW + CAMPUS.boulevard + 2 * CAMPUS.promenade + 2 * FLOOR_EDGE).toBeCloseTo(55.0, 6);
    for (const layout of [small, mid, large]) expect(size(layout).w).toBeCloseTo(55.0, 6);
    expect(size(small).d).toBeCloseTo(47.0, 6);
    expect(size(mid).d).toBeCloseTo(47.0, 6);
    expect(size(large).d).toBeCloseTo(81.2, 6);
    // More than two and a half times the floor it replaces (24.4 m x 38.2 m for the same small roster).
    expect(size(small).w * size(small).d).toBeGreaterThan(2.5 * 24.4 * 38.2);
    // One row holds four studios; the fifth opens a second row.
    const rows = (layout: OfficeLayout) => new Set(layout.departments.map((d) => d.minZ)).size;
    expect(rows(buildOfficeLayout(staff(12), { teams: teamsOf(3, 3) }))).toBe(1);
    expect(rows(buildOfficeLayout(staff(12), { teams: teamsOf(4, 3) }))).toBe(2);
    expect(rows(large)).toBe(3);
  });

  for (const [name, roster, teams] of SIZES) {
    it(`is furnished, not circulation: rooms, studios and commons take most of the floor (${name})`, () => {
      const layout = buildOfficeLayout(roster, { teams });
      const plan = { minX: layout.bounds.minX + 1.6, maxX: layout.bounds.maxX - 1.6, minZ: layout.bounds.minZ + 1.6, maxZ: layout.bounds.maxZ - 1.6 };
      const places = [...layout.rooms, ...layout.departments, ...layout.zones!.filter((z) => z.kind !== "boulevard" && z.kind !== "plaza")];
      const furnished = places.reduce((sum, r) => sum + area(r), 0);
      expect(furnished / area(plan)).toBeGreaterThan(0.68);
      // Streets are streets: the boulevard and the streets between rows are a few metres wide, the plaza is the one wide one.
      expect(CAMPUS.boulevard).toBeLessThanOrEqual(5);
      expect(CAMPUS.street).toBeLessThan(4);
      // Studios of a row stand shoulder to shoulder, their fronts in one line.
      const rows = new Map<number, typeof layout.departments>();
      for (const dept of layout.departments) rows.set(dept.minZ, [...(rows.get(dept.minZ) ?? []), dept]);
      for (const row of rows.values()) {
        expect(new Set(row.map((d) => d.maxZ)).size).toBe(1);
        const sorted = [...row].sort((a, b) => a.minX - b.minX);
        for (let i = 1; i < sorted.length; i += 1) {
          const gap = sorted[i].minX - sorted[i - 1].maxX;
          expect(gap === 0 || Math.abs(gap - CAMPUS.boulevard) < 1e-9 || Math.abs(gap - CAMPUS.cellW) < 1e-9 || gap > CAMPUS.cellW, `gap ${gap}`).toBe(true);
        }
      }
    });

    it(`keeps studios, rooms, streets and fittings apart (${name})`, () => {
      const layout = buildOfficeLayout(roster, { teams });
      const zones = layout.zones!, streets = zones.filter((z) => z.kind === "boulevard" || z.kind === "plaza");
      const blocks: Rect[] = [...layout.departments, ...layout.rooms];
      for (const a of blocks) for (const b of blocks) if (a !== b) expect(overlaps(a, b)).toBe(false);
      // Nothing is built on the boulevards, and no commons or plot overlaps a studio, a room or another commons.
      for (const block of blocks) for (const street of streets) expect(overlaps(block, street)).toBe(false);
      const commons = zones.filter((z) => z.kind !== "boulevard" && z.kind !== "plaza" && z.kind !== "atrium");
      for (const zone of commons) {
        for (const block of blocks) expect(overlaps(zone, block), zone.id).toBe(false);
        for (const street of streets) expect(overlaps(zone, street), zone.id).toBe(false);
        for (const other of commons) if (other !== zone) expect(overlaps(zone, other), `${zone.id} x ${other.id}`).toBe(false);
      }
      // Fittings never stand in a room or on a desk, and each one is solid.
      const ambience = layout.ambience!;
      expect(new Set(ambience.map((i) => i.id)).size).toBe(ambience.length);
      const kinds: AgentsAmbienceKind[] = ["olive", "tree", "bench", "planter", "screen", "cabinet", "sofa", "hightable", "booth", "steps", "counter", "island"];
      // The free plot's crates are there while a plot is.
      expect(ambience.some((i) => i.kind === "crate")).toBe(layout.zones!.some((z) => z.kind === "plot"));
      for (const kind of kinds) expect(ambience.some((i) => i.kind === kind), kind).toBe(true);
      for (const item of ambience) {
        for (const room of layout.rooms) expect(overlaps(item, room), item.id).toBe(false);
        for (const desk of allDesks(layout)) expect(inside(desk, item), item.id).toBe(false);
        for (const solid of ambienceObstacles(item)) {
          expect(layout.obstacles.some((o) => o.minX === solid.minX && o.maxX === solid.maxX && o.minZ === solid.minZ && o.maxZ === solid.maxZ), item.id).toBe(true);
        }
        // The railing's base is 8 cm wide on a line 0.2 m in from the slab edge.
        expect(item.minX, item.id).toBeGreaterThan(layout.bounds.minX + 0.24);
        expect(item.maxX, item.id).toBeLessThan(layout.bounds.maxX - 0.24);
        expect(item.minZ, item.id).toBeGreaterThan(layout.bounds.minZ + 0.24);
        expect(item.maxZ, item.id).toBeLessThan(layout.bounds.maxZ - 0.24);
      }
      // Planting is a few deliberate groups, not rows: far fewer trees than studios and commons could hold.
      const trees = ambience.filter((i) => i.kind === "olive" || i.kind === "tree").length;
      expect(trees).toBeLessThanOrEqual(12 + 2 * layout.departments.length + 3 * kindsOf(layout, "garden").length);
      expect(ambience.some((i) => i.kind === "tree") && ambience.some((i) => i.kind === "olive")).toBe(true);
    });

    it(`never stands two solid things in the same place (${name})`, () => {
      const layout = buildOfficeLayout([agent(0, { tier: "lead" }), agent(99, { tier: "lead" }), ...roster], { teams });
      const solids: (Rect & { id: string })[] = [
        ...layout.furniture.filter((f) => FURNITURE_SIZE[f.kind].solid).map((f) => ({ id: f.id, ...footprint(f) })),
        ...layout.ambience!.map((i) => ({ ...i })),
        ...allDesks(layout).map((d) => ({ id: `desk ${d.id}`, ...deskRect(d) })),
        ...layout.departments.map((d) => ({ id: `wall ${d.id}`, ...studioWallRect(d) })),
        ...layout.departments.flatMap(benchPlanters).map((p) => ({ id: `planter ${p.key}`, ...p.rect })),
        ...layout.walls.map((w, n) => ({ id: `room wall ${n}`, minX: Math.min(w.x1, w.x2) - 0.06, maxX: Math.max(w.x1, w.x2) + 0.06, minZ: Math.min(w.z1, w.z2) - 0.06, maxZ: Math.max(w.z1, w.z2) + 0.06 })),
      ];
      const clashes: string[] = [];
      for (let i = 0; i < solids.length; i += 1) {
        for (let j = i + 1; j < solids.length; j += 1) {
          if (solids[i].id.startsWith("room wall") && solids[j].id.startsWith("room wall")) continue;
          if (overlaps(solids[i], solids[j])) clashes.push(`${solids[i].id} x ${solids[j].id}`);
        }
      }
      // By design: the team board hangs on the team room's slat wall, so their footprints touch. Nothing else does.
      expect(clashes).toEqual(["team-wall x team-board"]);
      // Nothing solid stands in a doorway: one step inside and one outside every door is free.
      const grid = buildNavGrid(layout);
      for (const room of layout.rooms) {
        for (const door of room.doors) {
          const horizontal = door.side === "north" || door.side === "south";
          const line = door.side === "north" ? room.minZ : door.side === "south" ? room.maxZ : door.side === "west" ? room.minX : room.maxX;
          for (const step of [-0.8, 0, 0.8]) {
            const p = horizontal ? { x: door.at, z: line + step } : { x: line + step, z: door.at };
            expect(isWalkable(grid, p), `${room.kind} ${door.side} door ${step}`).toBe(true);
          }
        }
      }
    });

    it(`puts the spawn point in the atrium, where the boulevards cross (${name})`, () => {
      const layout = buildOfficeLayout(roster, { teams });
      const stop = layout.checkpoints.find((c) => c.id === "spawn")!;
      const zone = (kind: string) => layout.zones!.find((z) => z.kind === kind)!;
      const pad = layout.furniture.find((f) => f.kind === "spawnPad")!, terminal = layout.furniture.find((f) => f.kind === "spawnTerminal")!;
      expect([pad.x, pad.z, terminal.x, terminal.z]).toEqual([stop.x, stop.z, stop.x, stop.z]);
      expect(stop.x).toBe(0);
      expect(stop.z).toBeCloseTo((zone("plaza").minZ + zone("plaza").maxZ) / 2, 9);
      expect(inside(stop, zone("atrium")) && inside(stop, zone("boulevard"))).toBe(true);
      // The plaza is the gap between two blocks nearest the floor's middle; the boulevard runs from the lobby to the team room's door.
      expect(Math.abs(stop.z)).toBeLessThan(size(layout).d / 4);
      const teamRoom = layout.rooms.find((r) => r.kind === "team")!, lobby = layout.rooms.find((r) => r.kind === "reception")!;
      expect(teamRoom.doors[0].at).toBe(0);
      expect(zone("boulevard").minZ).toBe(teamRoom.maxZ);
      expect(zone("boulevard").maxZ).toBe(lobby.minZ);
      expect((lobby.minX + lobby.maxX) / 2).toBe(0);
      // The heart of the campus: step seating either side of the pad, facing it, with seats; the pad itself stays clear.
      const padBox = footprint(pad);
      for (const item of layout.ambience!) expect(overlaps(item, padBox), item.id).toBe(false);
      const [west, east] = ["west", "east"].map((side) => layout.ambience!.find((i) => i.id === `atrium-steps-${side}`)!);
      expect([west.kind, west.facing, east.kind, east.facing]).toEqual(["steps", "east", "steps", "west"]);
      expect(inside({ x: (west.minX + west.maxX) / 2, z: (west.minZ + west.maxZ) / 2 }, zone("atrium"))).toBe(true);
      const seats = layout.spots.filter((s) => s.id.startsWith("atrium-steps-"));
      expect(seats.length).toBeGreaterThanOrEqual(8);
      for (const seat of seats) {
        expect([seat.kind, seat.pose]).toEqual(["couch", "sit"]);
        // Looking at the spawn point.
        expect(Math.sign(Math.sin(seat.facing))).toBe(seat.x < 0 ? 1 : -1);
      }
      expect(layout.arrival).toEqual(stop.approach);
      expect(isWalkable(buildNavGrid(layout), layout.arrival)).toBe(true);
    });
  }

  it("shows the next team's place as a free plot and makes the other empty cells garden courts", () => {
    const empty = buildOfficeLayout(staff(5));
    expect(kindsOf(empty, "plot", "garden")).toEqual(["plot", "garden", "garden"]);
    // The first team takes exactly the plot's cell; the plot moves on.
    const plot = empty.zones!.find((z) => z.kind === "plot")!;
    const one = buildOfficeLayout(staff(5), { teams: [team(1, [1, 2])] });
    const studio = one.departments.find((d) => d.teamId === "team-1")!;
    expect(overlaps(plot, studio) && plot.minX > studio.minX && plot.maxX < studio.maxX && plot.minZ > studio.minZ).toBe(true);
    expect(kindsOf(one, "plot", "garden")).toEqual(["plot", "garden"]);
    expect(kindsOf(buildOfficeLayout(staff(12), { teams: teamsOf(3, 3) }), "plot", "garden")).toEqual([]);
  });

  it("furnishes the free plot: the stand where a team is started faces the street, crates and a plant wait behind it", () => {
    const layout = buildOfficeLayout(staff(5));
    const grid = buildNavGrid(layout);
    const plot = layout.zones!.find((z) => z.kind === "plot")!;
    const stands = layout.furniture.filter((f) => f.kind === "teamStand");
    expect(stands.map((f) => [f.id, f.rotationY])).toEqual([["team-stand", 0]]);
    const stand = stands[0];
    expect(inside(stand, plot)).toBe(true);
    expect(isWalkable(grid, stand)).toBe(false);
    // The station layer stands the person 0.95 m in front of its face: on the plot, on open floor, within reach.
    const front = { x: stand.x, z: stand.z + FURNITURE_SIZE.teamStand.d / 2 + 0.95 };
    expect(inside(front, plot)).toBe(true);
    expect(isWalkable(grid, front)).toBe(true);
    expect(findPath(grid, layout.spawn, front)).not.toBeNull();
    const crates = layout.ambience!.filter((i) => i.kind === "crate");
    expect(crates.map((i) => i.id)).toEqual(["plot-crates"]);
    expect(overlaps(crates[0], plot)).toBe(true);
    expect(isWalkable(grid, { x: (crates[0].minX + crates[0].maxX) / 2, z: (crates[0].minZ + crates[0].maxZ) / 2 })).toBe(false);
    expect(inside(layout.furniture.find((f) => f.id === "plot-plant")!, plot)).toBe(true);
    // A full row has no plot: no stand, no crates.
    const full = buildOfficeLayout(staff(12), { teams: teamsOf(3, 3) });
    expect(full.furniture.some((f) => f.kind === "teamStand" || f.id === "plot-plant")).toBe(false);
    expect(full.ambience!.some((i) => i.kind === "crate")).toBe(false);
  });

  it("carries the lobby's name on an arch at the back of the reception desk, off the atrium", () => {
    for (const [, roster, teams] of SIZES) {
      const layout = buildOfficeLayout(roster, { teams });
      const reception = layout.rooms.find((r) => r.kind === "reception")!;
      const desk = footprint(layout.furniture.find((f) => f.kind === "receptionDesk")!);
      const posts = archPosts(reception);
      expect(posts).toHaveLength(2);
      for (const post of posts) {
        expect(inside(post, reception)).toBe(true);
        // Behind the desk's back, within its width: the board reads as the desk's own sign.
        expect(post.x).toBeGreaterThan(desk.minX);
        expect(post.x).toBeLessThan(desk.maxX);
        expect(desk.minZ - post.z).toBeGreaterThan(ARCH.post / 2);
        expect(desk.minZ - post.z).toBeLessThan(0.3);
        for (const zone of layout.zones!.filter((z) => z.kind === "atrium" || z.kind === "plaza")) expect(inside(post, zone)).toBe(false);
        expect(isWalkable(buildNavGrid(layout), post)).toBe(false);
      }
    }
  });

  for (const [name, roster, teams] of SIZES) {
    it(`keeps a real walk along both windows, between the benches at the glass and the outer studios (${name})`, () => {
      const layout = buildOfficeLayout(roster, { teams });
      const grid = buildNavGrid(layout);
      const band = layout.ambience!.filter((i) => /^(bench|planter)-(west|east)-\d+$/.test(i.id));
      expect(band.length).toBeGreaterThanOrEqual(4);
      for (const piece of band) {
        const west = piece.id.includes("-west-");
        // The nearest solid thing further into the floor, beside this piece.
        const beside = layout.obstacles.filter((o) => o.minZ < piece.maxZ && o.maxZ > piece.minZ && (west ? o.minX >= piece.maxX : o.maxX <= piece.minX));
        const clear = Math.min(...beside.map((o) => (west ? o.minX - piece.maxX : piece.minX - o.maxX)));
        expect(clear, piece.id).toBeGreaterThanOrEqual(1.2);
      }
      // And it is one walk from the first row of studios to the last, on both sides.
      const rows = [...layout.departments, ...layout.zones!.filter((z) => z.kind === "plot" || z.kind === "garden")];
      const z0 = Math.min(...rows.map((r) => r.minZ)), z1 = Math.max(...rows.map((r) => r.maxZ));
      for (const x of [layout.bounds.minX + FLOOR_EDGE + CAMPUS.promenade / 2, layout.bounds.maxX - FLOOR_EDGE - CAMPUS.promenade / 2]) {
        for (let z = z0; z <= z1; z += 0.4) expect(isWalkable(grid, { x, z }), `walk ${x} at ${z}`).toBe(true);
      }
    });
  }

  for (const [name, roster, teams] of SIZES) {
    it(`has its commons at every size, each with places to use it (${name})`, () => {
      const layout = buildOfficeLayout(roster, { teams });
      expect(kindsOf(layout, "booths", "library", "cafe")).toEqual(["booths", "library", "cafe"]);
      const grid = buildNavGrid(layout);
      const spotsIn = (kind: string) => {
        const zone = layout.zones!.find((z) => z.kind === kind)!;
        return layout.spots.filter((s) => s.room === "floor" && inside(s, zone));
      };
      // Somewhere to sit and somewhere to stand in the café and the library; a booth each for three people.
      for (const kind of ["cafe", "library", "booths"]) {
        const spots = spotsIn(kind);
        expect(spots.length, kind).toBeGreaterThanOrEqual(5);
        expect(spots.some((s) => s.pose === "sit") && spots.some((s) => s.pose === "stand"), kind).toBe(true);
      }
      const booths = layout.spots.filter((s) => /^booth-\d$/.test(s.id));
      expect(booths).toHaveLength(3);
      // A person walks into a booth and stands inside it.
      for (const spot of booths) {
        expect(isWalkable(grid, spot), spot.id).toBe(true);
        const box = layout.ambience!.find((i) => i.id === spot.id)!;
        expect(inside(spot, box)).toBe(true);
        expect(isWalkable(grid, { x: spot.x, z: box.minZ + 0.1 })).toBe(false);
      }
      // A garden court has a bench to sit on.
      for (const zone of layout.zones!.filter((z) => z.kind === "garden")) {
        expect(layout.spots.filter((s) => inside(s, zone) && s.pose === "sit").length, zone.id).toBeGreaterThanOrEqual(2);
      }
      // Every spot outside the rooms is a place a figure can be: on the open floor, or on a seat within a step of it.
      for (const spot of layout.spots.filter((s) => s.room === "floor")) {
        expect(findPath(grid, layout.spawn, spot), spot.id).not.toBeNull();
      }
    });
  }
});

describe("campus: walking it", () => {
  const cases: [string, OfficeAgentInput[], OfficeTeamInput[]][] = [
    ["no team", staff(5), []],
    ["one team of two", staff(6), [team(1, [1, 2])]],
    ["three teams, one of twelve", staff(20), [team(1, [1, 2]), team(2, [3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14]), team(3, [15, 16, 17])]],
    ["eight teams", staff(40), teamsOf(8, 4)],
    ["an agent in two teams and a team of unknown ids", staff(8), [team(1, [1, 2, 3]), team(2, [3, 4]), team(3, [90, 91])]],
  ];
  for (const [name, roster, teams] of cases) {
    it(`reaches every seat, spot, station and studio board from the elevator (${name})`, () => {
      const layout = buildOfficeLayout([agent(0, { tier: "lead" }), ...roster], { teams });
      const grid = buildNavGrid(layout);
      const elevator = layout.checkpoints.find((c) => c.id === "elevator")!;
      const targets: { name: string; p: Point }[] = [
        ...allDesks(layout).flatMap((d) => [{ name: `seat ${d.id}`, p: seatOf(d) }, { name: `stand ${d.id}`, p: standOf(d) }]),
        ...layout.spots.map((s) => ({ name: `spot ${s.id}`, p: s })),
        ...layout.checkpoints.map((c) => ({ name: `station ${c.id}`, p: c.approach ?? c })),
        // In front of every studio board, where the person reads it.
        ...layout.studios!.map((s) => ({ name: `board ${s.deptId}`, p: { x: s.board!.x, z: s.board!.z + 1.0 } })),
        ...layout.zones!.map((z) => ({ name: `zone ${z.id}`, p: { x: (z.minX + z.maxX) / 2 + 0.9, z: (z.minZ + z.maxZ) / 2 + 2.2 } })),
      ];
      for (const start of [layout.spawn, elevator]) {
        expect(isWalkable(grid, start)).toBe(true);
        for (const target of targets) {
          if (!findPath(grid, start, target.p)) throw new Error(`${target.name} at ${target.p.x.toFixed(2)},${target.p.z.toFixed(2)} is unreachable`);
        }
      }
    });

    it(`sends every route from the lobby to a studio or a room across the plaza (${name})`, () => {
      const layout = buildOfficeLayout(roster, { teams });
      const grid = buildNavGrid(layout);
      const plaza = layout.zones!.find((z) => z.kind === "plaza")!;
      const elevator = layout.checkpoints.find((c) => c.id === "elevator")!;
      const north = [
        ...layout.departments.filter((d) => d.maxZ <= plaza.minZ).map((d) => ({ x: (d.minX + d.maxX) / 2, z: d.minZ + 2.0 })),
        ...layout.checkpoints.filter((c) => ["team", "lead", "wardrobe"].includes(c.id)),
      ];
      expect(north.length).toBeGreaterThan(3);
      // The main boulevard runs from window to window: whoever goes north passes over it, in the middle or along a window.
      const band = { ...plaza, minX: layout.floor.minX, maxX: layout.floor.maxX };
      for (const target of north) {
        const path = [elevator, ...findPath(grid, elevator, target)!];
        expect(path.some((p, i) => i > 0 && (inside(p, band) || (path[i - 1].z > band.maxZ && p.z < band.minZ))), `${target.x},${target.z}`).toBe(true);
        expect(path.every((p) => inside(p, layout.floor))).toBe(true);
      }
    });
  }

  it("keeps the boulevard, the plaza and every street open from end to end", () => {
    const layout = buildOfficeLayout(staff(40), { teams: teamsOf(8, 4) });
    const grid = buildNavGrid(layout);
    const boulevard = layout.zones!.find((z) => z.kind === "boulevard")!, plaza = layout.zones!.find((z) => z.kind === "plaza")!;
    for (let z = boulevard.minZ + 0.3; z < boulevard.maxZ - 0.3; z += 0.4) {
      // The boulevard's middle is free all the way, except where the spawn terminal stands on it.
      if (Math.abs(z - (plaza.minZ + plaza.maxZ) / 2) < 1) continue;
      expect(isWalkable(grid, { x: 0, z }), `axis at ${z}`).toBe(true);
    }
    // Past the step seating on both sides of the plaza, and along the street in front of every row of studios.
    const streets = [plaza.minZ + 1.5, plaza.maxZ - 1.5, ...new Set(layout.departments.map((d) => d.maxZ + 1.2)), boulevard.minZ + CAMPUS.street / 2];
    for (const z of streets) {
      for (let x = layout.floor.minX + 1.5; x < layout.floor.maxX - 1.5; x += 0.4) expect(isWalkable(grid, { x, z }), `street ${z} at ${x}`).toBe(true);
    }
  });
});
