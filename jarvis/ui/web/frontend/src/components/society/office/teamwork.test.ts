import { describe, expect, it } from "vitest";
import type { SocietyMeeting } from "@/lib/societyChatGroups";
import { bubbleText } from "./officeTalk";
import {
  HANDOFF_BUBBLE_MS, HANDOFF_FRESH_MS, MAX_ROUND_LINES, ROLE_GRACE_MS, SPOKE_LINGER_MS, applyRoomChange, applyRoomLine, applySnapshot, emptyRound,
  freshHandoffs, handoffFrom, isSpeaking, lastSpokeBy, meetingTeamId, pendingHandoff, queueHandoff, roundFor, roundRole, steadyRole, teamBubble, teamBubbleLive,
  type Handoff, type RoleMemory, type TeamRound,
} from "./teamwork";
import { BOARD_REFRESH_MS, MAX_READS_PER_TICK, SWEEP_MS, SWEEP_READS_PER_TICK, dueTeams } from "./useTeamRounds";

const meeting = (messages: [string, string, string][], running: boolean, next: string | null = null, members?: string[]): SocietyMeeting => ({
  messages: messages.map(([id, speaker, text]) => ({ id, speaker, text })),
  running,
  room: { state: running ? "running" : "settled", settle_reason: "", next_speaker: next, ...(members ? { members } : {}) } as SocietyMeeting["room"],
});

describe("meetingTeamId", () => {
  it("reads the team out of a meeting room id and ignores every other room", () => {
    expect(meetingTeamId("meeting:grp_42:9f3a")).toBe("grp_42");
    expect(meetingTeamId("meeting:a:b:c:9f3a")).toBe("a:b:c");
    expect(meetingTeamId("meeting:grp_42")).toBe("grp_42");
    expect(meetingTeamId("room:town-hall")).toBeNull();
    expect(meetingTeamId("")).toBeNull();
    expect(meetingTeamId(undefined)).toBeNull();
  });
});

describe("a team's round from its meeting", () => {
  it("takes state, speaker, members and the newest lines from a snapshot", () => {
    const round = applySnapshot(undefined, "t", meeting([["r1", "user", "Plan the launch"], ["e1", "nora", "I take the copy."]], true, "ben", ["nora", "ben"]), 1000);
    expect(round).toMatchObject({ teamId: "t", running: true, speakerId: "ben", members: ["nora", "ben"], loaded: true, fetchedMs: 1000, dirty: false });
    expect(round.lines.map((l) => l.speaker)).toEqual(["user", "nora"]);
  });

  it("never replays an old transcript as fresh speech when the office opens", () => {
    const first = applySnapshot(undefined, "t", meeting([["r1", "user", "Hi"], ["e1", "nora", "Hello."]], false), 1000);
    expect(first.spoke).toBeNull();
    expect(first.speakerId).toBeNull();
  });

  it("counts a line that is new since the last snapshot as just said, once", () => {
    const first = applySnapshot(undefined, "t", meeting([["r1", "user", "Hi"]], true, "nora"), 1000);
    const second = applySnapshot(first, "t", meeting([["r1", "user", "Hi"], ["e1", "nora", "Hello."]], true, "ben"), 4000);
    expect(second.spoke).toEqual({ id: "e1", speaker: "nora", text: "Hello.", atMs: 4000 });
    expect(second.speakerId).toBe("ben");
    const third = applySnapshot(second, "t", meeting([["r1", "user", "Hi"], ["e1", "nora", "Hello."]], false), 7000);
    expect(third.spoke?.atMs).toBe(4000);
    expect(third).toMatchObject({ running: false, speakerId: null });
    // The person's own line is on the board, never over an agent's head.
    const fourth = applySnapshot(third, "t", meeting([["e1", "nora", "Hello."], ["r2", "user", "Thanks"]], true, "nora"), 9000);
    expect(fourth.spoke?.id).toBe("e1");
  });

  it("keeps the newest lines only and drops empty ones (a silent pass says nothing)", () => {
    const many: [string, string, string][] = Array.from({ length: 30 }, (_, i) => [`e${i}`, "nora", i === 29 ? "   " : `line ${i}`]);
    const round = applySnapshot(undefined, "t", meeting(many, false), 1);
    expect(round.lines).toHaveLength(MAX_ROUND_LINES);
    expect(round.lines[round.lines.length - 1].id).toBe("e28");
  });

  it("opens and settles on the socket's room events, and asks for a fresh read", () => {
    const opened = applyRoomChange(undefined, "t", "open", ["nora", "ben"]);
    expect(opened).toMatchObject({ running: true, dirty: true, members: ["nora", "ben"], loaded: false });
    const settled = applyRoomChange({ ...opened, speakerId: "nora" }, "t", "settle");
    expect(settled).toMatchObject({ running: false, speakerId: null, dirty: true, members: ["nora", "ben"] });
    expect(applyRoomChange(settled, "t", "something-else")).toBe(settled);
  });

  it("adds a line said on the socket once, as just said, and frees the speaker's turn", () => {
    const running: TeamRound = { ...emptyRound("t"), running: true, speakerId: "nora", loaded: true };
    const said = applyRoomLine(running, "t", { id: "e1", speaker: "nora", text: "Done with the copy." }, 5000);
    expect(said.lines).toEqual([{ id: "e1", speaker: "nora", text: "Done with the copy." }]);
    expect(said.spoke).toMatchObject({ id: "e1", atMs: 5000 });
    expect(said).toMatchObject({ speakerId: null, dirty: true });
    const again = applyRoomLine(said, "t", { id: "e1", speaker: "nora", text: "Done with the copy." }, 9000);
    expect(again.lines).toHaveLength(1);
    expect(again.spoke?.atMs).toBe(5000);
    expect(applyRoomLine(said, "t", { id: "e2", speaker: "ben", text: "  " }, 9000).lines).toHaveLength(1);
  });
});

