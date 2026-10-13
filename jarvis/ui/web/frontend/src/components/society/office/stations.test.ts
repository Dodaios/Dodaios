import { describe, expect, it } from "vitest";
import { buildOfficeLayout, FURNITURE_SIZE, type OfficeAgentInput, type OfficeLayout, type Studio } from "./officeLayout";
import { buildNavGrid, isWalkable, nearestWalkable } from "./officeNav";
import {
  isReception, isTeamStand, loungeCentre, nearestInteractable, selectionKey, spawnScreenDive, stationOf, stationsFor, TEAM_STAND_ID, TEAM_STAND_STATION,
} from "./stations";

function roster(count: number): OfficeAgentInput[] {
  return Array.from({ length: count }, (_, i) => ({
    agentId: `a${i}`, name: `Agent ${i}`, tier: i === 0 ? "lead" as const : "specialist" as const,
    providerLabel: i % 2 ? "Codex" : "Gemini", state: "idle" as const, createdMs: i,
  }));
}

const REACH = { agent: 1.8, arcade: 0.9 };
const NOBODY: [string, { x: number; z: number }][] = [];
const NO_PETS = new Set<string>();

describe("stations", () => {
  const agentsFloor = buildOfficeLayout(roster(8));
  const codingFloor = buildOfficeLayout(roster(4), { variant: "coding" });

  it("turns every checkpoint of a floor into one station", () => {
    for (const layout of [agentsFloor, codingFloor]) {
      const stations = stationsFor(layout);
      const checkpoints = stations.filter((s) => s.selection.kind === "checkpoint");
      expect(checkpoints.map((s) => s.selection.id)).toEqual(layout.checkpoints.map((cp) => cp.id));
      expect(new Set(stations.map((s) => s.key)).size).toBe(stations.length);
      // The same plan gives the same list back, so a frame loop can ask every frame.
      expect(stationsFor(layout)).toBe(stations);
    }
  });

  it("binds each station to an object of the room, never to a marker of its own", () => {
    const props = new Map(agentsFloor.furniture.map((f) => [`prop:${f.id}`, f]));
    const kindOf = (id: string) => {
      const station = stationsFor(agentsFloor).find((s) => s.selection.id === id);
      expect(station, id).toBeTruthy();
      return station!.objects.map((name) => props.get(name)?.kind);
    };
    expect(kindOf("spawn")).toEqual(["spawnTerminal"]);
    expect(kindOf("team")).toEqual(["teamBoard"]);
    expect(kindOf("wardrobe")).toEqual(["dressingMirror"]);
    expect(kindOf("break")).toEqual(["coffeeBar"]);
    expect(kindOf("elevator")).toEqual(["elevator"]);
    const codingProps = new Map(codingFloor.furniture.map((f) => [`prop:${f.id}`, f.kind]));
    const codingKind = (id: string) => stationsFor(codingFloor).find((s) => s.selection.id === id)!.objects.map((name) => codingProps.get(name));
    expect(codingKind("launch")).toEqual(["spawnTerminal"]);
    expect(codingKind("mission")).toEqual(["commandWall"]);
  });

  it("gives the reception desk the directory, whatever the plan calls its checkpoint", () => {
    const desks = stationsFor(agentsFloor).filter((s) => isReception(s.selection));
    expect(desks.length).toBeGreaterThan(0);
    for (const desk of desks) {
      expect(desk.id).toBe("manage");
      expect(desk.icon).toBe("reception");
    }
    expect(desks.some((desk) => desk.objects.includes("prop:reception-desk"))).toBe(true);
    expect(isReception({ kind: "checkpoint", id: "team" })).toBe(false);
    expect(isReception({ kind: "agent", id: "manage" })).toBe(false);
  });

  it("sizes a click target to the object's own footprint", () => {
    const terminal = agentsFloor.furniture.find((f) => f.kind === "spawnTerminal")!;
    const spawn = stationsFor(agentsFloor).find((s) => s.selection.id === "spawn")!;
    expect(spawn.hits).toEqual([{
      x: terminal.x, z: terminal.z, y: FURNITURE_SIZE.spawnTerminal.h / 2, rotationY: terminal.rotationY,
      w: FURNITURE_SIZE.spawnTerminal.w, h: FURNITURE_SIZE.spawnTerminal.h, d: FURNITURE_SIZE.spawnTerminal.d,
    }]);
  });

  it("lights the lead's desks and puts their click target on the visitor side, clear of chair and monitors", () => {
    const lead = stationsFor(agentsFloor).find((s) => s.selection.id === "lead")!;
    const desks = agentsFloor.lead.desks;
    expect(desks.length).toBeGreaterThan(0);
    expect(lead.objects).toEqual(desks.map((d) => `desk:${d.id}`));
    lead.hits.forEach((hit, i) => {
      const desk = desks[i]!;
      const seatSide = desk.facing === "north" ? 1 : -1;
      // On the far side of the desk from the chair, and no taller than the desk top.
      expect(Math.sign(hit.z - desk.z)).toBe(-seatSide);
      expect(hit.y + hit.h / 2).toBeLessThan(0.76);
    });
  });

  it("stands the person somewhere they can actually walk to", () => {
    for (const layout of [agentsFloor, codingFloor]) {
      const grid = buildNavGrid(layout);
      for (const station of stationsFor(layout)) {
        const spot = isWalkable(grid, station.approach) ? station.approach : nearestWalkable(grid, station.approach);
        expect(spot, station.key).toBeTruthy();
        expect(Math.hypot(spot!.x - station.approach.x, spot!.z - station.approach.z), station.key).toBeLessThan(1.5);
      }
    }
  });

  it("adds a station for every team studio's board, selected by the board's id", () => {
    const board = { id: "studio-board:dept-0", x: 4, z: -6, facing: 0 };
    const studios: Studio[] = [
      { deptId: "dept-0", teamId: "g1", name: "Launch crew", members: ["a1", "a2"], leadId: null, board, huddleSpotIds: [], centre: { x: 4, z: -3 } },
      { deptId: "dept-1", teamId: null, name: "", members: ["a3"], leadId: null, board: null, huddleSpotIds: [], centre: { x: 9, z: -3 } },
    ];
    const layout: OfficeLayout = { ...agentsFloor, studios };
    const boards = stationsFor(layout).filter((s) => s.selection.kind === "team" && s.id !== TEAM_STAND_STATION);
    expect(boards).toHaveLength(1);
    const station = boards[0]!;
    expect(station.selection).toEqual({ kind: "team", id: board.id });
    expect(station.name).toBe("Launch crew");
    expect(station.objects).toEqual([`prop:${board.id}`]);
    // The person stands in front of the face, where the board looks.
    expect(station.z).toBeGreaterThan(board.z);
    expect(stationOf(layout, { kind: "team", id: board.id })).toBe(station);
    expect(stationOf(layout, { kind: "team", id: "studio-board:gone" })).toBeNull();
    expect(stationOf(layout, { kind: "agent", id: "a1" })).toBeNull();
    // Standing there, E reaches the board.
    expect(nearestInteractable(layout, station, NOBODY, NO_PETS, REACH)).toEqual(station.selection);
  });
});

