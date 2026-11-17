import { describe, expect, it } from "vitest";
import type { SessionGitHubStatus } from "../useSessionGitHub";
import { boardVerdict, gitHubSettled, sortBoardItems, type BoardActivity } from "./agentBoard";

function github(overrides: Partial<SessionGitHubStatus> = {}): SessionGitHubStatus {
  return {
    repo: "owner/repo", branch: "feat/login", url: "https://github.com/owner/repo/pull/7",
    owned: true, published: true, available: true, reason: "", fetched_at: 1, state: "open", number: 7,
    ci_stale: false, merge_status: "blocked", review: "",
    ci: { state: "success", url: "", total: 1, passed: 1, failed: 0, pending: 0, running: 0, names: [], commit: "" },
    ...overrides,
  };
}

const ci = (state: SessionGitHubStatus["ci"]["state"]) => ({ ...github().ci, state });

function verdict(status: SessionGitHubStatus | null, activity: BoardActivity = "idle", news = false) {
  return boardVerdict({ activity, activityKey: `status.${activity}`, news, status });
}

describe("boardVerdict", () => {
  it("keeps work without a pull request under Building and names its branch", () => {
    const none = verdict(null);
    expect(none).toMatchObject({ place: "building", label: "status.idle", tone: "quiet", branch: "" });
    const branch = verdict(github({ state: "branch", number: null }), "working");
    expect(branch).toMatchObject({ place: "building", label: "status.working", tone: "building", spin: true, branch: "feat/login" });
    expect(branch.requests).toEqual([]);
  });

  it("does not name a branch the session only happens to stand on, nor the main line", () => {
    expect(verdict(github({ state: "branch", number: null, owned: false })).branch).toBe("");
    expect(verdict(github({ state: "branch", number: null, branch: "main" })).branch).toBe("");
  });

  it("marks a resting agent with news in its column's colour", () => {
    expect(verdict(null, "idle", true).tone).toBe("building");
  });

  it("keeps a draft under Building", () => {
    expect(verdict(github({ state: "draft" }))).toMatchObject({ place: "building", label: "status.draft", tone: "quiet", branch: "" });
  });

  it("puts running and failed checks, and a merge conflict, under Checks", () => {
    expect(verdict(github({ ci: ci("running") }))).toMatchObject({ place: "checks", label: "status.checks_running", tone: "checks" });
    expect(verdict(github({ ci: ci("pending") })).place).toBe("checks");
    expect(verdict(github({ ci: ci("failure") }))).toMatchObject({ place: "checks", label: "status.checks_failed", tone: "danger" });
    expect(verdict(github({ merge_status: "dirty" }))).toMatchObject({ place: "checks", label: "status.conflicts", tone: "danger" });
  });

  it("puts a pull request with green or no checks under In review", () => {
    expect(verdict(github())).toMatchObject({ place: "review", label: "status.awaiting_review", tone: "review" });
    expect(verdict(github({ ci: ci("none") })).place).toBe("review");
    expect(verdict(github({ review: "changes_requested" }))).toMatchObject({ place: "review", label: "status.changes_requested", tone: "attention" });
  });

  it("puts a mergeable, approved or queued pull request under Ready", () => {
    expect(verdict(github({ merge_status: "clean" }))).toMatchObject({ place: "ready", label: "status.mergeable", tone: "ready" });
    expect(verdict(github({ review: "approved" })).place).toBe("ready");
    expect(verdict(github({ state: "queued" }))).toMatchObject({ place: "ready", label: "status.queued" });
  });

  it("does not read checks or reviews from a status that could not be refreshed", () => {
    expect(verdict(github({ available: false, merge_status: "clean", ci: ci("failure") }))).toMatchObject({
      place: "review", label: "status.awaiting_review",
    });
  });

  it("folds work whose pull requests are merged or closed into Finished", () => {
    expect(verdict(github({ state: "merged" }))).toMatchObject({ place: "finished", label: "status.merged", tone: "merged" });
    expect(verdict(github({ state: "closed" }))).toMatchObject({ place: "finished", label: "status.closed", tone: "quiet" });
  });

  it("brings finished work back to Building while its agent works or asks again", () => {
    expect(verdict(github({ state: "merged" }), "working")).toMatchObject({ place: "building", label: "status.working", tone: "building" });
    expect(verdict(github({ state: "merged" }), "attention")).toMatchObject({ place: "building", tone: "attention" });
  });

  it("goes by the open pull request when an older one is already merged", () => {
    const status = github({ state: "merged", number: 3, others: [github({ number: 9, ci: ci("running") })] });
    const read = verdict(status);
    expect(read.place).toBe("checks");
    expect(read.requests.map((request) => request.number)).toEqual([9, 3]);
  });

  it("says what the agent does before what the pull request waits for", () => {
    expect(verdict(github(), "working")).toMatchObject({ place: "review", label: "status.working", tone: "review", spin: true });
    expect(verdict(github({ ci: ci("failure") }), "working")).toMatchObject({ place: "checks", label: "status.working", tone: "checks" });
    expect(verdict(github({ merge_status: "clean" }), "attention")).toMatchObject({ place: "ready", label: "status.attention", tone: "attention" });
    expect(verdict(github(), "failed")).toMatchObject({ place: "review", label: "status.failed", tone: "danger" });
  });
});

describe("sortBoardItems", () => {
  it("leads with what asks for the person, then work, then news, then the newest", () => {
    const item = (id: string, activity: BoardActivity, atMs: number, news = false) => ({ id, activity, atMs, news });
    const sorted = sortBoardItems([
      item("old", "idle", 1), item("new", "idle", 9), item("news", "idle", 2, true),
      item("work", "working", 3), item("ask", "attention", 0), item("fail", "failed", 5),
    ]);
    expect(sorted.map((entry) => entry.id)).toEqual(["ask", "fail", "work", "news", "new", "old"]);
  });
});

describe("gitHubSettled", () => {
  const rest = { running: false, waiting: false, updatedMs: 100 };

  it("is settled once every pull request is finished and the thread has not moved since", () => {
    expect(gitHubSettled(rest, { answered: true, readAt: 200, status: github({ state: "merged" }) })).toBe(true);
    expect(gitHubSettled(rest, { answered: true, readAt: 200, status: null })).toBe(true);
    expect(gitHubSettled(rest, { answered: true, readAt: 200, status: github({ state: "branch", number: null }) })).toBe(true);
  });

  it("keeps following an open pull request, a thread at work and one that moved since the read", () => {
    expect(gitHubSettled(rest, { answered: true, readAt: 200, status: github() })).toBe(false);
    expect(gitHubSettled(rest, { answered: true, readAt: 200, status: github({ state: "merged", others: [github({ state: "draft" })] }) })).toBe(false);
    expect(gitHubSettled({ ...rest, running: true }, { answered: true, readAt: 200, status: null })).toBe(false);
    expect(gitHubSettled({ ...rest, waiting: true }, { answered: true, readAt: 200, status: null })).toBe(false);
    expect(gitHubSettled({ ...rest, updatedMs: 300 }, { answered: true, readAt: 200, status: null })).toBe(false);
  });

  it("is not settled before the backend has answered", () => {
    expect(gitHubSettled(rest, undefined)).toBe(false);
    expect(gitHubSettled(rest, { answered: false, readAt: null, status: null })).toBe(false);
  });
});