describe("an agent's part in a round", () => {
  const round: TeamRound = { ...emptyRound("t"), running: true, speakerId: "nora", members: ["nora", "ben", "kai"] };

  it("gathers the free, names the one contributing, and leaves the busy and the resting alone", () => {
    expect(roundRole({ agentId: "ben", state: "idle" }, round)).toBe("gather");
    // The speaker's run state reads working: that work is the round.
    expect(roundRole({ agentId: "nora", state: "working" }, round)).toBe("speaker");
    expect(roundRole({ agentId: "nora", state: "idle" }, round)).toBe("speaker");
    expect(roundRole({ agentId: "kai", state: "working" }, round)).toBe("busy");
    expect(roundRole({ agentId: "kai", state: "waiting" }, round)).toBe("busy");
    expect(roundRole({ agentId: "nora", state: "waiting" }, round)).toBe("busy");
    expect(roundRole({ agentId: "kai", state: "paused" }, round)).toBe("none");
  });

  it("is none without a running round: nobody gathers for a chat that is not answering", () => {
    expect(roundRole({ agentId: "ben", state: "idle" }, { ...round, running: false })).toBe("none");
    expect(roundRole({ agentId: "ben", state: "idle" }, undefined)).toBe("none");
  });

  it("finds the round an agent takes part in: its home team's, else one that lists it", () => {
    const rounds = { t: round, u: { ...emptyRound("u"), running: true, members: ["zoe"] }, v: { ...emptyRound("v"), members: ["ben"] } };
    expect(roundFor(rounds, "ben", "t")?.teamId).toBe("t");
    expect(roundFor(rounds, "zoe", null)?.teamId).toBe("u");
    expect(roundFor(rounds, "zoe", "v")?.teamId).toBe("u");
    expect(roundFor(rounds, "ben", "v")?.teamId).toBe("t");
    expect(roundFor(rounds, "stranger", null)).toBeUndefined();
  });

  it("holds a member at the board through the moments its state runs ahead of the meeting", () => {
    const memory: RoleMemory = { role: "none", busySinceMs: null };
    expect(steadyRole(memory, "gather", 0)).toBe("gather");
    // Its turn began: the roster already says working, the meeting has not named it yet.
    expect(steadyRole(memory, "busy", 1000)).toBe("gather");
    expect(steadyRole(memory, "busy", 1000 + ROLE_GRACE_MS - 1)).toBe("gather");
    expect(steadyRole(memory, "speaker", 3000)).toBe("speaker");
    // Its line is out, the roster still says working for a moment.
    expect(steadyRole(memory, "busy", 9000)).toBe("gather");
    expect(steadyRole(memory, "gather", 9500)).toBe("gather");
    // Really working on something else: after the grace it goes to its desk.
    expect(steadyRole(memory, "busy", 20000)).toBe("gather");
    expect(steadyRole(memory, "busy", 20000 + ROLE_GRACE_MS)).toBe("busy");
    expect(steadyRole(memory, "busy", 40000)).toBe("busy");
    expect(steadyRole(memory, "none", 41000)).toBe("none");
  });

  it("never holds back someone who was not at the board", () => {
    const memory: RoleMemory = { role: "none", busySinceMs: null };
    expect(steadyRole(memory, "busy", 0)).toBe("busy");
  });
});

