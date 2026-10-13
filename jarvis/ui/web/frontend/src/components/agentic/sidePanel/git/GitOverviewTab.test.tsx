import { StrictMode } from "react";
import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GitOverviewTab, resetGitOverviewCache } from "./GitOverviewTab";
import type { BranchRow, Checkout, CiStatus, PullRequest, RepoOverview } from "./gitOverviewApi";
import { openExternalUrl } from "@/lib/openExternal";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";

vi.mock("@/lib/openExternal", () => ({ openExternalUrl: vi.fn(async () => true) }));

const noCi: CiStatus = { state: "none", url: "", total: 0, passed: 0, failed: 0, running: 0, pending: 0, commit: "", names: [] };

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

const pr = (number: number, state: PullRequest["state"], ci: CiStatus = noCi, extra: Partial<PullRequest> = {}): PullRequest => ({
  number,
  title: `Change ${number}`,
  url: `https://github.com/o/r/pull/${number}`,
  state,
  base: "main",
  head: "x",
  head_oid: "",
  merged_at: "",
  updated_at: "",
  queue_position: state === "queued" ? 2 : null,
  ci,
  ...extra,
});

const CHECKOUT: Checkout = {
  branch: "feature/wip",
  detached: false,
  unborn: false,
  head: "abc123def456",
  upstream: "origin/feature/wip",
  ahead: 2,
  behind: 0,
  files: 0,
  staged: 0,
  unstaged: 0,
  untracked: 0,
  conflicted: 0,
  operation: "",
  stashes: 0,
  last_fetch: Math.floor(Date.now() / 1000) - 120,
  has_remote: true,
};

const OVERVIEW: RepoOverview = {
  available: true,
  reason: "",
  root: "/code/app",
  branch: "feature/wip",
  detached: false,
  head: "abc123def456",
  default_branch: "main",
  truncated: false,
  github: {
    available: true,
    reason: "",
    code: "",
    repo: "o/r",
    suggested_repo: "o/r",
    source: "app",
    repo_url: "https://github.com/o/r",
    fetched_at: Date.now() / 1000,
  },
  branches: [
    branch("feature/wip", {
      current: true,
      ahead: 2,
      pull_requests: [pr(7, "open")],
      ci: { ...noCi, state: "running", url: "https://github.com/o/r/actions/runs/7", total: 3, passed: 1, running: 2, names: ["tests"] },
    }),
    branch("main", { ci: { ...noCi, state: "success", total: 4, passed: 4, url: "https://github.com/o/r/actions/runs/1" } }),
    branch("feature/done", {
      merged_into: [{ target: "main", via: "pull_request", number: 5, url: "" }],
      pull_requests: [pr(5, "merged")],
      ci: { ...noCi, state: "success", total: 2, passed: 2 },
    }),
    branch("feature/queued", { pull_requests: [pr(8, "queued")] }),
    branch("feature/draft", { pull_requests: [pr(9, "draft")] }),
    branch("feature/dropped", {
      pull_requests: [pr(4, "closed")],
      ci: { ...noCi, state: "failure", total: 2, passed: 1, failed: 1, names: ["lint"], url: "https://github.com/o/r/actions/runs/4" },
    }),
  ],
  remote_branches: [branch("only-remote", { remote_only: true, upstream: "" })],
  checkout: CHECKOUT,
  base_ref: "origin/main",
};

const withCheckout = (extra: Partial<Checkout>, current: Partial<BranchRow> = {}): RepoOverview => ({
  ...OVERVIEW,
  checkout: { ...CHECKOUT, ...extra },
  branches: [{ ...OVERVIEW.branches[0], ...current }, ...OVERVIEW.branches.slice(1)],
});

let answer: unknown = OVERVIEW;
let status = 200;
/** Holds overview answers back, like a slow GitHub read. */
let gate: Promise<void> | null = null;
const calls: string[] = [];
const puts: string[] = [];
const opens: string[] = [];
const diffs: string[] = [];
/** Every action the tab asked the backend for: the route and its JSON body. */
const posts: { path: string; body: Record<string, unknown> }[] = [];
/** Queued failures per action route: `[status, detail]`, used once each. */
const refusals: Record<string, [number, unknown][]> = {};
const CONTENTS = {
  available: true,
  branch: "feature/wip",
  base: "origin/main",
  commits: [
    { sha: "aaaaaaaaaaaa", subject: "Add the widget", author: "Ada", committed_at: 1_790_000_000, on_github: false },
    { sha: "bbbbbbbbbbbb", subject: "Start the widget", author: "Ada", committed_at: 1_789_000_000, on_github: true },
  ],
  commits_truncated: false,
  files: [
    { path: "src/widget.ts", status: "added", added: 12, removed: 0 },
    { path: "README.md", status: "modified", added: 2, removed: 1 },
  ],
  files_truncated: false,
  reason: "",
};
const FILE_DIFF = {
  path: "src/widget.ts",
  status: "added",
  binary: false,
  added: 1,
  removed: 0,
  truncated: false,
  hunks: [{ header: "@@ -0,0 +1 @@", lines: [{ kind: "add", text: "export const widget = 1;", old_no: null, new_no: 1 }] }],
};
const REPOS = {
  connected: true,
  source: "app",
  login: "octo",
  reason: "",
  repos: [
    { name: "octo/other", description: "Something else", private: true, fork: false, url: "", pushed_at: "" },
    { name: "o/r", description: "", private: false, fork: false, url: "", pushed_at: "" },
  ],
};
const ACTION = /\/api\/agentic-ide\/git\/(fetch|pull|push|commit|switch|pull-request|branch\/update|branch\/delete)$/;

