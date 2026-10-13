/**
 * What the Git tab concludes from one overview: how a branch stands to its
 * remote, what needs a look across the repository, and the one next step for
 * the checkout the person is in. Pure functions — the components only render.
 */

import type { BranchRow, Checkout, PullRequest, RepoOverview } from "./gitOverviewApi";

/** How a branch stands to its remote counterpart. */
export type SyncState =
  | "synced"
  | "ahead" // commits to push
  | "behind" // commits to pull
  | "diverged" // both
  | "unpublished" // only on this computer
  | "gone" // its remote branch was deleted
  | "remote_only";

export function syncOf(row: BranchRow): SyncState {
  if (row.remote_only) return "remote_only";
  if (row.upstream_gone) return "gone";
  if (!row.upstream) return row.on_github ? "synced" : "unpublished";
  if (row.ahead && row.behind) return "diverged";
  if (row.ahead) return "ahead";
  return row.behind ? "behind" : "synced";
}

const LIVE = new Set(["queued", "open", "draft"]);

/** The branch's pull request that is still open, if it has one. */
export function livePr(row: BranchRow): PullRequest | undefined {
  return row.pull_requests.find((pr) => LIVE.has(pr.state));
}

export function isMerged(row: BranchRow): boolean {
  return row.merged_into.length > 0;
}

/** Commits that exist only on this computer: pushing is what backs them up. */
export function needsPush(row: BranchRow): boolean {
  if (row.remote_only || isMerged(row)) return false;
  const sync = syncOf(row);
  if (sync === "ahead" || sync === "diverged") return true;
  // Never pushed: only a branch with work of its own counts. A branch whose
  // remote one was deleted is not counted — that is what a merged pull request
  // leaves behind, and calling it unsaved work would cry wolf.
  return sync === "unpublished" && (row.base_ahead ?? 1) > 0;
}

export function needsPull(row: BranchRow): boolean {
  return !row.remote_only && (row.behind > 0 || Boolean(row.unfetched));
}

/** A merged branch that is neither checked out here nor the default one can go. */
export function canCleanUp(row: BranchRow, defaultBranch: string): boolean {
  return !row.remote_only && !row.current && row.name !== defaultBranch && isMerged(row);
}

export type BranchFilter = "all" | "unpushed" | "behind" | "failing" | "pr" | "merged";
export const BRANCH_FILTERS: readonly BranchFilter[] = ["all", "unpushed", "behind", "failing", "pr", "merged"];

export function matchesFilter(row: BranchRow, filter: BranchFilter): boolean {
  if (filter === "unpushed") return needsPush(row);
  if (filter === "behind") return needsPull(row);
  if (filter === "failing") return row.ci.state === "failure";
  if (filter === "pr") return Boolean(livePr(row));
  if (filter === "merged") return isMerged(row);
  return true;
}

