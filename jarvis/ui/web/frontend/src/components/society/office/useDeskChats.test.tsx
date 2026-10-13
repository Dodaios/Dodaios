import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { act, cleanup, renderHook } from "@testing-library/react";
import { READ_TIMEOUT_MS, readSignal, withReadSignal } from "./pollSignal";
import { MAX_PER_TICK, dueDesks, keptChats, useDeskChats, type DeskChat } from "./useDeskChats";
import { seatedAtDesk } from "./walkerRegistry";

const reads = vi.hoisted(() => ({ calls: [] as string[], signals: [] as (AbortSignal | undefined)[], hang: new Set<string>(), fail: new Set<string>(), seq: 0 }));
vi.mock("@/lib/agentChatApi", () => ({
  fetchAgentChatSession: (sessionId: string, options: { tail?: number; signal?: AbortSignal } = {}) => {
    reads.calls.push(sessionId);
    reads.signals.push(options.signal);
    if (reads.hang.has(sessionId)) return new Promise(() => undefined);
    if (reads.fail.has(sessionId)) return Promise.reject(new Error("HTTP 500"));
    reads.seq += 1;
    return Promise.resolve({ session: {}, events: [{ seq: reads.seq, kind: "assistant_text", payload: { text: `line ${reads.seq} of ${sessionId}` } }] });
  },
}));

const sessionsFor = (count: number) => new Map(Array.from({ length: count }, (_, i) => [`a${i}`, `s${i}`] as const));
/** One scheduler tick, with the jitter pinned to its middle: the first after 0.6 s, then one every 3.1 s. */
const tick = async () => { await act(async () => { await vi.advanceTimersByTimeAsync(3100); }); };

beforeEach(() => {
  vi.useFakeTimers();
  vi.spyOn(Math, "random").mockReturnValue(0.5);
  vi.spyOn(console, "debug").mockImplementation(() => undefined);
  reads.calls.length = 0; reads.signals.length = 0; reads.hang.clear(); reads.fail.clear(); reads.seq = 0;
  seatedAtDesk.clear();
});