beforeEach(() => {
  answer = OVERVIEW;
  status = 200;
  gate = null;
  calls.length = 0;
  puts.length = 0;
  opens.length = 0;
  diffs.length = 0;
  posts.length = 0;
  for (const key of Object.keys(refusals)) delete refusals[key];
  resetGitOverviewCache();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      calls.push(url);
      const json = (body: unknown, code = 200) =>
        new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
      const action = ACTION.exec(url);
      if (action && init?.method === "POST") {
        posts.push({ path: action[1], body: JSON.parse(String(init.body)) });
        const refusal = refusals[action[1]]?.shift();
        if (refusal) return json({ detail: refusal[1] }, refusal[0]);
        return json({ ok: true, message: "Done.", upstream: "origin/feature/wip", commit: "abc1234", url: "https://github.com/o/r/pull/11" });
      }
      if (url.includes("/github/repos")) return json(REPOS);
      if (url.includes("/branch/contents")) return json(CONTENTS);
      if (url.includes("/branch/diff")) {
        diffs.push(url);
        return json(FILE_DIFF);
      }
      if (url.includes("/branch/editors")) return json({ file_manager: true, editors: [{ id: "code", label: "VS Code" }] });
      if (url.includes("/branch/open")) {
        opens.push(String(init?.body));
        return json({ opened: true, path: "/code/app" });
      }
      if (url.includes("/github/binding")) {
        puts.push(String(init?.body));
        answer = OVERVIEW;
        return json({ ok: true, repo: "o/r" });
      }
      if (gate) await gate;
      return json(answer, status);
    }),
  );
  useEventStore.setState({ activeSection: "agentic-ide" });
  useIdeChatStore.setState({ workspace: { id: "w1", name: "App", path: "/code/app" }, stagedPane: null });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.mocked(openExternalUrl).mockClear();
});

const row = (name: string) => screen.getAllByTestId("git-branch-row").find((el) => el.dataset.branch === name)!;
const rowNames = () => screen.getAllByTestId("git-branch-row").map((el) => el.dataset.branch);
const posted = (path: string) => posts.filter((post) => post.path === path).map((post) => post.body);