describe("the free plot's stand", () => {
  // The plan's own stand is taken out, so the stand-in below is the only one.
  const plan = buildOfficeLayout(roster(4));
  const base: OfficeLayout = { ...plan, furniture: plan.furniture.filter((item) => !item.id.startsWith(TEAM_STAND_ID)) };
  // Any piece will do for the plan: the stand is found by its id, not by its kind.
  const stand = { id: `${TEAM_STAND_ID}`, kind: "lobbyLamp" as const, x: 6, z: 4, rotationY: Math.PI / 2, room: "floor" as const };
  const layout: OfficeLayout = { ...base, furniture: [...base.furniture, stand] };

  it("is a station that selects the stand like a board, lights it and takes clicks on it", () => {
    const station = stationsFor(layout).find((s) => s.id === TEAM_STAND_STATION)!;
    expect(station.selection).toEqual({ kind: "team", id: stand.id });
    expect(station.objects).toEqual([`prop:${stand.id}`]);
    expect(station.hits).toEqual([{
      x: stand.x, z: stand.z, y: FURNITURE_SIZE.lobbyLamp.h / 2, rotationY: stand.rotationY,
      w: FURNITURE_SIZE.lobbyLamp.w, h: FURNITURE_SIZE.lobbyLamp.h, d: FURNITURE_SIZE.lobbyLamp.d,
    }]);
    // The person stands in front of its face (rotated a quarter turn: to the east of it).
    expect(station.approach.x).toBeGreaterThan(stand.x + 0.9);
    expect(station.approach.z).toBeCloseTo(stand.z);
    expect(nearestInteractable(layout, station.approach, NOBODY, NO_PETS, REACH)).toEqual(station.selection);
  });

  it("is told apart from a studio's board, and from a plan without one", () => {
    expect(isTeamStand(layout, { kind: "team", id: stand.id })).toBe(true);
    expect(isTeamStand(layout, { kind: "team", id: "studio-board:dept-0" })).toBe(false);
    expect(isTeamStand(layout, { kind: "checkpoint", id: "team" })).toBe(false);
    expect(isTeamStand(base, { kind: "team", id: stand.id })).toBe(false);
    expect(stationsFor(base).some((s) => s.id === TEAM_STAND_STATION)).toBe(false);
  });
});

