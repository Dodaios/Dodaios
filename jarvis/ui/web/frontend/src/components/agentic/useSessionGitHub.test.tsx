import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  resetSessionGitHubForTests, useSessionGitHub, useSessionGitHubPane, type SessionGitHubStatus,
} from "./useSessionGitHub";
import { resetConnectBudgetForTests } from "@/lib/connectBudget";

const value: SessionGitHubStatus = {
  repo: "owner/repo", branch: "feature/a", url: "https://github.com/owner/repo/tree/feature/a",
  owned: true, published: true, available: true, reason: "", fetched_at: 1, state: "open", number: 1,
  ci_stale: false, ci: { state: "none", url: "", total: 0, passed: 0, failed: 0, pending: 0, running: 0, names: [], commit: "" },
};

beforeEach(() => {
  vi.useFakeTimers();
  // GitHub's answer is as recent as the test's clock.
  value.fetched_at = Date.now() / 1000;
  resetConnectBudgetForTests();
  vi.spyOn(Math, "random").mockReturnValue(0.5);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => {
  cleanup();
  resetSessionGitHubForTests();
  resetConnectBudgetForTests();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

it("shares one poll per workspace and refreshes PR/CI transitions", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: value, t2: value } }) });
  vi.stubGlobal("fetch", fetcher);
  const a = renderHook(() => useSessionGitHub("w", "t1"));
  const b = renderHook(() => useSessionGitHub("w", "t2"));
  await act(() => vi.advanceTimersByTimeAsync(300));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(a.result.current?.state).toBe("open");
  expect(b.result.current?.state).toBe("open");
  fetcher.mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: { ...value, state: "merged" } } }) });
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(a.result.current?.state).toBe("merged");
  expect(b.result.current).toBeNull();
  a.unmount(); b.unmount();
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("hides obsolete identity on a branch/workspace change and marks failed refreshes", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: value } }) });
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(({ workspace }) => useSessionGitHub(workspace, "t1"), { initialProps: { workspace: "w" } });
  await act(() => vi.advanceTimersByTimeAsync(300));
  fetcher.mockRejectedValue(new Error("offline"));
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(hook.result.current?.available).toBe(false);
  hook.rerender({ workspace: "another" });
  expect(hook.result.current).toBeNull();
});

it("pauses while hidden and resumes through the shared budget", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ panes: {} }) });
  vi.stubGlobal("fetch", fetcher);
  const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(true);
  renderHook(() => useSessionGitHub("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  expect(fetcher).not.toHaveBeenCalled();
  hidden.mockReturnValue(false);
  act(() => document.dispatchEvent(new Event("visibilitychange")));
  expect(fetcher).not.toHaveBeenCalled();
  await act(() => vi.advanceTimersByTimeAsync(600));
  expect(fetcher).toHaveBeenCalledTimes(1);
});

it("aborts an in-flight poll when its last subscriber unmounts", async () => {
  const fetcher = vi.fn().mockImplementation(() => new Promise(() => {}));
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(() => useSessionGitHub("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(300));
  const signal = fetcher.mock.calls[0][1].signal as AbortSignal;
  hook.unmount();
  expect(signal.aborted).toBe(true);
});

const answer = (body: object) => ({ ok: true, json: async () => body });

it("spins before the first answer and while the backend reads it, then shows it", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(answer({ panes: {}, refreshing: true, age: null, waiting: ["t1"] }))
    .mockResolvedValue(answer({ panes: { t1: value }, refreshing: false, age: 0, waiting: [] }));
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(() => useSessionGitHubPane("w", "t1"));
  expect(hook.result.current).toEqual({ status: null, pending: true });
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(hook.result.current).toEqual({ status: null, pending: true });
  // A read on its way is asked about again within about a second.
  await act(() => vi.advanceTimersByTimeAsync(1_500));
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(hook.result.current).toEqual({ status: value, pending: false });
});

it("stops spinning for a pane the backend reads nothing for", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer({ panes: { t1: value }, refreshing: false, age: 0 })));
  const remote = renderHook(() => useSessionGitHubPane("w", "remote"));
  expect(remote.result.current.pending).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(remote.result.current).toEqual({ status: null, pending: false });
});