describe("GitOverviewTab — the checkout at a glance", () => {
  it("says who is ahead and offers the one next step as a button", async () => {
    render(<GitOverviewTab />);
    expect((await screen.findByTestId("git-current-branch")).textContent).toBe("feature/wip");
    expect(screen.getByTestId("git-sync-push").dataset.count).toBe("2");
    expect(screen.getByTestId("git-sync-pull").dataset.count).toBe("0");
    expect(screen.getByTestId("git-sync-sentence").textContent).toBe("This computer is 2 commits ahead of origin/feature/wip.");
    expect(screen.getByTestId("git-working-tree").textContent).toContain("Nothing to commit");
    const next = screen.getByTestId("git-next");
    expect(next.dataset.step).toBe("push");
    expect(next.textContent).toContain("Push 2 commits to origin/feature/wip");
    fireEvent.click(screen.getByTestId("git-next-action"));
    await vi.waitFor(() => expect(posted("push")).toEqual([{ folder: "/code/app", branch: "" }]));
    // The overview is read again once the action finished.
    await vi.waitFor(() => expect(calls.some((url) => url.includes("refresh=true"))).toBe(true));
  });

  it("commits uncommitted work from an inline message box", async () => {
    answer = withCheckout({ ahead: 0, files: 3, unstaged: 2, untracked: 1 }, { ahead: 0 });
    render(<GitOverviewTab />);
    const tree = await screen.findByTestId("git-working-tree");
    expect(tree.textContent).toContain("3 changed files");
    expect(tree.textContent).toContain("2 modified · 1 new");
    expect(screen.getByTestId("git-next").dataset.step).toBe("commit");
    fireEvent.click(screen.getByTestId("git-next-action"));
    expect(screen.getByTestId("git-commit-form").textContent).toContain("Commits all 3 changed files");
    expect((screen.getByTestId("git-commit-submit") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.change(screen.getByTestId("git-commit-message"), { target: { value: "feat: add the widget" } });
    fireEvent.click(screen.getByTestId("git-commit-submit"));
    await vi.waitFor(() => expect(posted("commit")).toEqual([{ folder: "/code/app", message: "feat: add the widget" }]));
    await vi.waitFor(() => expect(screen.queryByTestId("git-commit-form")).toBeNull());
  });

  it("opens the Changes tab to review what is uncommitted", async () => {
    answer = withCheckout({ files: 1, unstaged: 1 });
    render(<GitOverviewTab />);
    fireEvent.click(await screen.findByTestId("git-review-changes"));
    expect(useIdeSidePanelStore.getState().active).toBe("changes");
  });

  it("pulls with a fast-forward, and rewrites local commits only after a confirmation", async () => {
    answer = withCheckout({ ahead: 0, behind: 3 }, { ahead: 0, behind: 3 });
    refusals.pull = [[422, { message: "Both moved on.", code: "diverged" }]];
    render(<GitOverviewTab />);
    expect((await screen.findByTestId("git-next")).textContent).toContain("Pull 3 commits from origin/feature/wip");
    expect(screen.getByTestId("git-sync-sentence").textContent).toBe("origin/feature/wip is 3 commits ahead of this computer.");
    fireEvent.click(screen.getByTestId("git-next-action"));
    await vi.waitFor(() => expect(posted("pull")).toEqual([{ folder: "/code/app", rebase: false }]));
    // The branch had diverged: nothing was rewritten, the tab asks first.
    const dialog = await screen.findByTestId("git-confirm");
    expect(dialog.textContent).toContain("Rebase your commits onto the remote ones?");
    fireEvent.click(within(dialog).getByTestId("git-confirm-ok"));
    await vi.waitFor(() => expect(posted("pull")).toEqual([{ folder: "/code/app", rebase: false }, { folder: "/code/app", rebase: true }]));
  });

  it("offers a rebase for a diverged branch and does nothing when it is cancelled", async () => {
    answer = withCheckout({ ahead: 2, behind: 1 }, { ahead: 2, behind: 1 });
    render(<GitOverviewTab />);
    expect((await screen.findByTestId("git-next")).dataset.step).toBe("rebase");
    expect(screen.getByTestId("git-sync-sentence").textContent).toContain("Both moved on: 2 only here, 1 only on origin/feature/wip.");
    fireEvent.click(screen.getByTestId("git-next-action"));
    fireEvent.click(within(await screen.findByTestId("git-confirm")).getByTestId("git-confirm-cancel"));
    expect(screen.queryByTestId("git-confirm")).toBeNull();
    expect(posts).toEqual([]);
  });

  it("names a failing pull request's checks as the next thing to fix", async () => {
    const failing = { ...noCi, state: "failure" as const, total: 5, passed: 3, failed: 2, names: ["lint", "tests"], url: "https://github.com/o/r/actions/runs/9" };
    answer = withCheckout({ ahead: 0 }, { ahead: 0, pull_requests: [pr(7, "open", failing)], ci: failing });
    render(<GitOverviewTab />);
    const next = await screen.findByTestId("git-next");
    expect(next.dataset.step).toBe("fix_ci");
    expect(next.textContent).toContain("CI is failing on #7");
    expect(next.textContent).toContain("Failed: lint, tests");
    fireEvent.click(screen.getByTestId("git-next-action"));
    expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/actions/runs/9");
  });

  it("opens a pull request for a pushed branch that has none", async () => {
    answer = withCheckout({ ahead: 0 }, { ahead: 0, pull_requests: [], ci: noCi });
    render(<GitOverviewTab />);
    expect((await screen.findByTestId("git-next")).dataset.step).toBe("open_pr");
    fireEvent.click(screen.getByTestId("git-next-action"));
    await vi.waitFor(() => expect(posted("pull-request")).toEqual([{ folder: "/code/app", title: "", draft: false, branch: "" }]));
    await vi.waitFor(() => expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/pull/11"));
  });

  it("says so when there is nothing to do", async () => {
    answer = { ...withCheckout({ branch: "main", upstream: "origin/main", ahead: 0 }), branch: "main", branches: [branch("main", { current: true })], remote_branches: [] };
    render(<GitOverviewTab />);
    const next = await screen.findByTestId("git-next");
    expect(next.dataset.step).toBe("done");
    expect(next.textContent).toContain("Everything is up to date");
    expect(screen.queryByTestId("git-next-action")).toBeNull();
    expect(screen.getByTestId("git-sync-sentence").textContent).toBe("In sync with origin/main.");
    expect(screen.getByTestId("git-all-clear")).toBeTruthy();
  });

  it("flags commits on GitHub that were not fetched yet, and fetches them", async () => {
    answer = withCheckout({ ahead: 0 }, { ahead: 0, unfetched: true });
    render(<GitOverviewTab />);
    expect((await screen.findByTestId("git-next")).dataset.step).toBe("fetch");
    expect(screen.getByTestId("git-sync-sentence").textContent).toContain("GitHub has newer commits that are not fetched yet.");
    fireEvent.click(screen.getByTestId("git-next-action"));
    await vi.waitFor(() => expect(posted("fetch")).toEqual([{ folder: "/code/app" }]));
  });

  it("paints the last overview at once when the tab is reopened", async () => {
    const first = render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    first.unmount();
    let release: () => void = () => {};
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    render(<GitOverviewTab />);
    // No answer has arrived yet, and the tab is already complete.
    expect(screen.queryByTestId("git-loading")).toBeNull();
    expect(screen.getByTestId("git-current-branch").textContent).toBe("feature/wip");
    expect(rowNames()).toContain("main");
    release();
  });

  it("shows the tab's shape while the very first answer loads", async () => {
    let release: () => void = () => {};
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    render(<GitOverviewTab />);
    expect(screen.getByTestId("git-loading")).toBeTruthy();
    release();
    expect(await screen.findByTestId("git-status")).toBeTruthy();
  });

  it("still works against a backend from before the control center", async () => {
    const { checkout: _checkout, base_ref: _base, ...old } = OVERVIEW;
    answer = old;
    render(<GitOverviewTab />);
    expect(await screen.findByTestId("git-older-backend")).toBeTruthy();
    expect(screen.getByTestId("git-sync-push").dataset.count).toBe("2");
    expect(screen.queryByTestId("git-working-tree")).toBeNull();
    expect(rowNames()).toContain("main");
  });
});

describe("GitOverviewTab — what needs attention", () => {
  it("lists problems across the repository, worst first", async () => {
    const failing = { ...noCi, state: "failure" as const, total: 4, passed: 3, failed: 1, names: ["lint"], url: "https://github.com/o/r/actions/runs/3" };
    answer = {
      ...OVERVIEW,
      branches: [...OVERVIEW.branches, branch("wip/local", { upstream: "", on_github: false }), branch("feature/stale", { behind: 4 })],
      pull_requests: [pr(12, "open", failing), pr(13, "open", noCi, { conflicting: true }), pr(7, "open")],
    };
    render(<GitOverviewTab />);
    const items = await screen.findAllByTestId("git-attention-item");
    expect(items.map((el) => el.dataset.kind)).toEqual(["ci_failing", "pr_conflicts", "unpushed", "behind", "cleanup"]);
    expect(items[0].textContent).toContain("CI is failing on 1 pull request");
    expect(items[0].textContent).toContain("#12");
    expect(items[2].textContent).toContain("1 branch has commits only on this computer");
    // "Show" narrows the branch list to what has to be pushed — the checked-out branch included.
    fireEvent.click(items[2]);
    expect(rowNames()).toEqual(["feature/wip", "wip/local"]);
    fireEvent.click(items[3]);
    expect(rowNames()).toEqual(["feature/stale"]);
  });

  it("lists every open pull request with its CI, the broken ones first", async () => {
    const failing = { ...noCi, state: "failure" as const, total: 4, passed: 3, failed: 1, names: ["lint"], url: "https://github.com/o/r/actions/runs/3" };
    answer = {
      ...OVERVIEW,
      pull_requests: [pr(12, "open", failing, { head: "feature/broken", review: "changes_requested" }), pr(7, "open", noCi, { review: "approved" })],
    };
    render(<GitOverviewTab />);
    const rows = await screen.findAllByTestId("git-pr-row");
    expect(rows.map((el) => el.dataset.number)).toEqual(["12", "7"]);
    expect(rows[0].textContent).toContain("feature/broken");
    // Into the default branch is the rule and goes unsaid.
    expect(rows[0].textContent).not.toContain("→ main");
    expect(rows[0].textContent).toContain("changes requested");
    expect(rows[1].textContent).toContain("approved");
    expect(within(rows[0]).getByTestId("git-ci").querySelector("[data-ci-state]")?.getAttribute("data-ci-state")).toBe("failure");
    fireEvent.click(within(rows[0]).getByTestId("git-pr-open"));
    expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/pull/12");
  });

  it("removes merged branches only after showing which, and reports what was kept", async () => {
    answer = {
      ...OVERVIEW,
      branches: [...OVERVIEW.branches, branch("feature/old", { merged_into: [{ target: "main", via: "git", number: null, url: "" }], worktree: "/code/trees/old" })],
    };
    refusals["branch/delete"] = [[422, { message: "old has 1 uncommitted change. Remove it anyway?", code: "dirty" }]];
    // Strict mode on purpose: its mount, unmount, mount must not leave the run stopped.
    render(
      <StrictMode>
        <GitOverviewTab />
      </StrictMode>,
    );
    const item = (await screen.findAllByTestId("git-attention-item")).find((el) => el.dataset.kind === "cleanup")!;
    expect(item.textContent).toContain("2 merged branches can be removed");
    fireEvent.click(item);
    const dialog = await screen.findByTestId("git-cleanup");
    expect(dialog.textContent).toContain("Remove 2 merged branches?");
    expect(within(dialog).getAllByTestId("git-cleanup-pick").map((el) => el.dataset.branch)).toEqual(["feature/done", "feature/old"]);
    expect(posts).toEqual([]); // nothing happens before the confirmation
    fireEvent.click(within(dialog).getByTestId("git-cleanup-ok"));
    await vi.waitFor(() => expect(screen.getByTestId("git-cleanup").dataset.phase).toBe("done"));
    // Never forced: the worktree with uncommitted work stayed, and the dialog says why.
    expect(posted("branch/delete")).toEqual([
      { folder: "/code/app", branch: "feature/done", force: false, remote: false, with_worktree: false },
      { folder: "/code/app", branch: "feature/old", force: false, remote: false, with_worktree: true },
    ]);
    expect(screen.getByTestId("git-cleanup").textContent).toContain("Removed 1 branch");
    expect(screen.getByTestId("git-cleanup-kept").textContent).toContain("uncommitted change");
  });

  it("lets a merged branch be unticked before the cleanup", async () => {
    render(<GitOverviewTab />);
    fireEvent.click((await screen.findAllByTestId("git-attention-item")).find((el) => el.dataset.kind === "cleanup")!);
    const dialog = await screen.findByTestId("git-cleanup");
    fireEvent.click(within(dialog).getByTestId("git-cleanup-pick"));
    expect((within(dialog).getByTestId("git-cleanup-ok") as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(within(dialog).getByTestId("git-cleanup-cancel"));
    expect(screen.queryByTestId("git-cleanup")).toBeNull();
    expect(posts).toEqual([]);
  });
});

describe("GitOverviewTab — branches", () => {
  it("lists the workspace's branches and marks the checked-out one", async () => {
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    expect(rowNames()).toEqual(["feature/wip", "main", "feature/done", "feature/queued", "feature/draft", "feature/dropped"]);
    expect(row("feature/wip").dataset.current).toBe("true");
    expect(within(row("feature/wip")).getByTestId("git-current-tag")).toBeTruthy();
    expect(row("main").dataset.current).toBeUndefined();
    expect(calls[0]).toContain("/api/agentic-ide/git/overview?workspace_id=w1");
  });

  it("shows each pull request state with GitHub's colour", async () => {
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    const state = (name: string) => within(row(name)).getByTestId("git-pr").querySelector("[data-pr-state]");
    expect(state("feature/wip")?.getAttribute("class")).toContain("text-success");
    expect(state("feature/done")?.getAttribute("class")).toContain("--gh-merged");
    expect(state("feature/queued")?.getAttribute("class")).toContain("text-warning");
    expect(state("feature/draft")?.getAttribute("class")).toContain("text-muted-foreground");
    expect(state("feature/dropped")?.getAttribute("class")).toContain("text-destructive");
    expect(state("feature/dropped")?.getAttribute("data-pr-state")).toBe("closed");
  });

  it("keeps CI apart from merging: a merged branch still shows its own green check", async () => {
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    const done = row("feature/done");
    expect(within(done).getByTestId("git-fact-merged").textContent).toBe("merged into main");
    expect(within(done).getByTestId("git-ci").querySelector("[data-ci-state]")?.getAttribute("data-ci-state")).toBe("success");
    expect(within(row("main")).queryByTestId("git-fact-merged")).toBeNull();
    expect(within(row("feature/wip")).getByTestId("git-ci").querySelector("[data-ci-state]")?.getAttribute("data-ci-state")).toBe("running");
    expect(within(row("feature/dropped")).getByTestId("git-ci").querySelector("[data-ci-state]")?.getAttribute("data-ci-state")).toBe("failure");
    // No checks at all shows nothing rather than a misleading icon.
    expect(within(row("feature/queued")).queryByTestId("git-ci")).toBeNull();
  });

  it("opens the pull request and the CI run in the browser", async () => {
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    fireEvent.click(within(row("feature/wip")).getByTestId("git-pr"));
    expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/pull/7");
    fireEvent.click(within(row("feature/dropped")).getByTestId("git-ci"));
    expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/actions/runs/4");
  });

  it("explains every icon in its tooltip", async () => {
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    fireEvent.mouseEnter(within(row("feature/dropped")).getByTestId("git-ci").parentElement!);
    const tip = await screen.findByRole("tooltip");
    expect(tip.textContent).toContain("CI failed");
    expect(tip.textContent).toContain("lint");
  });

  it("says in words what each branch has to push or pull, and where it lives", async () => {
    answer = {
      ...OVERVIEW,
      branches: [
        ...OVERVIEW.branches,
        branch("wip/local", { upstream: "", on_github: false }),
        branch("feature/both", { ahead: 3, behind: 1, worktree: "/code/trees/both" }),
        branch("feature/gone", { upstream_gone: true }),
      ],
    };
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    expect(within(row("wip/local")).getByTestId("git-fact-local").textContent).toBe("local only");
    expect(row("wip/local").dataset.sync).toBe("unpublished");
    expect(within(row("feature/both")).getByTestId("git-fact-push").textContent).toBe("3 to push");
    expect(within(row("feature/both")).getByTestId("git-fact-pull").textContent).toBe("1 to pull");
    expect(within(row("feature/both")).getByTestId("git-worktree")).toBeTruthy();
    expect(within(row("feature/gone")).getByTestId("git-fact-gone").textContent).toBe("remote deleted");
    // A branch in sync says nothing about syncing at all.
    expect(within(row("main")).queryByTestId("git-fact-push")).toBeNull();
    expect(within(row("main")).queryByTestId("git-fact-local")).toBeNull();
  });

  it("shows when each branch last changed", async () => {
    const now = Math.floor(Date.now() / 1000);
    answer = {
      ...OVERVIEW,
      branches: [
        branch("fresh", { committed_at: now - 2 * 3600 }),
        branch("old", { committed_at: Date.UTC(2024, 2, 3, 12) / 1000 }),
        branch("undated"),
      ],
    };
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    const date = (name: string) => within(row(name)).queryByTestId("git-fact-date")?.textContent;
    expect(date("fresh")).toBe("2 hr. ago");
    expect(date("old")).toBe("Mar 3, 2024");
    expect(date("undated")).toBeUndefined();
  });

  it("draws a long list a page at a time", async () => {
    answer = { ...OVERVIEW, branches: Array.from({ length: 45 }, (_, index) => branch(`feature/n${index}`)), remote_branches: [] };
    render(<GitOverviewTab />);
    expect(await screen.findAllByTestId("git-branch-row")).toHaveLength(20);
    expect(screen.getByTestId("git-branches-more").textContent).toContain("Show 20 more (25 left)");
    fireEvent.click(screen.getByTestId("git-branches-more"));
    expect(screen.getAllByTestId("git-branch-row")).toHaveLength(40);
    // Searching looks through every branch, not only the ones drawn.
    fireEvent.change(screen.getByTestId("git-search"), { target: { value: "n44" } });
    expect(rowNames()).toEqual(["feature/n44"]);
  });

  it("keeps GitHub-only branches folded until asked, and fetches on refresh", async () => {
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    expect(rowNames()).not.toContain("only-remote");
    fireEvent.click(screen.getByTestId("git-remote-toggle"));
    expect(rowNames()).toContain("only-remote");
    fireEvent.click(screen.getByTestId("git-refresh"));
    await vi.waitFor(() => expect(posted("fetch")).toEqual([{ folder: "/code/app" }]));
    await vi.waitFor(() => expect(calls.some((url) => url.includes("refresh=true"))).toBe(true));
  });

  it("narrows the list by search and by filter", async () => {
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    fireEvent.click(screen.getByTestId("git-filter-failing"));
    expect(rowNames()).toEqual(["feature/dropped"]);
    fireEvent.click(screen.getByTestId("git-filter-merged"));
    expect(rowNames()).toEqual(["feature/done"]);
    fireEvent.click(screen.getByTestId("git-filter-all"));
    fireEvent.change(screen.getByTestId("git-search"), { target: { value: "#9" } });
    expect(rowNames()).toEqual(["feature/draft"]);
    // A search also finds branches that exist only on GitHub.
    fireEvent.change(screen.getByTestId("git-search"), { target: { value: "only-rem" } });
    expect(rowNames()).toEqual(["only-remote"]);
    fireEvent.change(screen.getByTestId("git-search"), { target: { value: "nothing-like-this" } });
    expect(screen.getByTestId("git-filter-empty")).toBeTruthy();
  });

  it("folds a clicked branch open with its local folder and its GitHub page", async () => {
    answer = { ...OVERVIEW, branches: [...OVERVIEW.branches, branch("wip/local", { upstream: "", on_github: false })] };
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    expect(screen.queryByTestId("git-branch-details")).toBeNull();

    fireEvent.click(within(row("feature/wip")).getByTestId("git-branch-toggle"));
    const details = within(row("feature/wip")).getByTestId("git-branch-details");
    await within(details).findByTestId("git-branch-commits");
    fireEvent.click(await within(details).findByTestId("git-open-folder"));
    await vi.waitFor(() => expect(opens).toHaveLength(1));
    expect(JSON.parse(opens[0])).toEqual({ workspace_id: "w1", branch: "feature/wip", target: "folder" });
    fireEvent.click(within(details).getByTestId("git-open-code"));
    await vi.waitFor(() => expect(JSON.parse(opens[1]).target).toBe("code"));
    fireEvent.click(within(details).getByTestId("git-open-github"));
    expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/tree/feature/wip");
    fireEvent.click(within(details).getByTestId("git-open-pr"));
    expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/pull/7");
    expect(within(details).getByTestId("git-branch-base").textContent).toBe("1 ahead of origin/main, 0 behind");

    // Not checked out anywhere: nothing local to open, a switch instead; not on GitHub either.
    fireEvent.click(within(row("wip/local")).getByTestId("git-branch-toggle"));
    const local = within(row("wip/local")).getByTestId("git-branch-details");
    await within(local).findByTestId("git-branch-commits");
    expect(within(local).queryByTestId("git-open-folder")).toBeNull();
    expect(within(local).getByTestId("git-act-switch").textContent).toBe("Switch to it");
    expect(within(local).queryByTestId("git-open-github")).toBeNull();

    // The branch is readable in place: its commits and files, each file's diff one click away.
    // A commit only on this computer gets no GitHub link (that page would be a 404).
    const commit = (sha: string) => within(details).getAllByTestId("git-branch-commit").find((el) => el.dataset.sha === sha)!;
    expect(within(commit("aaaaaaaaaaaa")).queryByTestId("git-commit-link")).toBeNull();
    expect(within(commit("aaaaaaaaaaaa")).getByTestId("git-commit-local")).toBeTruthy();
    fireEvent.click(within(commit("bbbbbbbbbbbb")).getByTestId("git-commit-link"));
    expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/commit/bbbbbbbbbbbb");
    expect(within(details).getByTestId("git-branch-commits").textContent).toContain("Add the widget");
    expect(within(details).getByTestId("git-branch-commits").textContent).toContain("2 commits not in origin/main");
    const file = within(details).getAllByTestId("git-branch-file").find((el) => el.dataset.path === "src/widget.ts")!;
    fireEvent.click(within(file).getByRole("button"));
    expect(await within(file).findByTestId("explorer-diff")).toBeTruthy();
    expect(within(file).getByTestId("explorer-diff").textContent).toContain("export const widget = 1;");
    expect(diffs[0]).toContain("path=src%2Fwidget.ts");
    expect(diffs[0]).toContain("base=main");

    // A second click folds it away again.
    fireEvent.click(within(row("feature/wip")).getByTestId("git-branch-toggle"));
    expect(within(row("feature/wip")).queryByTestId("git-branch-details")).toBeNull();
  });

  it("acts on a branch from its details: switch, publish, update", async () => {
    answer = {
      ...OVERVIEW,
      branches: [...OVERVIEW.branches, branch("wip/local", { upstream: "", on_github: false }), branch("feature/stale", { behind: 4 })],
    };
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    fireEvent.click(within(row("wip/local")).getByTestId("git-branch-toggle"));
    const local = within(row("wip/local")).getByTestId("git-branch-details");
    expect(within(local).getByTestId("git-act-push").textContent).toBe("Publish");
    fireEvent.click(within(local).getByTestId("git-act-push"));
    await vi.waitFor(() => expect(posted("push")).toEqual([{ folder: "/code/app", branch: "wip/local" }]));
    await vi.waitFor(() => expect((within(local).getByTestId("git-act-switch") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(within(local).getByTestId("git-act-switch"));
    await vi.waitFor(() => expect(posted("switch")).toEqual([{ folder: "/code/app", branch: "wip/local" }]));

    fireEvent.click(within(row("feature/stale")).getByTestId("git-branch-toggle"));
    const stale = within(row("feature/stale")).getByTestId("git-branch-details");
    await vi.waitFor(() => expect((within(stale).getByTestId("git-act-update") as HTMLButtonElement).disabled).toBe(false));
    fireEvent.click(within(stale).getByTestId("git-act-update"));
    await vi.waitFor(() => expect(posted("branch/update")).toEqual([{ folder: "/code/app", branch: "feature/stale" }]));
    // The branch the person is on, and the default branch, cannot be deleted from here.
    fireEvent.click(within(row("main")).getByTestId("git-branch-toggle"));
    expect(within(row("main")).queryByTestId("git-act-delete")).toBeNull();
  });

  it("deletes a branch only after a confirmation, and asks again before losing commits", async () => {
    refusals["branch/delete"] = [[422, { message: "feature/draft has 2 commits that exist nowhere else. Delete it anyway?", code: "unmerged" }]];
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    fireEvent.click(within(row("feature/draft")).getByTestId("git-branch-toggle"));
    fireEvent.click(within(row("feature/draft")).getByTestId("git-act-delete"));
    const first = await screen.findByTestId("git-confirm");
    expect(first.textContent).toContain("Delete feature/draft?");
    expect(posts).toEqual([]); // the click alone deleted nothing
    fireEvent.click(within(first).getByTestId("git-confirm-ok"));
    await vi.waitFor(() =>
      expect(posted("branch/delete")).toEqual([{ folder: "/code/app", branch: "feature/draft", force: false, remote: false, with_worktree: false }]),
    );
    // The backend found commits that exist nowhere else: a second, explicit question.
    const second = await screen.findByText("feature/draft holds work that exists nowhere else");
    expect(second).toBeTruthy();
    expect(screen.getByTestId("git-confirm").textContent).toContain("Deleting it loses those commits for good.");
    fireEvent.click(screen.getByTestId("git-confirm-ok"));
    await vi.waitFor(() => expect(posted("branch/delete")[1]).toEqual({ folder: "/code/app", branch: "feature/draft", force: true, remote: false, with_worktree: false }));
  });

  it("can delete the branch on GitHub too, when asked", async () => {
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    fireEvent.click(within(row("feature/queued")).getByTestId("git-branch-more"));
    fireEvent.click(within(await screen.findByTestId("git-branch-menu")).getByTestId("git-menu-delete"));
    const dialog = await screen.findByTestId("git-confirm");
    fireEvent.click(within(dialog).getByTestId("git-confirm-remote"));
    fireEvent.click(within(dialog).getByTestId("git-confirm-ok"));
    await vi.waitFor(() => expect(posted("branch/delete")[0]).toMatchObject({ branch: "feature/queued", remote: true }));
  });

  it("offers GitHub pages and copies from a branch's menu", async () => {
    render(<GitOverviewTab />);
    await screen.findAllByTestId("git-branch-row");
    fireEvent.click(within(row("feature/queued")).getByTestId("git-branch-more"));
    const menu = await screen.findByTestId("git-branch-menu");
    expect(within(menu).getByTestId("git-menu-pr").textContent).toContain("#8");
    // A live pull request exists, so there is nothing new to create.
    expect(within(menu).queryByTestId("git-menu-create-pr")).toBeNull();
    fireEvent.click(within(menu).getByTestId("git-menu-compare"));
    expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/compare/main...feature/queued");
    expect(screen.queryByTestId("git-branch-menu")).toBeNull();

    fireEvent.contextMenu(row("feature/done"));
    const second = await screen.findByTestId("git-branch-menu");
    fireEvent.click(within(second).getByTestId("git-menu-create-pr"));
    expect(openExternalUrl).toHaveBeenCalledWith("https://github.com/o/r/compare/main...feature/done?expand=1");
  });
});

describe("GitOverviewTab — connecting", () => {
  it("says why when the folder is not a repository", async () => {
    answer = { ...OVERVIEW, available: false, reason: "This folder is not a git repository.", branches: [], remote_branches: [] };
    render(<GitOverviewTab />);
    expect((await screen.findByTestId("git-unavailable")).textContent).toContain("not a git repository");
  });

  it("asks once which GitHub repository the folder is, recommending its remote", async () => {
    answer = { ...OVERVIEW, github: { ...OVERVIEW.github, available: false, code: "needs_repo", repo: "", repo_url: "" } };
    render(<GitOverviewTab />);
    // The recommendation is clickable at once; the rest of the list follows.
    await vi.waitFor(() => expect(screen.getAllByTestId("git-repo-choice")).toHaveLength(2));
    const choices = screen.getAllByTestId("git-repo-choice");
    expect(choices.map((el) => el.dataset.repo)).toEqual(["o/r", "octo/other"]);
    expect(choices[0].textContent).toContain("Recommended");
    expect(screen.getByTestId("git-repo-picker").textContent).toContain("Connect a GitHub repository");
    fireEvent.click(choices[0]);
    await vi.waitFor(() => expect(puts).toEqual([JSON.stringify({ workspace_id: "w1", repo: "o/r" })]));
    expect(await screen.findAllByTestId("git-branch-row")).toHaveLength(6);
    expect(screen.queryByTestId("git-repo-picker")).toBeNull();
  });

  it("leaves the picker at once after a pick, while GitHub is still being read", async () => {
    answer = { ...OVERVIEW, github: { ...OVERVIEW.github, available: false, code: "needs_repo", repo: "", repo_url: "" } };
    render(<GitOverviewTab />);
    await vi.waitFor(() => expect(screen.getAllByTestId("git-repo-choice")).toHaveLength(2));
    let release: () => void = () => {};
    gate = new Promise<void>((resolve) => {
      release = resolve;
    });
    fireEvent.click(screen.getAllByTestId("git-repo-choice")[0]);
    // The local branches and the choice show before GitHub has answered.
    expect(await screen.findAllByTestId("git-branch-row")).toHaveLength(6);
    expect(screen.queryByTestId("git-repo-picker")).toBeNull();
    const state = screen.getByTestId("git-github-state");
    expect(state.textContent).toContain("o/r");
    expect(state.textContent).toContain("Reading pull requests and CI from GitHub");
    release();
    await vi.waitFor(() => expect(screen.getByTestId("git-github-state").textContent).toContain("fetched 2 min. ago"));
  });

  it("reopens the pick from the repository name to change it", async () => {
    render(<GitOverviewTab />);
    fireEvent.click(await screen.findByTestId("git-bound-repo"));
    await vi.waitFor(() => expect(screen.getAllByTestId("git-repo-choice")).toHaveLength(2));
    fireEvent.click(screen.getByLabelText("Keep the current repository"));
    expect(await screen.findAllByTestId("git-branch-row")).toHaveLength(6);
  });

  it("offers to connect GitHub and still shows the local state", async () => {
    answer = { ...OVERVIEW, github: { ...OVERVIEW.github, available: false, code: "not_connected", repo: "" } };
    render(<GitOverviewTab />);
    expect(await screen.findByTestId("git-connect-github")).toBeTruthy();
    expect(screen.getAllByTestId("git-branch-row")).toHaveLength(6);
    expect(screen.getByTestId("git-sync-push").dataset.count).toBe("2");
    // Pull requests are GitHub's: without a connection there is no such list.
    expect(screen.queryByTestId("git-section-prs")).toBeNull();
    fireEvent.click(screen.getByText("Connect GitHub"));
    expect(useEventStore.getState().activeSection).toBe("plugins");
  });

  it("asks for one restart when the running backend does not know the route yet", async () => {
    answer = { detail: "Not Found" };
    status = 404;
    render(<GitOverviewTab />);
    expect((await screen.findByTestId("git-error")).textContent).toContain("Connect a GitHub repository");
    fireEvent.click(screen.getByTestId("git-restart"));
    await vi.waitFor(() => expect(calls).toContain("/api/settings/restart-app"));
  });
});
