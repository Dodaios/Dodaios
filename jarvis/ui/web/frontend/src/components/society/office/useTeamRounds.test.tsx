import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import type { SocietyMeeting } from "@/lib/societyChatGroups";
import { useEventStore } from "@/store/events";
import type { SocietyAgent } from "../data";
import type { Studio } from "./officeLayout";
import { READ_TIMEOUT_MS } from "./pollSignal";
import { boardWatch, emptyRound, useTeamwork } from "./teamwork";
import { BOARD_REFRESH_MS, MAX_FAILED_READS, ROUND_POLL_MS, SWEEP_MS, afterFailedRead, useTeamRounds } from "./useTeamRounds";

const reads = vi.hoisted(() => ({ calls: [] as string[], answer: new Map<string, unknown>(), signals: [] as (AbortSignal | undefined)[] }));
/** An answer that never comes: a request hanging on a half-open socket. */
const HANGS = "hangs";
vi.mock("@/lib/societyChatGroups", () => ({
  fetchSocietyMeeting: (groupId: string, signal?: AbortSignal) => {
    reads.calls.push(groupId);
    reads.signals.push(signal);
    const answer = reads.answer.get(groupId);
    if (answer === "hangs") return new Promise(() => undefined);
    return answer instanceof Error ? Promise.reject(answer) : Promise.resolve(answer);
  },
}));
/** The key under which these tests say which boards a camera is near. */
const STAGE = Symbol("test-stage");

const agent = (agentId: string, tier = "specialist", checkpoint = "desk") => ({ agentId, name: agentId.toUpperCase(), tier, checkpoint } as unknown as SocietyAgent);
const roster = (extra: SocietyAgent[] = []) => new Map([agent("jarvis", "lead"), agent("nora"), agent("ben"), agent("kai"), ...extra].map((a) => [a.agentId, a]));
const studio = (teamId: string | null, members: string[]): Studio => ({
  deptId: `studio-${teamId ?? "pool"}`, teamId, name: teamId ?? "", members, leadId: null, board: null, huddleSpotIds: [], centre: { x: 0, z: 0 },
});
const studios = [studio(null, ["kai"]), studio("t1", ["nora", "ben"]), studio("t2", [])];
const meeting = (running: boolean, messages: [string, string, string][] = [], next: string | null = null): SocietyMeeting => ({
  messages: messages.map(([id, speaker, text]) => ({ id, speaker, text })), running, room: { state: running ? "running" : "settled", settle_reason: "", next_speaker: next },
});
let seq = 0;
const push = (name: string, payload: Record<string, unknown>) => act(() => {
  useEventStore.getState().pushEvent({ id: `ev-${seq += 1}`, name, layer: "society", ts: Date.now(), payload });
});
/** Let exactly one scheduled tick (and the reads it starts) run: with the jitter pinned to its middle, one every three seconds. */
const tick = async () => { await act(async () => { await vi.advanceTimersByTimeAsync(ROUND_POLL_MS + 600); }); };

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(Math, "random").mockReturnValue(0.5);
  reads.calls.length = 0;
  reads.signals.length = 0;
  reads.answer.clear();
  reads.answer.set("t1", meeting(false));
  reads.answer.set("t2", meeting(false));
  boardWatch.reset();
  useTeamwork.getState().reset();
  vi.spyOn(console, "debug").mockImplementation(() => undefined);
});

afterEach(() => {
  // Unmount, so the one poller's lease is free for the next test.
  cleanup();
  vi.restoreAllMocks();
  vi.useRealTimers();
  useTeamwork.getState().reset();
});

