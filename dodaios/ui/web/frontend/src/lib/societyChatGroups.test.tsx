import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider, focusManager } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { nextPollIn, useSocietyChatGroups, useSocietyMeeting } from "./societyChatGroups";

describe("when a polled query is due again", () => {
  const PERIOD = 10_000;

  it("keeps the period on average but never the same phase: half to one and a half periods", () => {
    const waits = Array.from({ length: 400 }, (_, i) => nextPollIn(1_700_000_000_000 + i * 37, PERIOD, 1_700_000_000_000 + i * 37));
    expect(Math.min(...waits)).toBeGreaterThanOrEqual(PERIOD / 2);
    expect(Math.max(...waits)).toBeLessThan(PERIOD * 1.5);
    // Spread, not one value: answers a few milliseconds apart are due at clearly different times.
    expect(new Set(waits).size).toBeGreaterThan(300);
    const mean = waits.reduce((sum, w) => sum + w, 0) / waits.length;
    expect(Math.abs(mean - PERIOD)).toBeLessThan(PERIOD * 0.1);
  });

  it("gives every watcher of one query the same moment, so their requests fold into one", () => {
    const answered = 1_700_000_123_456;
    const dueFor = (askedAt: number) => askedAt + nextPollIn(answered, PERIOD, askedAt);
    // Three components recompute at different times after the same answer: all are due at the same instant.
    expect(dueFor(answered + 5)).toBe(dueFor(answered + 900));
    expect(dueFor(answered + 900)).toBe(dueFor(answered + 3_000));
    expect(dueFor(answered + 3_000)).toBe(dueFor(answered + 4_700));
  });

  it("waits a whole period before the first answer, and a short beat when it is overdue", () => {
    expect(nextPollIn(0, PERIOD, 123)).toBe(PERIOD);
    const answered = 1_700_000_000_000;
    // Long overdue (a sleeping machine woke up): soon, but not a tight loop.
    expect(nextPollIn(answered, PERIOD, answered + 60_000)).toBe(250);
  });
});

describe("the society polls in a desktop window that reports itself hidden", () => {
  let client: QueryClient;
  const calls: string[] = [];
  const wrapper = ({ children }: { children: ReactNode }) => <QueryClientProvider client={client}>{children}</QueryClientProvider>;

  beforeEach(() => {
    calls.length = 0;
    client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    vi.stubGlobal("fetch", async (url: string) => {
      calls.push(url);
      return new Response(JSON.stringify(url.endsWith("/meeting") ? { messages: [], running: true, room: null } : { groups: [] }));
    });
    // What the desktop WebView tells the page about a window the person is looking at.
    focusManager.setFocused(false);
  });
  afterEach(() => {
    cleanup();
    client.clear();
    focusManager.setFocused(undefined);
    vi.unstubAllGlobals();
    vi.useRealTimers();
  });

  const observerOptions = (key: readonly unknown[]) => client.getQueryCache().find({ queryKey: key })!.observers[0]!.options;

  it("keeps refreshing the team list: jittered, and not paused by document visibility", async () => {
    const view = renderHook(() => useSocietyChatGroups(true), { wrapper });
    await waitFor(() => expect(view.result.current.isSuccess).toBe(true));
    const options = observerOptions(["society", "chat-groups"]);
    expect(options.refetchIntervalInBackground).toBe(true);
    expect(typeof options.refetchInterval).toBe("function");
    const query = client.getQueryCache().find({ queryKey: ["society", "chat-groups"] })!;
    const wait = (options.refetchInterval as (q: typeof query) => number)(query);
    expect(wait).toBeGreaterThan(4_000);
    expect(wait).toBeLessThanOrEqual(15_000);
  });

  it("really fetches again while hidden, and stays quiet while its caller is off", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const view = renderHook(({ on }) => useSocietyChatGroups(on), { wrapper, initialProps: { on: true } });
    await waitFor(() => expect(calls).toHaveLength(1));
    await vi.advanceTimersByTimeAsync(16_000);
    expect(calls.length).toBeGreaterThanOrEqual(2);
    // A sleeping stage passes `enabled: false`: nothing more is asked.
    view.rerender({ on: false });
    const asked = calls.length;
    await vi.advanceTimersByTimeAsync(40_000);
    expect(calls).toHaveLength(asked);
  });

  it("follows a running round the same way", async () => {
    const view = renderHook(() => useSocietyMeeting("g1"), { wrapper });
    await waitFor(() => expect(view.result.current.data?.running).toBe(true));
    const options = observerOptions(["society", "meeting", "g1"]);
    expect(options.refetchIntervalInBackground).toBe(true);
    const query = client.getQueryCache().find({ queryKey: ["society", "meeting", "g1"] })!;
    const wait = (options.refetchInterval as (q: typeof query) => number | false)(query);
    expect(wait).toBeGreaterThan(700);
    expect(wait).toBeLessThanOrEqual(3_000);
    // No round, no poll.
    query.setData({ messages: [], running: false, room: null });
    expect((options.refetchInterval as (q: typeof query) => number | false)(query)).toBe(false);
  });
});
