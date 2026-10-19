import { act, cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { GitOverviewTab, resetGitOverviewCache } from "./GitOverviewTab";
import type { GraphPage, ScmFile, ScmStatus } from "./scm/scmApi";
import { useCodeEditorStore } from "@/store/codeEditor";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useGitSessionStore } from "@/store/gitSession";
import { useWorkspacePanesStore } from "@/store/workspacePanes";

vi.mock("./scm/MonacoDiff", () => ({ default: () => <div data-testid="scm-diff-editor" /> }));

const file = (path: string, letter: ScmFile["letter"], status: string): ScmFile => ({ path, letter, status, original: "" });

const BASE: ScmStatus = {
  available: true,
  reason: "",
  root: "/code/app",
  prefix: "",
  branch: "main",
  head: "c2c2c2c2c2c2",
  detached: false,
  unborn: false,
  upstream: "origin/main",
  ahead: 0,
  behind: 0,
  operation: "",
  remotes: ["origin"],
  stashes: 0,
  merge: [],
  staged: [file("src/new.ts", "A", "index_added")],
  changes: [file("app.py", "M", "modified"), file("notes.txt", "U", "untracked"), file("old.txt", "D", "deleted")],
  truncated: false,
  head_message: "feat: before",
};

const GRAPH: GraphPage = {
  commits: [
    { id: "c2c2c2c2c2c2", parents: ["c1c1c1c1c1c1"], author: "Ada", email: "ada@example.invalid", date: 1_790_000_000, refs: ["HEAD -> refs/heads/main", "refs/remotes/origin/main"], subject: "feat: second" },
    { id: "c1c1c1c1c1c1", parents: [], author: "Ada", email: "ada@example.invalid", date: 1_789_000_000, refs: ["tag: refs/tags/v1.0"], subject: "feat: first" },
  ],
  more: false,
  head: "c2c2c2c2c2c2",
  upstream: "origin/main",
  incoming: [],
  outgoing: [],
};

let status: ScmStatus = BASE;
const FOLLOW = { enabled: false, eligible: true, reason: "", head: "", remote: "", last_check: 0, last_update: 0, last_subject: "", busy: "", restart_pending: false, blocked_by: [] as string[] };
let follow = FOLLOW;
const posts: { path: string; body: Record<string, unknown> }[] = [];
const gets: string[] = [];

