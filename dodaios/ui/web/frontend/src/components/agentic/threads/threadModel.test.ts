import { afterEach, describe, expect, it, vi } from "vitest";
import type { AgentChatSession } from "@/lib/agentChatApi";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { createAgentChatStore } from "@/store/agentChat";
import { comparablePath, compactTitle, isInside, projectIdFor, shortAge, threadDayBreak, threadStatus, threadTitle, threadWorktree, threadsByProject, useThreadChatStore } from "./threadModel";

function project(id: string, path: string): IdeProject {
  return {
    id, path, name: id, color: null, pinned: false, archived: false, created_at: 0, last_opened_at: 0,
    exists: true, chats: 0, scratch: false, workspaces: [],
  } as IdeProject;
}

function session(id: string, cwd: string, extra: Partial<AgentChatSession> = {}): AgentChatSession {
  return {
    session_id: id, title: `title ${id}`, provider: "claude-api", model: "", effort: "", cwd, permission_mode: "",
    vendor_session: null, created_ms: 0, updated_ms: 0, message_count: 1, preview: "", ...extra,
  };
}

describe("thread paths", () => {
  it("compares Windows paths without case or separator drift", () => {
    expect(comparablePath("C:\\Users\\Me\\Repo\\")).toBe("c:/users/me/repo");
    expect(isInside("c:/users/me/repo/sub", "C:\\Users\\Me\\Repo")).toBe(true);
  });

  it("keeps POSIX paths case-sensitive and never matches a sibling prefix", () => {
    expect(isInside("/home/me/Repo", "/home/me/repo")).toBe(false);
    expect(isInside("/home/me/repo-two", "/home/me/repo")).toBe(false);
    expect(isInside("/home/me/repo", "/home/me/repo/")).toBe(true);
  });
});

describe("projectIdFor", () => {
  const projects = [project("outer", "/code"), project("inner", "/code/app")];

  it("picks the deepest project that holds the thread's folder", () => {
    expect(projectIdFor(session("a", "/code/app/src"), projects, {})).toBe("inner");
    expect(projectIdFor(session("b", "/code/lib"), projects, {})).toBe("outer");
    expect(projectIdFor(session("c", "/elsewhere"), projects, {})).toBeNull();
  });

  it("prefers the project a thread was started in (a worktree lives outside it)", () => {
    expect(projectIdFor(session("w", "/worktrees/app-fix"), projects, { w: "inner" })).toBe("inner");
    // A remembered project that is gone falls back to the folder.
    expect(projectIdFor(session("x", "/code/lib"), projects, { x: "deleted" })).toBe("outer");
  });

  it("groups threads per project, newest first", () => {
    const grouped = threadsByProject([
      session("old", "/code/app", { updated_ms: 1 }),
      session("new", "/code/app", { updated_ms: 5 }),
      session("stray", "/tmp"),
    ], projects, {});
    expect(grouped.get("inner")?.map((row) => row.session_id)).toEqual(["new", "old"]);
    expect([...grouped.keys()]).toEqual(["inner"]);
  });

  it("orders by the last message, so a working thread's tool calls never move it", () => {
    const projects = [project("app", "/code/app")];
    const grouped = threadsByProject([
      session("asked-first-still-working", "/code/app", { last_message_ms: 10, updated_ms: 99 }),
      session("asked-last", "/code/app", { last_message_ms: 20, updated_ms: 21 }),
      session("old-backend", "/code/app", { updated_ms: 15 }),
    ], projects, {});
    expect(grouped.get("app")?.map((row) => row.session_id)).toEqual(["asked-last", "old-backend", "asked-first-still-working"]);
  });
});

describe("threadStatus", () => {
  it("puts an open question first, then a waiting approval, then work, then news", () => {
    const base = session("s", "/code", { updated_ms: 10 });
    expect(threadStatus({ ...base, running: true, pending_questions: ["q"], pending_approvals: ["a"] }, {}, null)).toBe("question");
    expect(threadStatus({ ...base, running: true, pending_questions: [] }, {}, null)).toBe("running");
    expect(threadStatus({ ...base, running: true, pending_approvals: ["a"] }, {}, null)).toBe("approval");
    expect(threadStatus({ ...base, running: true }, {}, null)).toBe("running");
    expect(threadStatus(base, { s: 5 }, null)).toBe("unseen");
    expect(threadStatus(base, { s: 5 }, "s")).toBe("idle");
    // Never looked at in this browser: not news.
    expect(threadStatus(base, {}, null)).toBe("idle");
  });
});

describe("threadTitle", () => {
  it("uses the CLI's own title first, then the stored one", () => {
    expect(threadTitle({ title: "fix the login test please", cli_title: "Fix login test" })).toBe("Fix login test");
    expect(threadTitle({ title: "fix the login test please" })).toBe("fix the login test please");
    expect(threadTitle({ title: "  " })).toBe("New thread");
    expect(threadTitle(null)).toBe("New thread");
  });
});

