import { describe, expect, it } from "vitest";
import { attention, canCleanUp, needsPull, needsPush, nextStep, syncOf } from "./gitInsights";
import type { BranchRow, Checkout, CiStatus, PullRequest, RepoOverview } from "./gitOverviewApi";

const noCi: CiStatus = { state: "none", url: "", total: 0, passed: 0, failed: 0, running: 0, pending: 0, commit: "", names: [] };
const failed: CiStatus = { ...noCi, state: "failure", total: 3, passed: 2, failed: 1, names: ["lint"], url: "https://ci/1" };

function branch(name: string, extra: Partial<BranchRow> = {}): BranchRow {
  return {
    name,
    current: false,
    remote_only: false,
    upstream: `origin/${name}`,
    ahead: 0,
    behind: 0,
    head: "abc123def456",
    committed_at: 0,
    worktree: "",
    on_github: true,
    merged_into: [],
    pull_requests: [],
    ci: noCi,
    ci_stale: false,
    base_ahead: 1,
    base_behind: 0,
    ...extra,
  };
}

function pr(number: number, extra: Partial<PullRequest> = {}): PullRequest {
  return {
    number,
    title: `Change ${number}`,
    url: `https://github.com/o/r/pull/${number}`,
    state: "open",
    base: "main",
    head: "feature/x",
    head_oid: "",
    merged_at: "",
    updated_at: "",
    queue_position: null,
    ci: noCi,
    ...extra,
  };
}

const CLEAN: Checkout = {
  branch: "feature/x",
  detached: false,
  unborn: false,
  head: "abc123def456",
  upstream: "origin/feature/x",
  ahead: 0,
  behind: 0,
  files: 0,
  staged: 0,
  unstaged: 0,
  untracked: 0,
  conflicted: 0,
  operation: "",
  stashes: 0,
  last_fetch: 1,
  has_remote: true,
};

function overview(checkout: Partial<Checkout> = {}, current: Partial<BranchRow> = {}, others: BranchRow[] = []): RepoOverview {
  const state = { ...CLEAN, ...checkout };
  return {
    available: true,
    reason: "",
    root: "/code/app",
    branch: state.branch,
    detached: state.detached,
    head: state.head,
    default_branch: "main",
    truncated: false,
    github: { available: true, reason: "", code: "", repo: "o/r", suggested_repo: "", source: "app", repo_url: "https://github.com/o/r", fetched_at: 1 },
    branches: [
      branch(state.branch || "feature/x", { current: true, upstream: state.upstream, ahead: state.ahead, behind: state.behind, ...current }),
      branch("main"),
      ...others,
    ],
    remote_branches: [],
    checkout: state,
    base_ref: "origin/main",
  };
}

describe("syncOf", () => {
  it("names how a branch stands to its remote", () => {
    expect(syncOf(branch("a"))).toBe("synced");
    expect(syncOf(branch("a", { ahead: 2 }))).toBe("ahead");
    expect(syncOf(branch("a", { behind: 1 }))).toBe("behind");
    expect(syncOf(branch("a", { ahead: 2, behind: 1 }))).toBe("diverged");
    expect(syncOf(branch("a", { upstream: "", on_github: false }))).toBe("unpublished");
    expect(syncOf(branch("a", { upstream_gone: true }))).toBe("gone");
    expect(syncOf(branch("a", { remote_only: true, upstream: "" }))).toBe("remote_only");
  });

  it("counts only work of its own as needing a push", () => {
    expect(needsPush(branch("a", { ahead: 1 }))).toBe(true);
    expect(needsPush(branch("a", { upstream: "", on_github: false }))).toBe(true);
    // Just created from main: nothing of its own to lose.
    expect(needsPush(branch("a", { upstream: "", on_github: false, base_ahead: 0 }))).toBe(false);
    // Merged work is safe in the target, wherever the branch itself is.
    expect(needsPush(branch("a", { upstream_gone: true, merged_into: [{ target: "main", via: "pull_request", number: 3, url: "" }] }))).toBe(false);
    // A deleted remote branch is what a merged pull request leaves behind: no alarm.
    expect(needsPush(branch("a", { upstream_gone: true }))).toBe(false);
    expect(needsPull(branch("a", { unfetched: true }))).toBe(true);
  });
});