afterEach(() => {
  cleanup();
  seatedAtDesk.clear();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("which desks are read on a tick", () => {
  it("takes the longest unread first, never more than the cap, and only agents with a chat", () => {
    const sessions = sessionsFor(9);
    const seated = [...sessions.keys(), "no-session"];
    const first = dueDesks(seated, sessions, new Map());
    expect(first).toEqual(["a0", "a1", "a2", "a3", "a4", "a5"]);
    expect(first).toHaveLength(MAX_PER_TICK);
    // Those six were just read: the next tick belongs to the three that were not, then the oldest again.
    const lastRead = new Map<string, number>(first.map((id) => [id, 1000] as const));
    expect(dueDesks(seated, sessions, lastRead)).toEqual(["a6", "a7", "a8", "a0", "a1", "a2"]);
    lastRead.set("a6", 2000).set("a7", 2000).set("a8", 2000).set("a0", 2000).set("a1", 2000).set("a2", 2000);
    expect(dueDesks(seated, sessions, lastRead)).toEqual(["a3", "a4", "a5", "a0", "a1", "a2"]);
    // A read still under way is not asked again and takes one of the six places.
    expect(dueDesks(seated, sessions, lastRead, new Set(["a3", "a4"]))).toEqual(["a5", "a0", "a1", "a2"]);
    expect(dueDesks(seated, sessions, lastRead, new Set(first))).toEqual([]);
  });

  it("forgets the chats of agents that left, and keeps the same map when nobody did", () => {
    const chat: DeskChat = { lines: [], version: "1:1" };
    const chats = new Map([["a0", chat], ["a1", chat], ["gone", chat]]);
    const kept = keptChats(chats, sessionsFor(2));
    expect([...kept.keys()]).toEqual(["a0", "a1"]);
    expect(keptChats(kept, sessionsFor(2))).toBe(kept);
  });
});

describe("useDeskChats", () => {
  it("gives every seated agent its turn on a floor with more of them than one tick reads", async () => {
    const sessions = sessionsFor(14);
    for (const id of sessions.keys()) seatedAtDesk.add(id);
    const view = renderHook(() => useDeskChats(sessions, true));
    await tick();
    expect(reads.calls).toHaveLength(MAX_PER_TICK);
    await tick();
    await tick();
    // Three ticks, eighteen reads, and all fourteen monitors have something to show.
    expect(new Set(reads.calls).size).toBe(14);
    expect(view.result.current.size).toBe(14);
    expect(view.result.current.get("a13")?.lines[0].text).toContain("s13");
  });

  it("is not frozen by a read that never answers, and does not let it keep its place in every tick", async () => {
    const sessions = sessionsFor(8);
    for (const id of sessions.keys()) seatedAtDesk.add(id);
    reads.hang.add("s0");
    const view = renderHook(() => useDeskChats(sessions, true));
    await tick();
    expect(reads.calls).toContain("s0");
    // The five that answered are on their monitors at once: nobody waits for the one that hangs.
    expect(view.result.current.size).toBe(5);
    await tick();
    // The next tick came on time, read the two left over, and did not ask the hanging session again.
    expect(view.result.current.size).toBe(7);
    expect(view.result.current.has("a0")).toBe(false);
    expect(reads.calls.filter((c) => c === "s0")).toHaveLength(1);
    expect(reads.signals[0]?.aborted).toBe(false);
    // After its timeout the hanging read is given up, and only then tried again.
    await act(async () => { await vi.advanceTimersByTimeAsync(READ_TIMEOUT_MS); });
    expect(reads.signals[0]?.aborted).toBe(true);
    await tick();
    expect(reads.calls.filter((c) => c === "s0").length).toBeGreaterThanOrEqual(2);
  });

  it("aborts what is in flight when the stage sleeps, and drops the chat of an agent that left", async () => {
    const sessions = sessionsFor(3);
    for (const id of sessions.keys()) seatedAtDesk.add(id);
    const view = renderHook(({ list, awake }) => useDeskChats(list, awake), { initialProps: { list: sessions as ReadonlyMap<string, string>, awake: true } });
    await tick();
    expect(view.result.current.size).toBe(3);
    reads.hang.add("s1");
    await tick();
    const hanging = reads.signals[reads.calls.lastIndexOf("s1")];
    expect(hanging?.aborted).toBe(false);
    view.rerender({ list: sessions, awake: false });
    expect(hanging?.aborted).toBe(true);
    const calls = reads.calls.length;
    await act(async () => { await vi.advanceTimersByTimeAsync(20_000); });
    expect(reads.calls).toHaveLength(calls);
    // An agent leaves the roster: its chat goes with it.
    view.rerender({ list: sessionsFor(2), awake: false });
    expect([...view.result.current.keys()].sort()).toEqual(["a0", "a1"]);
  });
});

describe("a read's signal", () => {
  it("aborts with its parent or after its time, whichever comes first", () => {
    const parent = new AbortController();
    const first = readSignal(parent.signal, 1000);
    expect(first.signal.aborted).toBe(false);
    parent.abort();
    expect(first.signal.aborted).toBe(true);
    const other = new AbortController();
    const second = readSignal(other.signal, 1000);
    vi.advanceTimersByTime(999);
    expect(second.signal.aborted).toBe(false);
    vi.advanceTimersByTime(1);
    expect(second.signal.aborted).toBe(true);
    // Settled in time: the timer is gone and nothing aborts later.
    const third = readSignal(other.signal, 1000);
    third.done();
    vi.advanceTimersByTime(5000);
    expect(third.signal.aborted).toBe(false);
    // A parent that is already aborted aborts the read at once.
    expect(readSignal(parent.signal).signal.aborted).toBe(true);
  });

  it("rejects a read that ignores its signal once the time is up, and passes a good one through", async () => {
    const parent = new AbortController();
    const stuck = withReadSignal(parent.signal, () => new Promise<number>(() => undefined), 1000);
    const outcome = stuck.then(() => "resolved", (error: Error) => error.message);
    await vi.advanceTimersByTimeAsync(1000);
    expect(await outcome).toBe("read timed out");
    await expect(withReadSignal(parent.signal, () => Promise.resolve(7), 1000)).resolves.toBe(7);
    await expect(withReadSignal(parent.signal, () => Promise.reject(new Error("HTTP 500")), 1000)).rejects.toThrow("HTTP 500");
    const cancelled = withReadSignal(parent.signal, () => new Promise<number>(() => undefined), 1000).then(() => "resolved", (error: Error) => error.message);
    parent.abort();
    expect(await cancelled).toBe("read cancelled");
  });
});