it("shows a tab's last answer the moment it is visited again", async () => {
  const fetcher = vi.fn().mockResolvedValue(answer({ panes: { t1: value }, refreshing: false, age: 0 }));
  vi.stubGlobal("fetch", fetcher);
  const first = renderHook(() => useSessionGitHubPane("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(200));
  first.unmount();
  await act(() => vi.advanceTimersByTimeAsync(5_000));
  fetcher.mockClear();
  const again = renderHook(() => useSessionGitHubPane("w", "t1"));
  // Painted from memory before any request: no spinner for a recent answer.
  expect(fetcher).not.toHaveBeenCalled();
  expect(again.result.current).toEqual({ status: value, pending: false });
});

it("keeps an old answer on screen and spins until the backend confirms it", async () => {
  const fetcher = vi.fn().mockResolvedValue(answer({ panes: { t1: value }, refreshing: false, age: 0 }));
  vi.stubGlobal("fetch", fetcher);
  const first = renderHook(() => useSessionGitHubPane("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(200));
  first.unmount();
  await act(() => vi.advanceTimersByTimeAsync(120_000));
  const merged = { ...value, state: "merged" as const, fetched_at: Date.now() / 1000 };
  fetcher
    .mockResolvedValueOnce(answer({ panes: { t1: value }, refreshing: true, age: 125, waiting: [] }))
    .mockResolvedValue(answer({ panes: { t1: merged }, refreshing: false, age: 0, waiting: [] }));
  const again = renderHook(() => useSessionGitHubPane("w", "t1"));
  expect(again.result.current).toEqual({ status: value, pending: true });
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(again.result.current).toEqual({ status: value, pending: true });
  await act(() => vi.advanceTimersByTimeAsync(1_500));
  expect(again.result.current).toEqual({ status: merged, pending: false });
});

it("does not spin while a recent answer is merely being refreshed", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer({ panes: { t1: value }, refreshing: true, age: 20, waiting: [] })));
  const hook = renderHook(() => useSessionGitHubPane("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(hook.result.current).toEqual({ status: value, pending: false });
});

it("stops spinning when the status cannot be read", async () => {
  vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("offline")));
  const hook = renderHook(() => useSessionGitHubPane("w", "t1"));
  expect(hook.result.current.pending).toBe(true);
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(hook.result.current).toEqual({ status: null, pending: false });
});

it("follows a slow read up less often after a while, then returns to its rhythm", async () => {
  const fetcher = vi.fn().mockResolvedValue(answer({ panes: {}, refreshing: true, age: null, waiting: ["t1"] }));
  vi.stubGlobal("fetch", fetcher);
  renderHook(() => useSessionGitHubPane("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(60_000));
  // Thirty quick follow-ups, then one every five seconds or so.
  expect(fetcher.mock.calls.length).toBeGreaterThan(30);
  expect(fetcher.mock.calls.length).toBeLessThan(45);
  fetcher.mockClear();
  fetcher.mockResolvedValue(answer({ panes: {}, refreshing: false, age: 0 }));
  await act(() => vi.advanceTimersByTimeAsync(10_000));
  const settled = fetcher.mock.calls.length;
  await act(() => vi.advanceTimersByTimeAsync(9_000));
  expect(fetcher.mock.calls.length).toBe(settled);
});

it("stops spinning and says unavailable when the backend's reads keep failing", async () => {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer({
    panes: { t1: value }, refreshing: false, age: 600, waiting: [], failed: true,
  })));
  const hook = renderHook(() => useSessionGitHubPane("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(hook.result.current.pending).toBe(false);
  expect(hook.result.current.status?.available).toBe(false);
});

it("asks at once when a pane joins a workspace that is already being polled", async () => {
  const fetcher = vi.fn().mockResolvedValue(answer({ panes: { t1: value }, refreshing: false, age: 0 }));
  vi.stubGlobal("fetch", fetcher);
  renderHook(() => useSessionGitHubPane("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(fetcher).toHaveBeenCalledTimes(1);
  // A new pane may reuse a closed pane's name: the backend is asked well
  // before the next regular poll.
  renderHook(() => useSessionGitHubPane("w", "t2"));
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(fetcher).toHaveBeenCalledTimes(2);
});

it("spins when GitHub's own answer is old, even on a board read moments ago", async () => {
  const stale = { ...value, fetched_at: Date.now() / 1000 - 300 };
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue(answer({ panes: { t1: stale }, refreshing: true, age: 1, waiting: [] })));
  const hook = renderHook(() => useSessionGitHubPane("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(200));
  expect(hook.result.current).toEqual({ status: stale, pending: true });
});

it("asks the backend to hold a follow-up until its read lands", async () => {
  const fetcher = vi.fn()
    .mockResolvedValueOnce(answer({ panes: {}, refreshing: true, age: null, waiting: ["t1"] }))
    .mockResolvedValue(answer({ panes: { t1: value }, refreshing: false, age: 0, waiting: [] }));
  vi.stubGlobal("fetch", fetcher);
  renderHook(() => useSessionGitHubPane("w", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(400));
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(String(fetcher.mock.calls[0][0])).not.toContain("wait=");
  expect(String(fetcher.mock.calls[0][0])).toContain("instant=1");
  expect(String(fetcher.mock.calls[1][0])).toContain("wait=4");
});
