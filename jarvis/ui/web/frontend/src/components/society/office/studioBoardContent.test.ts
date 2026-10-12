import { describe, expect, it } from "vitest";
import type { AgentRunState } from "../data";
import { emptyRound, type TeamRound } from "./teamwork";
import {
  MAX_BOARD_LINES, MAX_BOARD_MEMBERS, MAX_LIVE_BOARDS, boardModel, boardSignature, pickBoards, type BoardLabels,
} from "./studioBoardContent";

const labels: BoardLabels = {
  pool: "Open studio", members: "{0} members", live: "Live", speaking: "Speaking", you: "You",
  empty: "Nothing has been said yet.", poolNote: "No team yet.", loading: "Reading…", unavailable: "Cannot be read.", more: "+{0} more",
  state: { working: "Working", waiting: "Waiting", idle: "Idle", paused: "Paused" },
};
const agent = (name: string, state: AgentRunState) => ({ name, state });
const agents = new Map([["nora", agent("Nora", "working")], ["ben", agent("Ben", "idle")], ["kai", agent("Kai", "waiting")], ["zoe", agent("Zoe", "paused")]]);
const studio = { name: "Launch crew", teamId: "t", members: ["nora", "ben", "kai"] };
const round = (extra: Partial<TeamRound>): TeamRound => ({ ...emptyRound("t"), loaded: true, ...extra });

describe("what a studio board shows", () => {
  it("names the team and lists its members with the state each is really in", () => {
    const model = boardModel(studio, agents, round({}), labels);
    expect(model).toMatchObject({ title: "Launch crew", count: "3 members", live: false, hidden: 0 });
    expect(model.members).toEqual([
      { id: "nora", name: "Nora", state: "working", speaking: false },
      { id: "ben", name: "Ben", state: "idle", speaking: false },
      { id: "kai", name: "Kai", state: "waiting", speaking: false },
    ]);
  });

  it("marks a running round and the member contributing to it", () => {
    const model = boardModel(studio, agents, round({ running: true, speakerId: "nora" }), labels);
    expect(model.live).toBe(true);
    expect(model.members.map((m) => m.speaking)).toEqual([true, false, false]);
    // A speaker left over from a settled round is nobody's turn.
    expect(boardModel(studio, agents, round({ running: false, speakerId: "nora" }), labels).members.some((m) => m.speaking)).toBe(false);
  });

  it("shows the newest real lines of the team's chat, the person's as theirs, in plain text", () => {
    const lines = Array.from({ length: 9 }, (_, i) => ({ id: `e${i}`, speaker: i % 3 === 0 ? "user" : "nora", text: `**line** ${i} with a [link](https://example.test)` }));
    const model = boardModel(studio, agents, round({ lines }), labels);
    expect(model.lines).toHaveLength(MAX_BOARD_LINES);
    expect(model.lines[model.lines.length - 1]).toEqual({ id: "e8", who: "Nora", text: "line 8 with a link", fromPerson: false });
    expect(model.lines.find((l) => l.fromPerson)?.who).toBe("You");
    expect(model.note).toBeNull();
  });

  it("is honest when there is nothing to show", () => {
    expect(boardModel(studio, agents, round({}), labels).note).toBe(labels.empty);
    expect(boardModel(studio, agents, undefined, labels).note).toBe(labels.loading);
    expect(boardModel(studio, agents, { ...emptyRound("t") }, labels).note).toBe(labels.loading);
    // A team whose chat could never be read says so instead of "reading" for ever.
    expect(boardModel(studio, agents, { ...emptyRound("t"), unavailable: true }, labels).note).toBe(labels.unavailable);
    // What was read before a failure stays on the board.
    expect(boardModel(studio, agents, round({ unavailable: true, lines: [{ id: "e1", speaker: "nora", text: "hi" }] }), labels).note).toBeNull();
    // The pool has no team chat: it says so, and never borrows lines.
    const pool = boardModel({ name: "", teamId: null, members: ["zoe"] }, agents, round({ lines: [{ id: "e1", speaker: "nora", text: "hi" }] }), labels);
    expect(pool).toMatchObject({ title: "Open studio", note: labels.poolNote, lines: [], count: "1 members" });
  });

  it("adds team members who sit in another studio, skips who left the roster, and counts who does not fit", () => {
    const model = boardModel(studio, agents, round({ members: ["nora", "zoe", "gone"] }), labels);
    expect(model.members.map((m) => m.id)).toEqual(["nora", "ben", "kai", "zoe"]);
    const crowd = new Map(Array.from({ length: 9 }, (_, i) => [`m${i}`, agent(`M${i}`, "idle")] as const));
    const big = boardModel({ name: "Big", teamId: "t", members: [...crowd.keys()] }, crowd, round({}), labels);
    expect(big.members).toHaveLength(MAX_BOARD_MEMBERS);
    expect(big.hidden).toBe(9 - MAX_BOARD_MEMBERS);
    expect(big.count).toBe("9 members");
  });

  it("changes its signature only when the face would look different", () => {
    const a = boardModel(studio, agents, round({ lines: [{ id: "e1", speaker: "nora", text: "hi" }] }), labels);
    const same = boardModel(studio, new Map(agents), round({ lines: [{ id: "e1", speaker: "nora", text: "hi" }], fetchedMs: 999, dirty: true }), labels);
    expect(boardSignature(same, labels)).toBe(boardSignature(a, labels));
    const busy = new Map(agents).set("ben", agent("Ben", "working"));
    expect(boardSignature(boardModel(studio, busy, round({ lines: [{ id: "e1", speaker: "nora", text: "hi" }] }), labels), labels)).not.toBe(boardSignature(a, labels));
    expect(boardSignature(boardModel(studio, agents, round({ running: true, lines: [{ id: "e1", speaker: "nora", text: "hi" }] }), labels), labels)).not.toBe(boardSignature(a, labels));
  });
});

describe("which boards are live", () => {
  it("draws the boards in view and keeps only the nearest few teams current", () => {
    const boards = [
      { id: "b-pool", teamId: null, distance: 5 }, { id: "b1", teamId: "t1", distance: 12 }, { id: "b2", teamId: "t2", distance: 8 },
      { id: "b3", teamId: "t3", distance: 20 }, { id: "b4", teamId: "t4", distance: 25 }, { id: "b5", teamId: "t5", distance: 45 }, { id: "b6", teamId: "t6", distance: 90 },
    ];
    const { drawn, live } = pickBoards(boards);
    expect([...drawn].sort()).toEqual(["b-pool", "b1", "b2", "b3", "b4", "b5"]);
    expect([...live]).toEqual(["t2", "t1", "t3"]);
    expect(live.size).toBe(MAX_LIVE_BOARDS);
  });
  it("keeps nothing live from the overview", () => {
    expect(pickBoards([{ id: "b1", teamId: "t1", distance: 120 }])).toEqual({ drawn: new Set(), live: new Set() });
  });
});
