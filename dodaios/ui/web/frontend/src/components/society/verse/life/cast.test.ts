import { describe, expect, it } from "vitest";
import { syntheticDeck } from "../testing/syntheticDeck";
import type { CharacterContract } from "../actors/characters";
import { buildCast, COMMANDER_ID, COMPANION_ID, routesOf, type CommanderState } from "./cast";
import type { CrewMember } from "./crew";
import { placeOnDeck } from "./planner";

const deck = syntheticDeck();
const tier = { M_Uniform: "#333", M_Trim: "#222", M_Cap: "#333", tile: "#999", cap: false };
const contract = (models: CharacterContract["models"]): CharacterContract => ({
  version: 1, seatHeight: 0.46, skeletons: {}, tiers: { deck: tier, line: tier, command: tier, flag: tier }, models,
});
const officerModel = { id: "SK_Officer_M", url: "o.glb", kind: "officer" as const, materials: [], height: 1.78 };
const companion = { id: "SK_Drone_Companion", url: "c.glb", kind: "companion" as const, materials: [], height: 1.05 };
const utility = { id: "SK_Drone_Utility", url: "u.glb", kind: "drone" as const, materials: [], height: 0.25, driveSpeed: 1.2 };
const look = { tier: "line" as const, accent: null, plate: "010|000" };
const commander: CommanderState = { look, orders: { target: { deck: "bridge", x: -20, z: 0 }, order: 0, fromLift: false } };

function crew(...members: CrewMember[]) {
  return new Map(members.map((m) => [m.id, m]));
}

describe("routes", () => {
  it("keeps waypoint groups of two or more, in order", () => {
    const routes = routesOf(deck);
    expect([...routes.keys()]).toEqual(["patrol_a"]);
    expect(routes.get("patrol_a")!.map((s) => s.order)).toEqual([0, 1, 2, 3]);
  });
});

describe("the cast", () => {
  const a: CrewMember = { id: "a", name: "A", role: "officer", status: "working", createdMs: 1, lead: false };
  const b: CrewMember = { id: "b", name: "B", role: "officer", status: "waiting", createdMs: 2, lead: false };
  const members = crew(a, b);
  const placements = placeOnDeck({ deck, crew: [a, b], rounds: new Map(), nowMs: 0, previous: new Map() }).placements;

  it("puts placed crew at their sockets, the commander and the companion aboard", () => {
    const cast = buildCast({
      deck, contract: contract([officerModel, companion]), crew: members, placements, looks: new Map(), aboard: new Set(["a"]),
      arriving: new Set(), commander,
    });
    const byId = new Map(cast.map((m) => [m.id, m]));
    expect(byId.get("a")).toMatchObject({ body: "officer", entry: "placed", goal: { kind: "socket", activity: "sit_type" } });
    // Not aboard when the deck opened: comes out of the lift.
    expect(byId.get("b")).toMatchObject({ entry: "lift", goal: { kind: "socket", activity: "stand_wait", faceCommander: true } });
    expect(byId.get(COMMANDER_ID)).toMatchObject({ goal: { kind: "point", x: -20, z: 0 } });
    expect(byId.get(COMPANION_ID)).toMatchObject({ body: "companion", goal: { kind: "follow", leaderId: COMMANDER_ID } });
  });

  it("changes a goal key whenever the goal changes, and only then", () => {
    const base = { deck, contract: contract([officerModel]), crew: members, placements, looks: new Map(), aboard: new Set<string>(), arriving: new Set<string>() };
    const one = buildCast({ ...base, commander });
    const same = buildCast({ ...base, commander });
    const moved = buildCast({ ...base, commander: { look, orders: { target: { deck: "bridge", x: 3, z: 4 }, order: 1, fromLift: false } } });
    const key = (c: typeof one, id: string) => c.find((m) => m.id === id)?.goalKey;
    expect(key(one, COMMANDER_ID)).toBe(key(same, COMMANDER_ID));
    expect(key(moved, COMMANDER_ID)).not.toBe(key(one, COMMANDER_ID));
    expect(key(moved, "a")).toBe(key(one, "a"));
  });

  it("sends the ship's company on the deck's routes only when a body exists for them", () => {
    const base = { deck, crew: members, placements, looks: new Map(), aboard: new Set<string>(), arriving: new Set<string>(), commander };
    expect(buildCast({ ...base, contract: contract([officerModel]) }).some((m) => m.id.startsWith("ambient:"))).toBe(false);
    const troopers = buildCast({ ...base, contract: contract([officerModel, { ...officerModel, id: "SK_Trooper", kind: "trooper" }]) });
    expect(troopers.find((m) => m.id === "ambient:patrol_a")).toMatchObject({ body: "trooper", goal: { kind: "route" } });
    // A patrol route is the troopers'; utility drones take service, cargo, pad and corridor rounds.
    expect(buildCast({ ...base, contract: contract([officerModel, utility]) }).some((m) => m.id.startsWith("ambient:"))).toBe(false);
    const serviced = { ...deck, sockets: deck.sockets.map((s) => (s.group === "patrol_a" ? { ...s, group: "service_a" } : s)) };
    expect(buildCast({ ...base, deck: serviced, contract: contract([officerModel, utility]) }).find((m) => m.id === "ambient:service_a"))
      .toMatchObject({ body: "drone", model: "SK_Drone_Utility" });
  });

  it("walks a new officer from the shuttle to the lift on the hangar", () => {
    const hangar = { ...deck, id: "hangar" as const };
    const fresh: CrewMember = { id: "new", name: "N", role: "officer", status: "idle", createdMs: 9, lead: false };
    const cast = buildCast({
      deck: hangar, contract: contract([officerModel]), crew: crew(fresh), placements: new Map(), looks: new Map(),
      aboard: new Set(), arriving: new Set(["new"]), commander,
    });
    expect(cast.find((m) => m.id === "new")).toMatchObject({ entry: "spawn", goal: { kind: "leave" } });
  });
});
