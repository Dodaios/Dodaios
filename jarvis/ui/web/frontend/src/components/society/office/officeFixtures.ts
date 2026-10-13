/**
 * Floors for the behaviour, teamwork and walking tests: a roster with teams
 * built through the public floor-plan builder, and small hand-made rooms for
 * the cases a real floor does not isolate (a door, a corridor, a dead end).
 * Test support only; nothing at runtime imports it.
 */
import { buildOfficeLayout, type OfficeAgentInput, type OfficeLayout, type OfficeTeamInput, type Rect } from "./officeLayout";
import { buildNavGrid, type NavGrid } from "./officeNav";

export function rosterOf(count: number): OfficeAgentInput[] {
  return Array.from({ length: count }, (_, i) => ({
    agentId: `a${i}`, name: `Agent ${i}`, tier: "specialist" as const, providerLabel: i % 2 ? "Codex" : "Gemini", state: "idle" as const, createdMs: i,
  }));
}

/**
 * Teams of the given sizes over the first agents of the roster, in order; whoever is left has no team.
 * `leads[i]` names team i's lead by its place among the team's members (absent or null: the team has none).
 */
export function teamsOf(roster: readonly OfficeAgentInput[], sizes: readonly number[], leads: readonly (number | null)[] = []): OfficeTeamInput[] {
  let next = 0;
  return sizes.map((size, i) => {
    const members = roster.slice(next, next + size).map((a) => a.agentId);
    next += size;
    const lead = leads[i];
    return { id: `team-${i}`, name: `Team ${i}`, members, createdMs: 100 + i, ...(lead != null ? { leadId: members[lead] } : {}) };
  });
}

export interface Campus { roster: OfficeAgentInput[]; teams: OfficeTeamInput[]; layout: OfficeLayout; grid: NavGrid }

/** The agents floor for `count` agents in teams of `sizes` (the rest sit in the pool). */
export function campusOf(count: number, sizes: readonly number[], leads: readonly (number | null)[] = []): Campus {
  const roster = rosterOf(count);
  const teams = teamsOf(roster, sizes, leads);
  const layout = buildOfficeLayout(roster, { teams });
  return { roster, teams, layout, grid: buildNavGrid(layout) };
}

/** A bare rectangular floor `w` × `d` metres from the origin with the given solid rectangles on it. */
export function roomGrid(w: number, d: number, obstacles: readonly Rect[] = []): NavGrid {
  return buildNavGrid({ floor: { minX: 0, maxX: w, minZ: 0, maxZ: d }, obstacles: [...obstacles] } as unknown as OfficeLayout);
}

/** A wall across a room at `x` (0.12 m thick) with one door: a gap `doorWidth` wide centred on `doorZ`. */
export function wallWithDoor(x: number, depth: number, doorZ: number, doorWidth: number): Rect[] {
  return [
    { minX: x - 0.06, maxX: x + 0.06, minZ: 0, maxZ: doorZ - doorWidth / 2 },
    { minX: x - 0.06, maxX: x + 0.06, minZ: doorZ + doorWidth / 2, maxZ: depth },
  ];
}