const agents = new Map([
  ["jarvis", { tier: "lead" as const, name: "George" }],
  ["nora", { tier: "specialist" as const, name: "Nora" }],
  ["ben", { tier: "orchestrator" as const, name: "Ben" }],
]);

describe("a message from one agent to another", () => {
  const event = (extra: Record<string, unknown>) => ({ event_id: "ev1", msg_type: "ASSIGN", from_agent: "ben", to_agent: "nora", room_id: "", text: "Draft the release notes", ...extra });

  it("is read from the board's own event: sender, receiver, type and its real text", () => {
    expect(handoffFrom(event({}), agents, 500)).toEqual({
      id: "ev1", from: "ben", to: "nora", toName: "Nora", text: "Draft the release notes", msgType: "ASSIGN", atMs: 500, phase: "queued", untilMs: 500 + HANDOFF_FRESH_MS,
    });
    for (const msgType of ["SAY", "QUERY", "ANSWER", "PROPOSE"]) expect(handoffFrom(event({ msg_type: msgType }), agents, 1)?.msgType).toBe(msgType);
  });

  it("is not made up from anything else", () => {
    // A line said in a room, a result, a message to oneself, to nobody, to a stranger, or without words.
    expect(handoffFrom(event({ room_id: "meeting:t:1" }), agents, 1)).toBeNull();
    expect(handoffFrom(event({ msg_type: "RESULT" }), agents, 1)).toBeNull();
    expect(handoffFrom(event({ to_agent: "ben" }), agents, 1)).toBeNull();
    expect(handoffFrom(event({ to_agent: "" }), agents, 1)).toBeNull();
    expect(handoffFrom(event({ to_agent: "stranger" }), agents, 1)).toBeNull();
    expect(handoffFrom(event({ from_agent: "user" }), agents, 1)).toBeNull();
    expect(handoffFrom(event({ text: "  " }), agents, 1)).toBeNull();
    expect(handoffFrom(null, agents, 1)).toBeNull();
    // The lead's own messages are its pet's errands, and nobody walks to the pet.
    expect(handoffFrom(event({ from_agent: "jarvis" }), agents, 1)).toBeNull();
    expect(handoffFrom(event({ to_agent: "jarvis" }), agents, 1)).toBeNull();
  });

  const handoff = (id: string, from = "ben", atMs = 0): Handoff => ({ id, from, to: "nora", toName: "Nora", text: id, msgType: "SAY", atMs, phase: "queued", untilMs: atMs + HANDOFF_FRESH_MS });

  it("queues without duplicates, two per sender at most, and forgets what went stale", () => {
    let list = queueHandoff([], handoff("h1"));
    expect(queueHandoff(list, handoff("h1"))).toBe(list);
    list = queueHandoff(list, handoff("h2"));
    list = queueHandoff(list, handoff("h3"));
    expect(list.map((h) => h.id)).toEqual(["h2", "h3"]);
    list = queueHandoff(list, handoff("x1", "nora"));
    expect(list).toHaveLength(3);
    expect(pendingHandoff(list, "ben", 10)?.id).toBe("h2");
    expect(pendingHandoff(list, "kai", 10)).toBeNull();
    expect(freshHandoffs(list, 10)).toBe(list);
    expect(freshHandoffs(list, HANDOFF_FRESH_MS + 1)).toEqual([]);
    expect(pendingHandoff(list, "ben", HANDOFF_FRESH_MS + 1)).toBeNull();
  });
});