export function matchesQuery(row: BranchRow, query: string): boolean {
  if (!query) return true;
  const needle = query.toLowerCase().replace(/^#/, "");
  return (
    row.name.toLowerCase().includes(needle) ||
    row.pull_requests.some((pr) => String(pr.number) === needle || pr.title.toLowerCase().includes(needle))
  );
}

/**
 * The checkout's state. A backend from before the control center sends none;
 * the current branch's row then stands in (no uncommitted-change counts).
 */
export function checkoutOf(overview: RepoOverview): Checkout {
  if (overview.checkout) return overview.checkout;
  const row = overview.branches.find((branch) => branch.current);
  return {
    branch: overview.branch,
    detached: overview.detached,
    unborn: false,
    head: overview.head,
    upstream: row?.upstream ?? "",
    ahead: row?.ahead ?? 0,
    behind: row?.behind ?? 0,
    files: 0,
    staged: 0,
    unstaged: 0,
    untracked: 0,
    conflicted: 0,
    operation: "",
    stashes: 0,
    last_fetch: 0,
    has_remote: true,
  };
}

/** Every pull request that is still open; derived from the branches for an older backend. */
export function openPullRequests(overview: RepoOverview): PullRequest[] {
  if (overview.pull_requests) return overview.pull_requests;
  const seen = new Set<number>();
  const found: PullRequest[] = [];
  for (const row of [...overview.branches, ...overview.remote_branches]) {
    const pr = livePr(row);
    if (pr && !seen.has(pr.number)) {
      seen.add(pr.number);
      found.push(pr);
    }
  }
  return found;
}

// ------------------------------------------------------------------ next step

export type NextStep =
  | { kind: "resolve"; operation: string; conflicts: number }
  | { kind: "detached" }
  | { kind: "fetch" }
  | { kind: "pull"; count: number }
  | { kind: "commit"; count: number }
  | { kind: "rebase"; ahead: number; behind: number }
  | { kind: "publish" }
  | { kind: "push"; count: number }
  | { kind: "open_pr" }
  | { kind: "fix_ci"; number: number | null; names: string[]; url: string }
  | { kind: "fix_conflict"; pr: PullRequest }
  | { kind: "changes_requested"; pr: PullRequest }
  | { kind: "wait_queue"; pr: PullRequest }
  | { kind: "wait_ci"; number: number | null; url: string }
  | { kind: "ready"; pr: PullRequest }
  | { kind: "done" };

/**
 * The one thing to do next in this checkout, in the order a careful developer
 * works: finish what is half-done, get the remote's commits, save your own,
 * share them, then look after the pull request.
 */
export function nextStep(overview: RepoOverview): NextStep {
  const checkout = checkoutOf(overview);
  const row = overview.branches.find((branch) => branch.current);
  if (checkout.operation || checkout.conflicted > 0) {
    return { kind: "resolve", operation: checkout.operation, conflicts: checkout.conflicted };
  }
  if (checkout.detached || !checkout.branch) return { kind: "detached" };
  if (row?.unfetched) return { kind: "fetch" };
  // A fast-forward never touches local commits, so it comes before anything else.
  if (checkout.behind > 0 && checkout.ahead === 0) return { kind: "pull", count: checkout.behind };
  const tracked = checkout.staged + checkout.unstaged;
  if (tracked > 0) return { kind: "commit", count: checkout.files };
  if (checkout.behind > 0 && checkout.ahead > 0) {
    return { kind: "rebase", ahead: checkout.ahead, behind: checkout.behind };
  }
  const isDefault = checkout.branch === overview.default_branch;
  const hasWork = (row?.base_ahead ?? 1) > 0;
  if (!checkout.upstream && checkout.has_remote && (!isDefault || !row?.on_github) && hasWork) {
    return { kind: "publish" };
  }
  if (checkout.ahead > 0) return { kind: "push", count: checkout.ahead };

  const pr = row ? livePr(row) : undefined;
  if (pr) {
    if (pr.ci.state === "failure") return { kind: "fix_ci", number: pr.number, names: pr.ci.names, url: pr.ci.url || pr.url };
    if (pr.conflicting) return { kind: "fix_conflict", pr };
    if (pr.review === "changes_requested") return { kind: "changes_requested", pr };
    if (pr.state === "queued") return { kind: "wait_queue", pr };
    if (pr.ci.state === "running" || pr.ci.state === "pending") return { kind: "wait_ci", number: pr.number, url: pr.ci.url || pr.url };
    if (pr.state === "open" && pr.ci.state === "success") return { kind: "ready", pr };
    return { kind: "done" };
  }
  if (row && !isDefault && row.upstream && !row.upstream_gone && !isMerged(row) && hasWork && overview.github.available) {
    return { kind: "open_pr" };
  }
  if (row && row.ci.state === "failure" && !row.ci_stale) {
    return { kind: "fix_ci", number: null, names: row.ci.names, url: row.ci.url };
  }
  if (row && (row.ci.state === "running" || row.ci.state === "pending") && !row.ci_stale) {
    return { kind: "wait_ci", number: null, url: row.ci.url };
  }
  return { kind: "done" };
}

// ------------------------------------------------------------------ attention

export type AttentionKind =
  | "ci_failing"
  | "default_ci"
  | "pr_conflicts"
  | "changes_requested"
  | "default_behind"
  | "unpushed"
  | "behind"
  | "cleanup";

export interface AttentionItem {
  kind: AttentionKind;
  tone: "danger" | "warning" | "neutral";
  count: number;
  /** A few names for the row's second line (branches, or `#12` for pull requests). */
  names: string[];
}

const MAX_NAMES = 3;

/** What needs a look across the repository, worst first. Empty means all clear. */
export function attention(overview: RepoOverview): AttentionItem[] {
  const items: AttentionItem[] = [];
  const prs = openPullRequests(overview);
  const add = (kind: AttentionKind, tone: AttentionItem["tone"], names: string[]) => {
    if (names.length > 0) items.push({ kind, tone, count: names.length, names: names.slice(0, MAX_NAMES) });
  };
  const number = (pr: PullRequest) => `#${pr.number}`;
  const local = overview.branches;
  const fallback = local.find((row) => row.name === overview.default_branch);

  add("ci_failing", "danger", prs.filter((pr) => pr.ci.state === "failure").map(number));
  if (fallback && fallback.ci.state === "failure") add("default_ci", "danger", fallback.ci.names.length ? fallback.ci.names : [fallback.name]);
  add("pr_conflicts", "danger", prs.filter((pr) => pr.conflicting).map(number));
  add("changes_requested", "warning", prs.filter((pr) => pr.review === "changes_requested").map(number));
  if (fallback && !fallback.current && needsPull(fallback)) add("default_behind", "warning", [fallback.name]);
  add("unpushed", "warning", local.filter((row) => !row.current && needsPush(row)).map((row) => row.name));
  add(
    "behind",
    "warning",
    local.filter((row) => !row.current && row.name !== overview.default_branch && needsPull(row) && !isMerged(row)).map((row) => row.name),
  );
  add("cleanup", "neutral", local.filter((row) => canCleanUp(row, overview.default_branch)).map((row) => row.name));
  return items;
}
