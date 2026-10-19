import { describe, expect, it } from "vitest";
import { Color } from "three";

import { CODING_SCENE, CODING_TEAMS, codingTeam } from "./officePalette";

describe("coding floor look", () => {
  it("gives the six neighbourhoods a floor can hold six different team colours, cycled for any index", () => {
    expect(new Set(CODING_TEAMS.map((t) => t.accent)).size).toBe(CODING_TEAMS.length);
    expect(CODING_TEAMS.length).toBeGreaterThanOrEqual(6);
    expect(codingTeam(CODING_TEAMS.length)).toBe(codingTeam(0));
    expect(codingTeam(-1)).toBe(codingTeam(CODING_TEAMS.length - 1));
  });

  it("keeps team colours apart from the busy lights' status colours", () => {
    for (const team of CODING_TEAMS) {
      for (const status of [CODING_SCENE.busy.working, CODING_SCENE.busy.waiting, CODING_SCENE.busy.error]) {
        const a = new Color(team.accent), b = new Color(status);
        expect(Math.hypot(a.r - b.r, a.g - b.g, a.b - b.b), `${team.accent} vs ${status}`).toBeGreaterThan(0.2);
      }
    }
  });
});