describe("useTeamRounds", () => {
  it("reads every team once after waking, then leaves a quiet campus alone until the sweep comes round", async () => {
    renderHook(() => useTeamRounds(studios, roster(), true));
    await tick();
    expect([...reads.calls].sort()).toEqual(["t1", "t2"]);
    for (let i = 0; i < 6; i += 1) await tick();
    expect(reads.calls).toHaveLength(2);
    // About a minute later each team is looked at again.
    await act(async () => { await vi.advanceTimersByTimeAsync(SWEEP_MS); });
    expect([...reads.calls].sort()).toEqual(["t1", "t1", "t2", "t2"]);
  });

  it("finds a round that was already running when the office opened, without any socket event", async () => {
    reads.answer.set("t1", meeting(true, [["r1", "user", "Plan the launch"], ["e1", "nora", "I take the copy."]], "ben"));
    renderHook(() => useTeamRounds(studios, roster(), true));
    expect(useTeamwork.getState().rounds).toEqual({});
    await tick();
    const round = useTeamwork.getState().rounds.t1;
    expect(round).toMatchObject({ running: true, speakerId: "ben", loaded: true });
    expect(round.lines.map((l) => l.id)).toEqual(["r1", "e1"]);
    // An old line is on the board, not replayed over anybody's head.
    expect(round.spoke).toBeNull();
    // From now on it is followed like any running round, tick by tick.
    reads.answer.set("t1", meeting(true, [["r1", "user", "Plan the launch"], ["e1", "nora", "I take the copy."], ["e2", "ben", "I book the room."]], "nora"));
    await tick();
    expect(useTeamwork.getState().rounds.t1).toMatchObject({ speakerId: "nora", spoke: { id: "e2", speaker: "ben" } });
    // And its end is found the same way.
    reads.answer.set("t1", meeting(false, [["r1", "user", "Plan the launch"], ["e1", "nora", "I take the copy."], ["e2", "ben", "I book the room."]]));
    await tick();
    expect(useTeamwork.getState().rounds.t1).toMatchObject({ running: false, speakerId: null });
  });

  it("follows a round from the socket: it opens, a member speaks, it settles", async () => {
    renderHook(() => useTeamRounds(studios, roster(), true));
    push("SocietyRoomChanged", { room_id: "meeting:t1:9f", phase: "open", members: ["nora", "ben"] });
    expect(useTeamwork.getState().rounds.t1).toMatchObject({ running: true, members: ["nora", "ben"] });

    reads.answer.set("t1", meeting(true, [["r1", "user", "Plan the launch"]], "nora"));
    await tick();
    expect(reads.calls).toContain("t1");
    expect(useTeamwork.getState().rounds.t1).toMatchObject({ running: true, speakerId: "nora", loaded: true });

    push("SocietyMessageSent", { event_id: "e1", msg_type: "SAY", from_agent: "nora", to_agent: "", room_id: "meeting:t1:9f", text: "I take the copy." });
    const said = useTeamwork.getState().rounds.t1;
    expect(said.spoke).toMatchObject({ id: "e1", speaker: "nora", text: "I take the copy." });
    expect(said.speakerId).toBeNull();
    // A line said in a room is never a message between two agents.
    expect(useTeamwork.getState().handoffs).toEqual([]);

    reads.answer.set("t1", meeting(true, [["r1", "user", "Plan the launch"], ["e1", "nora", "I take the copy."]], "ben"));
    await tick();
    expect(useTeamwork.getState().rounds.t1.speakerId).toBe("ben");

    push("SocietyRoomChanged", { room_id: "meeting:t1:9f", phase: "settle", reason: "user_round_complete" });
    expect(useTeamwork.getState().rounds.t1).toMatchObject({ running: false, speakerId: null });
    reads.answer.set("t1", meeting(false, [["r1", "user", "Plan the launch"], ["e1", "nora", "I take the copy."]]));
    await tick();
    const before = reads.calls.length;
    await tick();
    await tick();
    // Settled and read once more: it is left alone again.
    expect(reads.calls.length).toBe(before);
  });

  it("ignores rooms that are not a team's meeting, and teams the floor does not have", async () => {
    renderHook(() => useTeamRounds(studios, roster(), true));
    push("SocietyRoomChanged", { room_id: "town-hall:7", phase: "open", members: ["nora"] });
    push("SocietyRoomChanged", { room_id: "meeting:somebody-else:1", phase: "open", members: ["nora"] });
    push("SocietyMessageSent", { event_id: "e9", msg_type: "SAY", from_agent: "nora", to_agent: "", room_id: "meeting:somebody-else:1", text: "hi" });
    expect(useTeamwork.getState().rounds).toEqual({});
    await tick();
    expect(reads.calls).not.toContain("somebody-else");
    expect(Object.keys(useTeamwork.getState().rounds).sort()).toEqual(["t1", "t2"]);
  });

  it("queues a message one agent sent another, and leaves the lead's errands to its pet", () => {
    renderHook(() => useTeamRounds(studios, roster(), true));
    push("SocietyMessageSent", { event_id: "m1", msg_type: "ASSIGN", from_agent: "ben", to_agent: "nora", room_id: "", text: "Draft the notes" });
    push("SocietyMessageSent", { event_id: "m2", msg_type: "ASSIGN", from_agent: "jarvis", to_agent: "nora", room_id: "", text: "From the lead" });
    expect(useTeamwork.getState().handoffs.map((h) => [h.id, h.from, h.to, h.toName, h.text])).toEqual([["m1", "ben", "nora", "NORA", "Draft the notes"]]);
  });

  it("keeps a board near the camera current, slowly, and a far one not at all", async () => {
    boardWatch.set(STAGE, new Set(["t2"]));
    reads.answer.set("t2", meeting(false, [["r1", "user", "Hello team"]]));
    renderHook(() => useTeamRounds(studios, roster(), true));
    const of = (id: string) => reads.calls.filter((c) => c === id).length;
    await tick();
    expect(of("t2")).toBe(1);
    expect(useTeamwork.getState().rounds.t2).toMatchObject({ loaded: true, running: false });
    expect(useTeamwork.getState().rounds.t2.lines).toHaveLength(1);
    await tick();
    await tick();
    expect(of("t2")).toBe(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(BOARD_REFRESH_MS); });
    // The near board was read again; the far team only once, by the sweep.
    expect(of("t2")).toBe(2);
    expect(of("t1")).toBe(1);
  });

  it("checks a team whose member the roster shows in a room", async () => {
    renderHook(() => useTeamRounds(studios, roster([agent("ben", "specialist", "meeting")]), true));
    reads.answer.set("t1", meeting(true, [], "ben"));
    await tick();
    expect(reads.calls[0]).toBe("t1");
    expect(useTeamwork.getState().rounds.t1).toMatchObject({ running: true, speakerId: "ben" });
  });

  it("stops showing a round it can no longer read, instead of leaving the team at the board", async () => {
    renderHook(() => useTeamRounds(studios, roster(), true));
    push("SocietyRoomChanged", { room_id: "meeting:t1:9f", phase: "open", members: ["nora", "ben"] });
    reads.answer.set("t1", new Error("HTTP 500"));
    // One failed read is a hiccup: the round stays.
    await act(async () => { await vi.advanceTimersByTimeAsync(1300); });
    expect(reads.calls.length).toBeGreaterThanOrEqual(1);
    expect(useTeamwork.getState().rounds.t1.running).toBe(true);
    // Five in a row are not.
    for (let i = 0; i < 6; i += 1) await tick();
    expect(reads.calls.length).toBeGreaterThanOrEqual(5);
    expect(useTeamwork.getState().rounds.t1.running).toBe(false);
  });

  it("is silent while the stage sleeps: no reads, no feed", async () => {
    boardWatch.set(STAGE, new Set(["t1", "t2"]));
    const view = renderHook(({ awake }) => useTeamRounds(studios, roster(), awake), { initialProps: { awake: false } });
    push("SocietyRoomChanged", { room_id: "meeting:t1:9f", phase: "open", members: ["nora"] });
    push("SocietyMessageSent", { event_id: "m1", msg_type: "SAY", from_agent: "ben", to_agent: "nora", room_id: "", text: "hi" });
    await tick();
    await tick();
    expect(reads.calls).toEqual([]);
    expect(useTeamwork.getState().rounds).toEqual({});
    expect(useTeamwork.getState().handoffs).toEqual([]);
    // Awake again: the boards in view are read, and nothing that happened meanwhile is replayed.
    view.rerender({ awake: true });
    await tick();
    expect([...reads.calls].sort()).toEqual(["t1", "t2"]);
    expect(useTeamwork.getState().handoffs).toEqual([]);
  });

  it("forgets the rounds of a team that was deleted", async () => {
    const view = renderHook(({ list }) => useTeamRounds(list, roster(), true), { initialProps: { list: studios } });
    push("SocietyRoomChanged", { room_id: "meeting:t1:9f", phase: "open", members: ["nora"] });
    expect(Object.keys(useTeamwork.getState().rounds)).toEqual(["t1"]);
    view.rerender({ list: [studios[0], studios[2]] });
    expect(useTeamwork.getState().rounds).toEqual({});
  });
});