describe("what teamwork puts over an agent's head", () => {
  const labels = { thinking: "Thinking", to: "To {0}: {1}" };
  const spoke = { id: "e1", speaker: "nora", text: "**Done** with the copy.", atMs: 1000 };
  const handoff: Handoff = { id: "h1", from: "ben", to: "nora", toName: "Nora", text: "Draft the release notes", msgType: "ASSIGN", atMs: 1000, phase: "queued", untilMs: 91000 };
  const bubble = (input: Partial<Parameters<typeof teamBubble>[0]>) => teamBubble({ spoke: null, speaking: false, handoff: null, now: 2000, labels, short: bubbleText, ...input });

  it("shows the line an agent just said, in its own words, for a few seconds", () => {
    expect(bubble({ spoke })).toEqual({ kind: "speech", text: "Done with the copy.", live: false, atMs: 1000 });
    expect(bubble({ spoke, now: 1000 + SPOKE_LINGER_MS })).toBeNull();
  });

  it("shows a thought, not invented words, while the speaker's line is not written yet", () => {
    expect(bubble({ speaking: true })).toEqual({ kind: "thought", text: "Thinking", live: true, atMs: 0 });
    expect(bubble({ speaking: true, spoke })?.kind).toBe("speech");
  });

  it("shows the message a sender handed over: briefly at its desk, and while it stands with the receiver", () => {
    expect(bubble({ handoff })).toEqual({ kind: "speech", text: "To Nora: Draft the release notes", live: false, atMs: 1000 });
    expect(bubble({ handoff, now: 1000 + HANDOFF_BUBBLE_MS })).toBeNull();
    const delivering: Handoff = { ...handoff, phase: "delivering", untilMs: 60000 };
    expect(bubble({ handoff: delivering, now: 59000 })?.text).toBe("To Nora: Draft the release notes");
    expect(bubble({ handoff: delivering, now: 60001 })).toBeNull();
  });

  it("says nothing when nothing happened", () => {
    expect(bubble({})).toBeNull();
  });

  it("needs a clock only while something still lingers", () => {
    expect(teamBubbleLive(null, null, 5000)).toBe(false);
    expect(teamBubbleLive(spoke, null, 1000 + SPOKE_LINGER_MS - 1)).toBe(true);
    // A line said long ago stays in the round; it must not keep a bubble ticking for the rest of the session.
    expect(teamBubbleLive(spoke, null, 1000 + SPOKE_LINGER_MS)).toBe(false);
    expect(teamBubbleLive(spoke, null, 3_600_000)).toBe(false);
    expect(teamBubbleLive(null, handoff, 1000 + HANDOFF_BUBBLE_MS - 1)).toBe(true);
    expect(teamBubbleLive(null, handoff, 1000 + HANDOFF_BUBBLE_MS)).toBe(false);
    const delivering: Handoff = { ...handoff, phase: "delivering", untilMs: 60000 };
    expect(teamBubbleLive(null, delivering, 59999)).toBe(true);
    expect(teamBubbleLive(null, delivering, 60000)).toBe(false);
  });

  it("finds an agent's newest line and whether it is the speaker across teams", () => {
    const rounds = {
      t: { ...emptyRound("t"), running: true, speakerId: "ben", spoke },
      u: { ...emptyRound("u"), spoke: { ...spoke, id: "e9", atMs: 5000 } },
      v: { ...emptyRound("v"), running: false, speakerId: "kai" },
    };
    expect(lastSpokeBy(rounds, "nora")?.id).toBe("e9");
    expect(lastSpokeBy(rounds, "ben")).toBeNull();
    // One voice at a time: nora's line in team t gives way now that ben has the word there.
    expect(lastSpokeBy({ t: rounds.t }, "nora")).toBeNull();
    expect(lastSpokeBy({ t: { ...rounds.t, speakerId: null } }, "nora")?.id).toBe("e1");
    expect(lastSpokeBy({ t: { ...rounds.t, speakerId: "nora" } }, "nora")?.id).toBe("e1");
    // After the round has settled the last line may linger.
    expect(lastSpokeBy({ t: { ...rounds.t, running: false } }, "nora")?.id).toBe("e1");
    expect(isSpeaking(rounds, "ben")).toBe(true);
    expect(isSpeaking(rounds, "kai")).toBe(false);
  });
});