describe("nextStep", () => {
  const step = (...args: Parameters<typeof overview>) => nextStep(overview(...args));

  it("finishes what is half-done before anything else", () => {
    expect(step({ operation: "merge", conflicted: 2, files: 2, behind: 3 })).toEqual({ kind: "resolve", operation: "merge", conflicts: 2 });
    expect(step({ detached: true, branch: "" }).kind).toBe("detached");
  });

  it("gets the remote's commits before saving and sharing your own", () => {
    expect(step({}, { unfetched: true }).kind).toBe("fetch");
    // A fast-forward is safe even with uncommitted files, so it comes first.
    expect(step({ behind: 3, files: 2, unstaged: 2 })).toEqual({ kind: "pull", count: 3 });
    expect(step({ files: 4, unstaged: 3, untracked: 1, ahead: 2 })).toEqual({ kind: "commit", count: 4 });
    expect(step({ ahead: 2, behind: 1 })).toEqual({ kind: "rebase", ahead: 2, behind: 1 });
    expect(step({ ahead: 2 })).toEqual({ kind: "push", count: 2 });
    expect(step({ upstream: "" }, { on_github: false }).kind).toBe("publish");
  });

  it("does not suggest committing files git does not track yet", () => {
    expect(step({ files: 5, untracked: 5 }).kind).not.toBe("commit");
  });

  it("looks after the pull request once the branch is shared", () => {
    expect(step().kind).toBe("open_pr");
    expect(step({}, { pull_requests: [pr(4, { ci: failed })] })).toEqual({ kind: "fix_ci", number: 4, names: ["lint"], url: "https://ci/1" });
    expect(step({}, { pull_requests: [pr(4, { conflicting: true })] }).kind).toBe("fix_conflict");
    expect(step({}, { pull_requests: [pr(4, { review: "changes_requested" })] }).kind).toBe("changes_requested");
    expect(step({}, { pull_requests: [pr(4, { state: "queued" })] }).kind).toBe("wait_queue");
    expect(step({}, { pull_requests: [pr(4, { ci: { ...noCi, state: "running", total: 2 } })] }).kind).toBe("wait_ci");
    expect(step({}, { pull_requests: [pr(4, { ci: { ...noCi, state: "success", total: 2, passed: 2 } })] }).kind).toBe("ready");
  });

  it("says so when there is nothing to do", () => {
    expect(step({ branch: "main", upstream: "origin/main" }).kind).toBe("done");
    // A merged branch needs no pull request.
    expect(step({}, { merged_into: [{ target: "main", via: "git", number: null, url: "" }] }).kind).toBe("done");
  });

  it("works from the current branch's row on a backend without checkout state", () => {
    const old = overview({ ahead: 2 });
    delete old.checkout;
    expect(nextStep(old)).toEqual({ kind: "push", count: 2 });
  });
});

describe("attention", () => {
  it("is empty when the repository is in order", () => {
    expect(attention(overview({ branch: "main", upstream: "origin/main" }))).toEqual([]);
  });

  it("lists what is broken first and what can be tidied last", () => {
    const merged = branch("feature/done", { merged_into: [{ target: "main", via: "git", number: null, url: "" }] });
    const data = overview({}, {}, [
      merged,
      branch("feature/local", { upstream: "", on_github: false }),
      branch("feature/stale", { behind: 4 }),
    ]);
    data.pull_requests = [pr(7, { ci: failed }), pr(8, { conflicting: true }), pr(9, { review: "changes_requested" }), pr(10)];
    data.branches[1] = branch("main", { behind: 2 });
    const items = attention(data);
    expect(items.map((item) => [item.kind, item.count])).toEqual([
      ["ci_failing", 1],
      ["pr_conflicts", 1],
      ["changes_requested", 1],
      ["default_behind", 1],
      ["unpushed", 1],
      ["behind", 1],
      ["cleanup", 1],
    ]);
    expect(items[0].names).toEqual(["#7"]);
    expect(canCleanUp(merged, "main")).toBe(true);
    // The branch the person is on is never offered for removal.
    expect(canCleanUp({ ...merged, current: true }, "main")).toBe(false);
  });
});