describe("reads that go wrong", () => {
  it("gives a hanging read up after its timeout and keeps ticking meanwhile", async () => {
    reads.answer.set("t1", HANGS);
    reads.answer.set("t2", meeting(true, [], "nora"));
    renderHook(() => useTeamRounds(studios, roster(), true));
    await tick();
    // The team that answered is known at once: nobody waits for the read that hangs.
    expect(useTeamwork.getState().rounds.t2).toMatchObject({ running: true, speakerId: "nora" });
    expect(useTeamwork.getState().rounds.t1).toBeUndefined();
    // The next ticks come on time and follow the running round; the hanging team is not asked again meanwhile.
    await tick();
    await tick();
    expect(reads.calls.filter((c) => c === "t2").length).toBeGreaterThanOrEqual(3);
    expect(reads.calls.filter((c) => c === "t1")).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS); });
    // After its timeout the hanging read was aborted and counted as failed.
    expect(reads.signals[reads.calls.indexOf("t1")]?.aborted).toBe(true);
    expect(useTeamwork.getState().rounds.t1).toMatchObject({ loaded: false, unavailable: true });
    // And the loop goes on: the running round is read again on the following ticks.
    const before = reads.calls.filter((c) => c === "t2").length;
    reads.answer.set("t1", meeting(false));
    for (let i = 0; i < 4; i += 1) await tick();
    expect(reads.calls.filter((c) => c === "t2").length).toBeGreaterThan(before);
  });

  it("aborts the reads in flight when the stage goes to sleep, and writes nothing afterwards", async () => {
    reads.answer.set("t1", HANGS);
    reads.answer.set("t2", HANGS);
    const view = renderHook(({ awake }) => useTeamRounds(studios, roster(), awake), { initialProps: { awake: true } });
    await tick();
    expect(reads.signals).toHaveLength(2);
    expect(reads.signals.every((s) => s && !s.aborted)).toBe(true);
    view.rerender({ awake: false });
    expect(reads.signals.every((s) => s?.aborted)).toBe(true);
    await act(async () => { await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS * 2); });
    expect(useTeamwork.getState().rounds).toEqual({});
    expect(reads.calls).toHaveLength(2);
  });

  it("says a team whose chat was never read is unavailable, and keeps what was read before a failure", () => {
    expect(afterFailedRead(undefined, "t", 1, 500)).toMatchObject({ teamId: "t", loaded: false, unavailable: true, fetchedMs: 500, running: false });
    const known = { ...emptyRound("t"), loaded: true, running: true, speakerId: "nora", lines: [{ id: "e1", speaker: "nora", text: "hi" }] };
    expect(afterFailedRead(known, "t", 1, 500)).toMatchObject({ running: true, speakerId: "nora", unavailable: true, lines: known.lines });
    expect(afterFailedRead(known, "t", MAX_FAILED_READS, 500)).toMatchObject({ running: false, speakerId: null, lines: known.lines });
  });

  it("clears the unavailable mark with the next good read", async () => {
    reads.answer.set("t1", new Error("HTTP 500"));
    renderHook(() => useTeamRounds(studios, roster(), true));
    await tick();
    expect(useTeamwork.getState().rounds.t1.unavailable).toBe(true);
    reads.answer.set("t1", meeting(false, [["r1", "user", "Hello"]]));
    await act(async () => { await vi.advanceTimersByTimeAsync(SWEEP_MS * 1.2); });
    expect(useTeamwork.getState().rounds.t1).toMatchObject({ loaded: true, unavailable: false });
  });
});

