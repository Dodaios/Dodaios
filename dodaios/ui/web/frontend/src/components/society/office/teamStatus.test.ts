import { describe, expect, it } from "vitest";
import { teamMark } from "./teamStatus";

const NOW = 1_000_000;
const gathering = { groupId: "g1", untilMs: NOW + 60_000 };

describe("what a team's mark may claim", () => {
  it("is live only while the backend reports a running round", () => {
    expect(teamMark("g1", { g1: { running: true } }, null, NOW)).toBe("live");
    expect(teamMark("g1", { g1: { running: false } }, null, NOW)).toBeNull();
    expect(teamMark("g1", {}, null, NOW)).toBeNull();
    // Another team's round says nothing about this one.
    expect(teamMark("g1", { g2: { running: true } }, null, NOW)).toBeNull();
  });

  it("never calls the person's own gathering live", () => {
    expect(teamMark("g1", {}, gathering, NOW)).toBe("called");
    expect(teamMark("g1", { g1: { running: false } }, gathering, NOW)).toBe("called");
    expect(teamMark("g2", {}, gathering, NOW)).toBeNull();
  });

  it("drops the gathering once its time is up", () => {
    expect(teamMark("g1", {}, { groupId: "g1", untilMs: NOW }, NOW)).toBeNull();
    expect(teamMark("g1", {}, { groupId: "g1", untilMs: NOW - 1 }, NOW)).toBeNull();
  });

  it("shows the real round when a called team is also answering", () => {
    expect(teamMark("g1", { g1: { running: true } }, gathering, NOW)).toBe("live");
  });
});
