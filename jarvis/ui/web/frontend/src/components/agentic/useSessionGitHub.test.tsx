import { act, cleanup, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { useSessionGitHub, type SessionGitHubStatus } from "./useSessionGitHub";
import { resetConnectBudgetForTests } from "@/lib/connectBudget";

const value: SessionGitHubStatus = {
  repo: "owner/repo", branch: "feature/a", url: "https://github.com/owner/repo/tree/feature/a",
  owned: true, published: true, available: true, reason: "", fetched_at: 1, state: "open", number: 1,
  ci_stale: false, ci: { state: "none", url: "", total: 0, passed: 0, failed: 0, pending: 0, running: 0, names: [], commit: "" },
};

beforeEach(() => {
  vi.useFakeTimers();
  resetConnectBudgetForTests();
  vi.spyOn(Math, "random").mockReturnValue(0.5);
  vi.spyOn(document, "hidden", "get").mockReturnValue(false);
});
afterEach(() => {
  cleanup();
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

it("answers with what is known and asks again while a newer answer is read", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ panes: {}, refreshing: true }) });
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(() => useSessionGitHub("reading", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(300));
  expect(fetcher).toHaveBeenCalledTimes(1);
  expect(hook.result.current).toBeNull();
  // The follow-up comes within a second, not with the steady 20 s rhythm.
  fetcher.mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: value }, refreshing: false }) });
  await act(() => vi.advanceTimersByTimeAsync(800));
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(hook.result.current?.state).toBe("open");
  expect(hook.result.current?.refreshing).toBe(false);
  // An answer that is being brought up to date keeps its state and says so.
  fetcher.mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: { ...value, state: "merged" } }, refreshing: true }) });
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(hook.result.current?.state).toBe("merged");
  expect(hook.result.current?.refreshing).toBe(true);
});

it("keeps a pane's last known branch until the backend has read it", async () => {
  const sessions = { t1: "first" };
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: value }, refreshing: false, sessions }) });
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(() => useSessionGitHub("restarted", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(300));
  fetcher.mockResolvedValue({ ok: true, json: async () => ({ panes: {}, refreshing: true, sessions }) });
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(hook.result.current?.branch).toBe("feature/a");
  expect(hook.result.current?.refreshing).toBe(true);
  // Once the read has landed, a pane without a branch has none.
  fetcher.mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: null }, refreshing: false, sessions }) });
  await act(() => vi.advanceTimersByTimeAsync(800));
  expect(hook.result.current).toBeNull();
});

it("never shows a pane the branch of the session it ran before", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: value }, refreshing: false, sessions: { t1: "first" } }) });
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(() => useSessionGitHub("successor", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(300));
  expect(hook.result.current?.branch).toBe("feature/a");
  fetcher.mockResolvedValue({ ok: true, json: async () => ({ panes: {}, refreshing: true, sessions: { t1: "second" } }) });
  await act(() => vi.advanceTimersByTimeAsync(20_000));
  expect(hook.result.current).toBeNull();
});

it("shows a tab's branch the moment it is back on stage", async () => {
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: value }, refreshing: false }) });
  vi.stubGlobal("fetch", fetcher);
  const first = renderHook(() => useSessionGitHub("tab", "t1"));
  await act(() => vi.advanceTimersByTimeAsync(300));
  first.unmount();
  fetcher.mockImplementation(() => new Promise(() => {}));
  const back = renderHook(() => useSessionGitHub("tab", "t1"));
  expect(back.result.current?.state).toBe("open");
  expect(back.result.current?.refreshing).toBe(true);
});

it("paints what was last known after the window reloaded", () => {
  sessionStorage.setItem("ide-pane-github:reloaded", JSON.stringify({ panes: { t1: value }, sessions: { t1: "first" } }));
  vi.stubGlobal("fetch", vi.fn().mockImplementation(() => new Promise(() => {})));
  const hook = renderHook(() => useSessionGitHub("reloaded", "t1"));
  expect(hook.result.current?.branch).toBe("feature/a");
  expect(hook.result.current?.refreshing).toBe(true);
});

it("stores each settled answer for the next load, and survives unreadable storage", async () => {
  sessionStorage.setItem("ide-pane-github:broken", "{not json");
  const fetcher = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ panes: { t1: value }, refreshing: false }) });
  vi.stubGlobal("fetch", fetcher);
  const hook = renderHook(() => useSessionGitHub("broken", "t1"));
  expect(hook.result.current).toBeNull();
  await act(() => vi.advanceTimersByTimeAsync(300));
  expect(hook.result.current?.state).toBe("open");
  expect(JSON.parse(sessionStorage.getItem("ide-pane-github:broken") ?? "null").panes.t1.branch).toBe("feature/a");
});