describe("one poller for the whole app", () => {
  it("reads once when two floors are awake at the same time, and the second takes over when the first sleeps", async () => {
    const first = renderHook(({ awake }) => useTeamRounds(studios, roster(), awake), { initialProps: { awake: true } });
    renderHook(() => useTeamRounds(studios, roster(), true));
    await tick();
    // Two teams, read once each: not once per floor.
    expect([...reads.calls].sort()).toEqual(["t1", "t2"]);
    push("SocietyMessageSent", { event_id: "m1", msg_type: "ASSIGN", from_agent: "ben", to_agent: "nora", room_id: "", text: "Draft the notes" });
    expect(useTeamwork.getState().handoffs).toHaveLength(1);

    first.rerender({ awake: false });
    reads.answer.set("t1", meeting(true, [], "ben"));
    push("SocietyRoomChanged", { room_id: "meeting:t1:9f", phase: "open", members: ["nora", "ben"] });
    expect(useTeamwork.getState().rounds.t1.running).toBe(true);
    await tick();
    await tick();
    expect(useTeamwork.getState().rounds.t1).toMatchObject({ running: true, speakerId: "ben", loaded: true });
  });

  it("clears out messages whose time has passed on a floor without any team", async () => {
    renderHook(() => useTeamRounds([studio(null, ["kai", "nora", "ben"])], roster(), true));
    push("SocietyMessageSent", { event_id: "m1", msg_type: "SAY", from_agent: "ben", to_agent: "nora", room_id: "", text: "Got a minute?" });
    expect(useTeamwork.getState().handoffs).toHaveLength(1);
    await act(async () => { await vi.advanceTimersByTimeAsync(95_000); });
    expect(useTeamwork.getState().handoffs).toEqual([]);
    expect(reads.calls).toEqual([]);
  });
});

describe("the boards a camera is near", () => {
  it("are kept per floor: one floor leaving does not blind the other", () => {
    const a = Symbol("a"), b = Symbol("b");
    boardWatch.set(a, new Set(["t1"]));
    boardWatch.set(b, new Set(["t2"]));
    expect([...boardWatch.near()].sort()).toEqual(["t1", "t2"]);
    boardWatch.clear(a);
    expect([...boardWatch.near()]).toEqual(["t2"]);
    boardWatch.set(b, new Set());
    expect(boardWatch.near().size).toBe(0);
  });
});