beforeEach(() => {
  status = BASE;
  follow = FOLLOW;
  posts.length = 0;
  gets.length = 0;
  window.localStorage.clear();
  resetGitOverviewCache();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input);
      const json = (body: unknown, code = 200) => new Response(JSON.stringify(body), { status: code, headers: { "Content-Type": "application/json" } });
      if (url.includes("/scm/follow-main")) {
        if (init?.method === "PUT") follow = { ...follow, ...JSON.parse(String(init.body)) };
        return json(follow);
      }
      if (init?.method === "POST") {
        posts.push({ path: url.replace(/^.*\/api\/agentic-ide\/git\//, ""), body: JSON.parse(String(init.body)) });
        return json({ ok: true, commit: "abc1234", message: "feat: before", branch: "x", upstream: "origin/main", result: "merged" });
      }
      gets.push(url);
      if (url.includes("/scm/status")) return json(status);
      if (url.includes("/scm/graph")) return json(GRAPH);
      if (url.includes("/scm/commit?")) {
        return json({
          id: "c2c2c2c2c2c2",
          parents: ["c1c1c1c1c1c1"],
          author: "Ada",
          email: "",
          date: 0,
          committer: "Ada",
          committer_date: 0,
          message: "feat: second",
          files: [{ path: "src/x.ts", letter: "M", original: "" }],
          stat: "1 file changed, 2 insertions(+)",
        });
      }
      if (url.includes("/api/agentic-ide/panes")) {
        const pane = (key: string, display_name: string, recap: string) => ({
          workspace_id: "w1", workspace_name: "App", folder: "/code/app", workspace_active: true, key: key.toLowerCase(), history_id: key, name: key,
          agent: display_name.toLowerCase(), display_name, accepts_prompts: true, status: "live", exit_code: null, activity: "idle",
          activity_since: 0, worked: true, started_at: null, last_output_at: null, last_prompt: "", last_prompt_at: null, recap,
          has_resume: true, readable: true, account: null, account_label: null, archived: false,
        });
        return json({ panes: [pane("T1", "Claude Code", "fix the login"), pane("T2", "Codex", "add the widget")], active_id: "w1" });
      }
      if (url.includes("/terminals/T2/changes")) {
        return json({
          workspace_id: "w1",
          available: true,
          branch: "main",
          truncated: false,
          reason: "",
          base: "b0b0b0b0b0b0",
          since_ms: Date.now() - 600_000,
          generated: 2,
          files: [
            { path: "src/widget.ts", status: "added", added: 3, removed: 0, is_directory: false, authors: [], committed: true },
            { path: "app.py", status: "modified", added: 1, removed: 1, is_directory: false, authors: [], committed: false },
          ],
        });
      }
      if (url.includes("/scm/session-file")) return json({ path: "src/widget.ts", before: null, after: "export const w = 1;\n", binary: false });
      if (url.includes("/scm/refs")) {
        return json({
          current: "main",
          refs: [
            { kind: "head", name: "main", commit: "c2c2c2c", date: 0, subject: "feat: second", upstream: "origin/main" },
            { kind: "head", name: "feature/x", commit: "c1c1c1c", date: 0, subject: "feat: first", upstream: "" },
            { kind: "tag", name: "v1.0", commit: "c1c1c1c", date: 0, subject: "", upstream: "" },
          ],
        });
      }
      return json({ detail: "Not Found" }, 404);
    }),
  );
  useEventStore.setState({ activeSection: "agentic-ide" });
  useIdeChatStore.setState({ workspace: { id: "w1", name: "App", path: "/code/app" }, stagedPane: null });
  useCodeEditorStore.setState({ tabs: [] });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const fileRow = (path: string, group = "changes") =>
  screen.getAllByTestId("scm-file").find((element) => element.dataset.path === path && element.dataset.group === group)!;
const posted = (path: string) => posts.filter((post) => post.path === path).map((post) => post.body);

describe("GitOverviewTab — changes", () => {
  it("lists staged and unstaged files in their groups with a status letter", async () => {
    render(<GitOverviewTab />);
    expect(await screen.findByTestId("scm-group-staged")).toBeTruthy();
    expect(within(screen.getByTestId("scm-group-staged")).getByTestId("scm-group-count").textContent).toBe("1");
    expect(within(screen.getByTestId("scm-group-changes")).getByTestId("scm-group-count").textContent).toBe("3");
    expect(fileRow("app.py").dataset.letter).toBe("M");
    expect(fileRow("notes.txt").dataset.letter).toBe("U");
    expect(fileRow("src/new.ts", "staged").dataset.letter).toBe("A");
    expect(within(fileRow("old.txt")).getByText("old.txt").className).toContain("line-through");
    expect(within(fileRow("app.py")).getByTestId("scm-letter").className).toContain("scm-tone-M");
    expect(screen.getByTestId("scm-branch").textContent).toBe("main*");
  });

  it("stages and unstages from a file's row", async () => {
    render(<GitOverviewTab />);
    fireEvent.click(within(await screen.findByText("app.py").then(() => fileRow("app.py"))).getByTestId("scm-stage"));
    await vi.waitFor(() => expect(posted("scm/stage")).toEqual([{ workspace_id: "w1", paths: ["app.py"] }]));
    fireEvent.click(within(fileRow("src/new.ts", "staged")).getByTestId("scm-unstage"));
    await vi.waitFor(() => expect(posted("scm/unstage")).toEqual([{ workspace_id: "w1", paths: ["src/new.ts"] }]));
  });

  it("acts on every selected file at once", async () => {
    render(<GitOverviewTab />);
    await screen.findByText("app.py");
    fireEvent.click(fileRow("app.py"));
    fireEvent.click(fileRow("notes.txt"), { ctrlKey: true });
    fireEvent.click(within(fileRow("notes.txt")).getByTestId("scm-stage"));
    await vi.waitFor(() => expect(posted("scm/stage")).toEqual([{ workspace_id: "w1", paths: ["app.py", "notes.txt"] }]));
  });

  it("commits the staged files with Ctrl+Enter and empties the box", async () => {
    render(<GitOverviewTab />);
    const box = (await screen.findByTestId("scm-message")) as HTMLTextAreaElement;
    expect(box.placeholder).toContain("main");
    fireEvent.change(box, { target: { value: "feat: widget" } });
    fireEvent.keyDown(box, { key: "Enter", ctrlKey: true });
    await vi.waitFor(() => expect(posted("scm/commit")).toHaveLength(1));
    expect(posted("scm/commit")[0]).toMatchObject({ message: "feat: widget", amend: false, all_changes: false });
    await vi.waitFor(() => expect(box.value).toBe(""));
  });

  it("asks before committing every change when nothing is staged", async () => {
    status = { ...BASE, staged: [] };
    render(<GitOverviewTab />);
    fireEvent.change(await screen.findByTestId("scm-message"), { target: { value: "fix: all" } });
    fireEvent.click(screen.getByTestId("scm-primary"));
    fireEvent.click(await screen.findByTestId("scm-choice-yes"));
    await vi.waitFor(() => expect(posted("scm/commit")[0]).toMatchObject({ message: "fix: all", all_changes: true }));
  });

  it("asks for a message instead of committing without one", async () => {
    render(<GitOverviewTab />);
    fireEvent.click(await screen.findByTestId("scm-primary"));
    expect(await screen.findByTestId("scm-message-error")).toBeTruthy();
    expect(posts).toEqual([]);
  });

  it("commits and pushes from the button's menu", async () => {
    render(<GitOverviewTab />);
    fireEvent.change(await screen.findByTestId("scm-message"), { target: { value: "feat: ship" } });
    fireEvent.click(screen.getByTestId("scm-primary-more"));
    fireEvent.click(await screen.findByTestId("scm-menu-commit-push"));
    await vi.waitFor(() => expect(posted("scm/push")).toHaveLength(1));
    expect(posted("scm/commit")[0]).toMatchObject({ message: "feat: ship" });
  });

  it("discards a file only after a confirmation", async () => {
    render(<GitOverviewTab />);
    await screen.findByText("app.py");
    fireEvent.click(within(fileRow("app.py")).getByTestId("scm-discard"));
    expect(await screen.findByTestId("scm-choice")).toBeTruthy();
    fireEvent.click(screen.getByTestId("scm-choice-cancel"));
    expect(posted("scm/discard")).toEqual([]);
    fireEvent.click(within(fileRow("app.py")).getByTestId("scm-discard"));
    fireEvent.click(await screen.findByTestId("scm-choice-discard"));
    await vi.waitFor(() => expect(posted("scm/discard")).toEqual([{ workspace_id: "w1", paths: ["app.py"] }]));
  });

  it("opens a changed file's diff in the editor and an untracked file as it is", async () => {
    render(<GitOverviewTab />);
    await screen.findByText("app.py");
    fireEvent.click(fileRow("app.py"));
    expect(useCodeEditorStore.getState().tabs.map((tab) => [tab.path, tab.mode])).toEqual([["app.py", "diff"]]);
    fireEvent.click(fileRow("notes.txt"));
    expect(useCodeEditorStore.getState().tabs.map((tab) => [tab.path, tab.mode])).toEqual([["notes.txt", "edit"]]);
  });

  it("shows folders in tree view", async () => {
    render(<GitOverviewTab />);
    await screen.findByText("app.py");
    expect(screen.queryByTestId("scm-folder")).toBeNull();
    fireEvent.click(screen.getByTestId("scm-view-mode"));
    expect((await screen.findByTestId("scm-folder")).textContent).toContain("src");
  });

  it("turns the button into Sync with the counts when there is nothing to commit", async () => {
    status = { ...BASE, staged: [], changes: [], ahead: 1, behind: 2 };
    render(<GitOverviewTab />);
    const button = await screen.findByTestId("scm-primary");
    expect(button.dataset.action).toBe("sync");
    expect(button.textContent).toContain("2↓");
    expect(button.textContent).toContain("1↑");
    fireEvent.click(button);
    fireEvent.click(await screen.findByTestId("scm-choice-ok"));
    await vi.waitFor(() => expect(posted("scm/sync")).toHaveLength(1));
  });

  it("offers to publish a branch that has no upstream", async () => {
    status = { ...BASE, staged: [], changes: [], upstream: "" };
    render(<GitOverviewTab />);
    const button = await screen.findByTestId("scm-primary");
    expect(button.dataset.action).toBe("publish");
    fireEvent.click(button);
    await vi.waitFor(() => expect(posted("scm/push")).toEqual([{ workspace_id: "w1", remote: "origin" }]));
  });

  it("switches branch from the branch name", async () => {
    render(<GitOverviewTab />);
    fireEvent.click(await screen.findByTestId("scm-branch"));
    const items = await screen.findAllByTestId("scm-quick-pick-item");
    expect(items.map((item) => item.textContent)).toEqual(expect.arrayContaining([expect.stringContaining("feature/x"), expect.stringContaining("v1.0")]));
    fireEvent.click(items.find((item) => item.textContent?.includes("feature/x"))!);
    await vi.waitFor(() => expect(posted("scm/checkout")).toEqual([{ workspace_id: "w1", ref: "feature/x", detached: false }]));
  });

  it("stashes with a message from the more menu", async () => {
    render(<GitOverviewTab />);
    fireEvent.click(await screen.findByTestId("scm-more"));
    fireEvent.mouseEnter(await screen.findByTestId("scm-menu-stash-menu"));
    fireEvent.click(await screen.findByTestId("scm-menu-s-stash"));
    const box = await screen.findByTestId("scm-quick-input-box");
    fireEvent.change(box, { target: { value: "wip" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await vi.waitFor(() => expect(posted("scm/stash")).toEqual([{ workspace_id: "w1", message: "wip" }]));
  });

  it("puts the message of an undone commit back into the box", async () => {
    render(<GitOverviewTab />);
    fireEvent.click(await screen.findByTestId("scm-more"));
    fireEvent.mouseEnter(await screen.findByTestId("scm-menu-commit-menu"));
    fireEvent.click(await screen.findByTestId("scm-menu-c-undo"));
    await vi.waitFor(() => expect((screen.getByTestId("scm-message") as HTMLTextAreaElement).value).toBe("feat: before"));
    expect(posted("scm/undo-commit")).toHaveLength(1);
  });

  it("offers to initialize a folder that is no repository", async () => {
    status = { ...BASE, available: false, reason: "app is not a git repository." };
    render(<GitOverviewTab />);
    fireEvent.click(await screen.findByTestId("scm-init"));
    await vi.waitFor(() => expect(posted("prepare")).toEqual([{ folder: "/code/app", mode: "init", branch: "", base: "" }]));
  });
});

describe("GitOverviewTab — one agent session", () => {
  beforeEach(() => useWorkspacePanesStore.setState({ panes: [], loaded: false }));

  it("folds the repository away from its row", async () => {
    render(<GitOverviewTab />);
    fireEvent.click(await screen.findByTestId("scm-repo-row"));
    expect(screen.queryByTestId("scm-message")).toBeNull();
    expect(screen.queryByTestId("scm-file")).toBeNull();
    fireEvent.click(screen.getByTestId("scm-repo-row"));
    expect(await screen.findByTestId("scm-message")).toBeTruthy();
  });

  it("narrows the list to the files one session wrote, picked from the filter", async () => {
    render(<GitOverviewTab />);
    await screen.findByText("app.py");
    fireEvent.click(screen.getByTestId("scm-session-filter"));
    await vi.waitFor(() => expect(screen.getAllByTestId("scm-quick-pick-item").length).toBe(3));
    const items = screen.getAllByTestId("scm-quick-pick-item");
    expect(items.map((item) => item.textContent)).toEqual([expect.stringContaining("All Changes"), expect.stringContaining("T1 · Claude Code"), expect.stringContaining("T2 · Codex")]);
    fireEvent.click(items[2]);
    const files = await screen.findAllByTestId("scm-session-file");
    expect(files.map((file) => [file.dataset.path, file.dataset.letter])).toEqual([["src/widget.ts", "A"], ["app.py", "M"]]);
    expect(screen.getByTestId("scm-session-row").textContent).toContain("T2 · Codex");
    expect(screen.getByTestId("scm-session-count").textContent).toBe("2");
    expect(screen.queryByTestId("scm-file")).toBeNull();
    // Only the pending file can be staged; the committed one is history.
    expect(within(files[0]).queryByTestId("scm-session-stage")).toBeNull();
    fireEvent.click(within(files[1]).getByTestId("scm-session-stage"));
    await vi.waitFor(() => expect(posted("scm/stage")).toEqual([{ workspace_id: "w1", paths: ["app.py"] }]));
    // A file in the shared folder opens in the editor's diff, against the code before the session.
    fireEvent.click(files[0]);
    const editor = useCodeEditorStore.getState();
    expect(editor.tabs.map((tab) => [tab.path, tab.mode])).toEqual([["src/widget.ts", "diff"]]);
    expect(editor.diffBases[editor.tabs[0].fileKey]?.ref).toBe("b0b0b0b0b0b0");
    expect(screen.queryByTestId("scm-diff-dialog")).toBeNull();
    fireEvent.click(screen.getByTestId("scm-session-clear"));
    expect(await screen.findByText("notes.txt")).toBeTruthy();
    expect(screen.queryByTestId("scm-session")).toBeNull();
  });

  it("opens straight on a session when its pane asks", async () => {
    render(<GitOverviewTab />);
    await screen.findByText("app.py");
    act(() => useGitSessionStore.getState().show("w1", "T2"));
    expect((await screen.findAllByTestId("scm-session-file")).length).toBe(2);
    // The ask is used up: the tab opened again later starts on every change.
    expect(useGitSessionStore.getState().request).toBeNull();
    cleanup();
    render(<GitOverviewTab />);
    expect(await screen.findByText("app.py")).toBeTruthy();
    expect(screen.queryByTestId("scm-session")).toBeNull();
  });
});

describe("GitOverviewTab — following main", () => {
  it("turns following main on from the more menu and shows its state in the title", async () => {
    render(<GitOverviewTab />);
    fireEvent.click(await screen.findByTestId("scm-title-more"));
    expect(screen.queryByTestId("scm-follow-status")).toBeNull();
    fireEvent.click(await screen.findByTestId("scm-menu-follow-main"));
    await vi.waitFor(() => expect(follow.enabled).toBe(true));
    expect(await screen.findByTestId("scm-follow-status")).toBeTruthy();
  });
});

describe("GitOverviewTab — graph", () => {
  it("draws the history with branch and tag badges and opens a commit's files", async () => {
    render(<GitOverviewTab />);
    const commits = await screen.findAllByTestId("scm-graph-commit");
    expect(commits.map((element) => element.textContent)).toEqual([expect.stringContaining("feat: second"), expect.stringContaining("feat: first")]);
    expect(within(commits[0]).getAllByTestId("scm-graph-ref").map((badge) => badge.getAttribute("aria-label"))).toEqual(["main", "origin/main"]);
    expect(within(commits[1]).getByTestId("scm-graph-ref").dataset.kind).toBe("tag");
    fireEvent.click(commits[0]);
    expect((await screen.findByTestId("scm-graph-file")).textContent).toContain("x.ts");
    fireEvent.click(screen.getByTestId("scm-graph-file"));
    expect(await screen.findByTestId("scm-diff-dialog")).toBeTruthy();
    await act(async () => {
      fireEvent.click(screen.getByTestId("scm-diff-close"));
    });
    expect(screen.queryByTestId("scm-diff-dialog")).toBeNull();
  });

  it("creates a branch at a commit from its menu", async () => {
    render(<GitOverviewTab />);
    const [top] = await screen.findAllByTestId("scm-graph-commit");
    fireEvent.contextMenu(top);
    fireEvent.click(await screen.findByTestId("scm-menu-create-branch"));
    const box = await screen.findByTestId("scm-quick-input-box");
    fireEvent.change(box, { target: { value: "feature/here" } });
    fireEvent.keyDown(box, { key: "Enter" });
    await vi.waitFor(() =>
      expect(posted("scm/branch/create")).toEqual([{ workspace_id: "w1", name: "feature/here", start: "c2c2c2c2c2c2", switch: true }]),
    );
  });
});