describe("which meetings are read on a tick", () => {
  const round = (teamId: string, extra: Partial<TeamRound>): TeamRound => ({ ...emptyRound(teamId), loaded: true, fetchedMs: 100_000, ...extra });
  const base = { teamIds: ["a", "b", "c", "d", "e", "f"], near: new Set<string>(), inRoom: new Set<string>(), now: 100_500 };

  it("reads nothing while every team was read lately and nothing is running, changed or near", () => {
    expect(dueTeams({ ...base, rounds: Object.fromEntries(base.teamIds.map((id) => [id, round(id, {})])) })).toEqual([]);
  });

  it("finds what nobody announced: every team is read once after waking, two a tick, and again after about a minute", () => {
    // Nothing known yet (the office just opened, or a socket event was missed): the sweep starts at once.
    const rounds: Record<string, TeamRound> = {};
    const seen: string[] = [];
    let now = 100_500;
    for (let tick = 0; tick < 3; tick += 1) {
      const due = dueTeams({ ...base, rounds, now });
      expect(due).toHaveLength(SWEEP_READS_PER_TICK);
      for (const id of due) { seen.push(id); rounds[id] = round(id, { fetchedMs: now }); }
      now += 3000;
    }
    expect([...seen].sort()).toEqual(base.teamIds);
    expect(dueTeams({ ...base, rounds, now })).toEqual([]);
    // A minute on, the teams read first are due again, the longest unread first.
    expect(dueTeams({ ...base, rounds, now: 100_500 + SWEEP_MS })).toEqual(seen.slice(0, 2));
    expect(dueTeams({ ...base, rounds, now: 100_500 + SWEEP_MS - 1 })).toEqual([]);
    // The caller's jitter moves the period.
    expect(dueTeams({ ...base, rounds, now: 100_500 + SWEEP_MS - 5000, sweepMs: SWEEP_MS * 0.9 })).toEqual(seen.slice(0, 2));
  });

  it("keeps room for the sweep on a tick full of running rounds", () => {
    const rounds = Object.fromEntries(["a", "b", "c", "d", "e"].map((id) => [id, round(id, { running: true, fetchedMs: 99_000 })]));
    const due = dueTeams({ ...base, rounds });
    expect(due).toHaveLength(MAX_READS_PER_TICK);
    expect(due).toContain("f");
    expect(due.filter((id) => id !== "f")).toHaveLength(3);
  });

  it("reads running and freshly changed rounds first, longest unread first, capped", () => {
    const rounds = {
      a: round("a", { running: true, fetchedMs: 99_000 }), b: round("b", { dirty: true, fetchedMs: 98_000 }), c: round("c", { running: true, fetchedMs: 97_000 }),
      d: round("d", { running: true }), e: round("e", { running: true, fetchedMs: 96_000 }), f: round("f", {}),
    };
    const due = dueTeams({ ...base, rounds, near: new Set(["f"]) });
    expect(due).toEqual(["e", "c", "b", "a"]);
    // Nothing was left for the sweep here, so the running rounds take the whole tick.
    expect(due).toHaveLength(MAX_READS_PER_TICK);
  });

  const fresh = () => Object.fromEntries(base.teamIds.map((id) => [id, round(id, {})]));

  it("reads a board near the camera again once its transcript has aged, and a far one only with the sweep", () => {
    const rounds = { ...fresh(), b: round("b", { fetchedMs: 100_500 - BOARD_REFRESH_MS }) };
    expect(dueTeams({ ...base, rounds, near: new Set(["a", "b"]) })).toEqual(["b"]);
    expect(dueTeams({ ...base, rounds, near: new Set() })).toEqual([]);
  });

  it("checks a team the roster shows in a room, but not on every tick", () => {
    const rounds = { ...fresh(), a: round("a", { fetchedMs: 100_000 }), b: round("b", { fetchedMs: 90_000 }) };
    expect(dueTeams({ ...base, rounds, inRoom: new Set(["a", "b"]) })).toEqual(["b"]);
  });
});