describe("nearest interactable", () => {
  const layout = buildOfficeLayout(roster(6));
  const spawn = stationsFor(layout).find((s) => s.selection.id === "spawn")!;

  it("is the station whose reach the person stands in", () => {
    expect(nearestInteractable(layout, spawn.approach, NOBODY, NO_PETS, REACH)).toEqual(spawn.selection);
  });

  it("is nothing in the open, outside every reach", () => {
    const far = { x: spawn.x + spawn.radius + 0.6, z: spawn.z };
    const clear = stationsFor(layout).every((s) => Math.hypot(s.x - far.x, s.z - far.z) > s.radius);
    expect(clear).toBe(true);
    expect(nearestInteractable(layout, far, NOBODY, NO_PETS, REACH)).toBeNull();
  });

  it("prefers whoever is closer: an agent at arm's length beats the station behind them", () => {
    const at = spawn.approach;
    const beside: [string, { x: number; z: number }][] = [["a2", { x: at.x + 0.3, z: at.z }]];
    expect(Math.hypot(spawn.x - at.x, spawn.z - at.z)).toBeGreaterThan(0.3);
    expect(nearestInteractable(layout, at, beside, NO_PETS, REACH)).toEqual({ kind: "agent", id: "a2" });
    // The person's own pet walks beside them and is never the target.
    expect(nearestInteractable(layout, at, beside, new Set(["a2"]), REACH)).toEqual(spawn.selection);
  });

  it("offers a game cabinet only from in front of its screen", () => {
    const cabinet = layout.furniture.find((f) => f.kind === "arcade")!;
    const front = { x: cabinet.x + Math.sin(cabinet.rotationY) * 0.85, z: cabinet.z + Math.cos(cabinet.rotationY) * 0.85 };
    expect(nearestInteractable(layout, front, NOBODY, NO_PETS, REACH)).toEqual({ kind: "arcade", id: cabinet.id });
  });
});

describe("station helpers", () => {
  const layout = buildOfficeLayout(roster(3));

  it("keys a selection by kind and id", () => {
    expect(selectionKey({ kind: "checkpoint", id: "team" })).toBe("checkpoint:team");
    expect(selectionKey({ kind: "team", id: "studio-board:d" })).toBe("team:studio-board:d");
  });

  it("dives into the terminal face on the viewer's side", () => {
    const terminal = layout.furniture.find((f) => f.kind === "spawnTerminal")!;
    const south = spawnScreenDive(layout, { x: terminal.x, z: terminal.z + 3 })!;
    const north = spawnScreenDive(layout, { x: terminal.x, z: terminal.z - 3 })!;
    expect(south.target[2]).toBeGreaterThan(terminal.z);
    expect(north.target[2]).toBeLessThan(terminal.z);
    expect(Math.abs(north.facing - south.facing)).toBeCloseTo(Math.PI);
    expect(south.target[1]).toBeLessThan(FURNITURE_SIZE.spawnTerminal.h);
    expect(spawnScreenDive({ ...layout, furniture: [] }, { x: 0, z: 0 })).toBeNull();
  });

  it("gathers a coffee break among the break room's couches", () => {
    const centre = loungeCentre(layout);
    const room = layout.rooms.find((r) => r.kind === "break")!;
    expect(centre.x).toBeGreaterThan(room.minX);
    expect(centre.x).toBeLessThan(room.maxX);
    expect(centre.z).toBeGreaterThan(room.minZ);
    expect(centre.z).toBeLessThan(room.maxZ);
    expect(loungeCentre({ ...layout, spots: [] })).toEqual(layout.spawn);
  });
});