describe("shortAge", () => {
  it("says how long ago in a list's shorthand", () => {
    const now = 1_000_000_000;
    expect(shortAge(now - 10_000, now)).toBe("now");
    expect(shortAge(now - 5 * 60_000, now)).toBe("5m");
    expect(shortAge(now - 3 * 3_600_000, now)).toBe("3h");
    expect(shortAge(now - 2 * 86_400_000, now)).toBe("2d");
    expect(shortAge(now - 15 * 86_400_000, now)).toBe("2w");
  });
});

describe("threadDayBreak", () => {
  const at = (day: number, hour: number) => new Date(2026, 10, day, hour).getTime();
  const now = at(12, 9);

  it("leaves today's rows at the top of the list without a heading", () => {
    expect(threadDayBreak(at(12, 8), null, "en-US", now)).toBeNull();
    expect(threadDayBreak(at(12, 0), at(12, 8), "en-US", now)).toBeNull();
  });

  it("names the day where the list crosses into an earlier one", () => {
    expect(threadDayBreak(at(11, 23), at(12, 0), "en-US", now)).toBe("Yesterday");
    expect(threadDayBreak(at(11, 1), at(11, 23), "en-US", now)).toBeNull();
    expect(threadDayBreak(at(10, 22), at(11, 1), "en-US", now)).toBe("Tue, Nov 10");
    expect(threadDayBreak(at(10, 22), at(11, 1), "de-DE", now)).toMatch(/^Di\.?, 10\. Nov\.?$/);
    expect(threadDayBreak(at(11, 23), at(12, 0), "de-DE", now)).toBe("Gestern");
  });

  it("names the first row's day when nothing happened today", () => {
    expect(threadDayBreak(at(11, 23), null, "en-US", now)).toBe("Yesterday");
  });

  it("files a thread under the day of its last activity, not the day it started", () => {
    // Started on the 10th, still working on the 12th: it stands with today's rows.
    expect(threadDayBreak(at(12, 3), null, "en-US", now)).toBeNull();
  });

  it("adds the year to a day from another year", () => {
    expect(threadDayBreak(new Date(2025, 11, 30, 12).getTime(), at(1, 12), "en-US", now)).toBe("Tue, Dec 30, 2025");
  });
});

describe("compactTitle", () => {
  it("turns GitHub issue and pull request links into short references", () => {
    expect(compactTitle("Https://github.com/Dodaios/Dodaios/issues/1189 what is this")).toBe("Issue #1189 what is this");
    expect(compactTitle("https://github.com/Dodaios/Dodaios/pull/1191 review please")).toBe("PR #1191 review please");
  });

  it("keeps only the host of any other link and leaves plain titles alone", () => {
    expect(compactTitle("look at https://example.com/a/b?c=1   now")).toBe("look at example.com now");
    expect(compactTitle("GitHub main is red")).toBe("GitHub main is red");
  });
});

describe("threadWorktree", () => {
  it("names the worktree a thread works in", () => {
    expect(threadWorktree("C:\\Repo\\.worktrees\\Fix-Login", "C:\\repo")).toBe("Fix-Login");
    expect(threadWorktree("/home/a/repo/.claude/worktrees/agent-1/src", "/home/a/repo")).toBe("agent-1");
  });

  it("is null in the project's own checkout or outside it", () => {
    expect(threadWorktree("C:\\Repo", "C:\\repo")).toBeNull();
    expect(threadWorktree("C:\\Repo\\src", "C:\\repo")).toBeNull();
    expect(threadWorktree("C:\\Other\\.worktrees\\x", "C:\\repo")).toBeNull();
  });
});

describe("thread list row of a thread open in a side column", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("follows the side column's turn without waiting for the list poll", () => {
    // The list route never answers in time here: only the side column's
    // store can tell the thread list its turn started and ended.
    vi.stubGlobal("fetch", vi.fn(async () => { throw new TypeError("offline"); }));
    vi.stubGlobal("WebSocket", class { close() {} });
    const row = session("side-thread", "C:\\work", { running: false });
    useThreadChatStore.setState({ sessions: [row], activeSessionId: null });
    void useThreadChatStore.getState().loadSessions();
    const side = createAgentChatStore("agent", "threads-side");
    side.setState({ sessions: [row] });
    side.getState().openSession("side-thread");
    const listed = () => useThreadChatStore.getState().sessions[0];
    side.getState().ingest({ seq: 1, ts_ms: Date.now(), kind: "turn_started", payload: { turn_id: "t1" } });
    expect(threadStatus(listed(), {}, null)).toBe("running");
    side.getState().ingest({ seq: 2, ts_ms: Date.now(), kind: "turn_finished", payload: { turn_id: "t1", status: "done" } });
    expect(threadStatus(listed(), {}, null)).toBe("idle");
    side.getState().disconnect();
  });
});
