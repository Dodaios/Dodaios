import { describe, expect, it } from "vitest";
import { syntheticDeck } from "../testing/syntheticDeck";
import { byServiceOrder, technicianOf, type CrewMember, type DutyStatus } from "./crew";
import { homeSeats, idleVenueOf, intentOf, placeOnDeck, socketKey, IDLE_SLOT_MS, type RoundPart } from "./planner";

const bridge = syntheticDeck();
const ops = { ...syntheticDeck(), id: "ops" as const };

function officer(id: string, status: DutyStatus, createdMs = 0, lead = false): CrewMember {
  return { id, name: id, role: "officer", status, createdMs, lead };
}

describe("intent from duty status", () => {
  it("puts working officers at their console, typing", () => {
    expect(intentOf(officer("a", "working"), undefined, 0)).toMatchObject({ deck: "bridge", venue: "console", activity: "sit_type" });
  });

  it("stands a waiting officer at its console, turned to the commander", () => {
    expect(intentOf(officer("a", "waiting"), undefined, 0)).toMatchObject({ venue: "console", activity: "stand_wait", faceCommander: true });
  });

  it("sends a paused officer to its bunk and an error to its console", () => {
    expect(intentOf(officer("a", "paused"), undefined, 0)).toMatchObject({ deck: "ops", venue: "bunk", activity: "sleep" });
    expect(intentOf(officer("a", "error"), undefined, 0)).toMatchObject({ venue: "console", activity: "stand_alert" });
  });

  it("gathers a team round at the briefing table: the speaker talks, the free listen", () => {
    expect(intentOf(officer("a", "working"), "speaker", 0)).toMatchObject({ venue: "briefing", activity: "talk" });
    expect(intentOf(officer("b", "idle"), "listener", 0)).toMatchObject({ venue: "briefing", activity: "listen" });
    // A busy member keeps working; a waiting speaker still waits for the person.
    expect(intentOf(officer("c", "working"), "listener", 0)).toMatchObject({ venue: "console" });
    expect(intentOf(officer("d", "waiting"), "speaker", 0)).toMatchObject({ venue: "console", activity: "stand_wait" });
  });

  it("gives idle officers a seeded off-duty routine that changes over time", () => {
    const seen = new Set<string>();
    for (let k = 0; k < 40; k++) seen.add(idleVenueOf("officer-7", k * IDLE_SLOT_MS).venue);
    expect(seen.size).toBeGreaterThan(1);
    // Deterministic.
    expect(idleVenueOf("x", 123456)).toEqual(idleVenueOf("x", 123456));
  });

  it("calls the off-duty crew to the mess, and only them", () => {
    expect(intentOf(officer("a", "idle"), undefined, 0, true)).toMatchObject({ deck: "ops", venue: "mess" });
    expect(intentOf(officer("b", "working"), undefined, 0, true)).toMatchObject({ venue: "console" });
  });

  it("reads panes as technicians at engineering terminals", () => {
    const pane = (dot: "working" | "waiting" | "error" | "idle") => technicianOf({ agent: { agentId: "pane:w:1", name: "T1", createdMs: 0 } as never, dot, stateKey: "working" });
    expect(pane("waiting").status).toBe("waiting");
    expect(intentOf(pane("working"), undefined, 0)).toMatchObject({ deck: "engineering", venue: "terminal", activity: "sit_type" });
    expect(intentOf(pane("error"), undefined, 0)).toMatchObject({ venue: "terminal", activity: "stand_alert" });
    expect(intentOf(pane("idle"), undefined, 0)).toMatchObject({ deck: "engineering", venue: "workshop" });
  });
});

describe("seat reservations", () => {
  const crew = [officer("c", "working", 30), officer("a", "working", 10), officer("lead", "idle", 50, true), officer("b", "paused", 20)];

  it("hands consoles to the whole roster in service order, those on duty first", () => {
    const homes = homeSeats(bridge, crew, "officer", new Map());
    expect([...crew].sort(byServiceOrder).map((m) => m.id)).toEqual(["lead", "a", "b", "c"]);
    expect(homes.get("a")).toBe("pit_p_0");
    expect(homes.get("c")).toBe("pit_p_1");
    expect(homes.get("lead")).toBe("pit_p_2");
    expect(homes.get("b")).toBe("pit_p_3");
  });

  it("gives a console to a working member before an off-duty one when there are too few", () => {
    const idle = Array.from({ length: 6 }, (_, i) => officer(`idle${i}`, "idle", i));
    const first = homeSeats(bridge, idle, "officer", new Map());
    expect(first.size).toBe(6);
    const busy = officer("busy", "working", 99);
    const again = homeSeats(bridge, [...idle, busy], "officer", first);
    expect(again.has("busy")).toBe(true);
    expect(again.size).toBe(6);
    // Everyone else who kept a console kept the same one.
    for (const [id, seat] of again) if (id !== "busy") expect(first.get(id)).toBe(seat);
  });

  it("does not move an off-duty member when a free console is left", () => {
    const idle = [officer("i0", "idle", 0), officer("i1", "idle", 1)];
    const first = homeSeats(bridge, idle, "officer", new Map());
    const again = homeSeats(bridge, [...idle, officer("w", "working", 5)], "officer", first);
    expect(again.get("i0")).toBe(first.get("i0"));
    expect(again.get("i1")).toBe(first.get("i1"));
    expect(again.get("w")).toBe("pit_p_2");
  });

  it("keeps a member's console when someone before them leaves", () => {
    const first = homeSeats(bridge, crew, "officer", new Map());
    const after = homeSeats(bridge, crew.filter((m) => m.id !== "a"), "officer", first);
    expect(after.get("c")).toBe(first.get("c"));
    expect(after.get("b")).toBe(first.get("b"));
  });

  it("never seats two members on one socket and leaves the overflow unseated", () => {
    const many = Array.from({ length: 9 }, (_, i) => officer(`m${i}`, "working", i));
    const placed = placeOnDeck({ deck: bridge, crew: many, rounds: new Map(), nowMs: 0, previous: new Map() }).placements;
    const sockets = [...placed.values()].map((p) => socketKey(p.socket));
    expect(new Set(sockets).size).toBe(sockets.length);
    expect(placed.size).toBe(6);
  });

  it("places only the members whose venue is on this deck", () => {
    const placed = placeOnDeck({ deck: ops, crew, rounds: new Map(), nowMs: 0, previous: new Map() }).placements;
    expect(placed.get("b")).toMatchObject({ venue: "bunk", activity: "sleep" });
    expect(placed.has("a")).toBe(false);
    expect(placed.has("c")).toBe(false);
  });

  it("spreads a round around the table and keeps places across refreshes", () => {
    const team = [officer("s", "working", 1), officer("l1", "idle", 2), officer("l2", "idle", 3)];
    const rounds = new Map<string, RoundPart>([["s", "speaker"], ["l1", "listener"], ["l2", "listener"]]);
    const first = placeOnDeck({ deck: bridge, crew: team, rounds, nowMs: 0, previous: new Map() }).placements;
    expect([...first.values()].every((p) => p.venue === "briefing")).toBe(true);
    expect(new Set([...first.values()].map((p) => socketKey(p.socket))).size).toBe(3);
    const previous = new Map([...first].map(([id, p]) => [id, socketKey(p.socket)]));
    const again = placeOnDeck({ deck: bridge, crew: [...team].reverse(), rounds, nowMs: 5000, previous }).placements;
    for (const [id, p] of first) expect(again.get(id)?.socket.id).toBe(p.socket.id);
  });
});
