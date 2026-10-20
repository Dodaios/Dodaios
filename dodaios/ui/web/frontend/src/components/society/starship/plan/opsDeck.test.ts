import { describe, expect, it } from "vitest";
import { buildOpsDeck, planDivisions, BAY_SEATS, ringRadius } from "./opsDeck";
import { buildNavGrid, findPath, isFree } from "../nav/shipNav";
import type { CrewInput, DeckPlan, TeamInput } from "./types";

function crew(n: number, prefix = "a"): CrewInput[] {
  return Array.from({ length: n }, (_, i) => ({ agentId: `${prefix}${i}`, name: `Agent ${i}`, tier: "specialist", state: "idle", createdMs: 1000 + i }));
}

function teams(groups: string[][]): TeamInput[] {
  return groups.map((members, i) => ({ id: `t${i}`, name: `Team ${i}`, members, createdMs: 10 + i, leadId: members[0] ?? null }));
}

function reachable(plan: DeckPlan) {
  const grid = buildNavGrid(plan);
  const from = plan.lift;
  const misses: string[] = [];
  for (const place of plan.places) if (!findPath(grid, from, place)) misses.push(place.id);
  for (const station of plan.stations) if (!findPath(grid, from, station)) misses.push(station.id);
  return { grid, misses };
}

describe("operations deck plan", () => {
  it("seats the crew without a team in the first bay and keeps a free bay", () => {
    const plan = buildOpsDeck({ crew: crew(5), teams: [] });
    expect(plan.divisions).toHaveLength(1);
    expect(plan.divisions[0].teamId).toBeNull();
    expect(plan.divisions[0].members).toHaveLength(5);
    expect(plan.stations.some((s) => s.kind === "newDivision")).toBe(true);
    for (const c of crew(5)) expect(plan.seatOf.get(c.agentId)?.owner).toBe(c.agentId);
  });

  it("gives every team its division, the lead the head console", () => {
    const all = crew(12);
    const groups = teams([["a3", "a4", "a5"], ["a6", "a7"], ["a8", "a9", "a10", "a11"]]);
    const plan = buildOpsDeck({ crew: all, teams: groups });
    expect(plan.divisions.map((d) => d.teamId)).toEqual([null, "t0", "t1", "t2"]);
    const t0 = plan.divisions[1];
    expect(t0.leadId).toBe("a3");
    expect(t0.members[0]).toBe("a3");
    // The head console is the gold one.
    const head = plan.props.find((p) => p.kind === "console" && p.ref === "a3");
    expect(head?.accent).toBe("#d9a441");
    expect(plan.divisions[0].members).toEqual(["a0", "a1", "a2"]);
  });

  it("is deterministic and does not depend on run state", () => {
    const a = buildOpsDeck({ crew: crew(9), teams: teams([["a1", "a2"]]) });
    const busy = crew(9).map((c, i) => ({ ...c, state: i % 2 ? ("working" as const) : ("waiting" as const) }));
    const b = buildOpsDeck({ crew: busy, teams: teams([["a1", "a2"]]) });
    expect(b.places.map((p) => [p.id, p.x, p.z])).toEqual(a.places.map((p) => [p.id, p.x, p.z]));
  });

  it("puts an agent in several teams in the oldest, unless it leads a younger one", () => {
    const groups: TeamInput[] = [
      { id: "old", name: "Old", members: ["a1", "a2"], createdMs: 1, leadId: null },
      { id: "young", name: "Young", members: ["a1", "a3"], createdMs: 2, leadId: "a3" },
      { id: "led", name: "Led", members: ["a2"], createdMs: 3, leadId: "a2" },
    ];
    const { divisions } = planDivisions(crew(4), groups, 6);
    const of = (id: string) => divisions.find((d) => d.members.some((m) => m.agentId === id))?.teamId;
    expect(of("a1")).toBe("old");
    expect(of("a2")).toBe("led");
    expect(of("a3")).toBe("young");
  });

  it("never seats the lead tier on this deck", () => {
    const all = [...crew(3), { agentId: "jarvis", name: "Jarvis", tier: "lead" as const, state: "idle" as const, createdMs: 0 }];
    const plan = buildOpsDeck({ crew: all, teams: [] });
    expect(plan.seatOf.has("jarvis")).toBe(false);
  });

  it("caps a division and sends the rest to the crew without a team", () => {
    const all = crew(BAY_SEATS + 4);
    const plan = buildOpsDeck({ crew: all, teams: teams([all.map((c) => c.agentId)]) });
    const team = plan.divisions.find((d) => d.teamId === "t0");
    expect(team?.members).toHaveLength(BAY_SEATS);
    expect(plan.divisions[0].members).toHaveLength(4);
    expect(plan.unseated).toEqual([]);
  });

  it("grows the ring with the team", () => {
    expect(ringRadius(6)).toBeLessThan(ringRadius(18));
    expect(ringRadius(1)).toBeGreaterThan(3);
  });

  it.each([
    ["empty", 0, [] as string[][]],
    ["one team", 6, [["a0", "a1", "a2"]]],
    ["eight teams", 40, Array.from({ length: 8 }, (_, t) => Array.from({ length: 5 }, (_, k) => `a${t * 5 + k}`))],
  ])("reaches every place and station from the turbolift (%s)", (_name, n, groups) => {
    const plan = buildOpsDeck({ crew: crew(n), teams: teams(groups) });
    const { grid, misses } = reachable(plan);
    expect(misses).toEqual([]);
    expect(isFree(grid, plan.lift)).toBe(true);
    expect(isFree(grid, plan.arrival)).toBe(true);
  });

  it("keeps ids unique and every seat inside the hull", () => {
    const plan = buildOpsDeck({ crew: crew(30), teams: teams([["a0", "a1"], ["a2", "a3", "a4"]]) });
    const ids = [...plan.props.map((x) => `prop:${x.id}`), ...plan.places.map((x) => `place:${x.id}`), ...plan.stations.map((x) => `station:${x.id}`)];
    expect(new Set(ids).size).toBe(ids.length);
    for (const place of plan.places) {
      expect(place.x).toBeGreaterThan(plan.bounds.x0);
      expect(place.x).toBeLessThan(plan.bounds.x1);
    }
  });
});
