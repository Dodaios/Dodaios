import { act, cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgentsOverview } from "./AgentsOverview";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { usePaneRecapsStore } from "@/store/paneRecaps";
import { usePaneReviewsStore } from "@/store/paneReviews";
import { resetWorkspacePanesPoll, useWorkspacePanesStore } from "@/store/workspacePanes";
import type { AgentChatSession } from "@/lib/agentChatApi";
import type { IdeProject, TerminalRecap, WorkspacePaneRow } from "@/lib/agenticIdeApi";
import { useThreadChatStore } from "../threads/threadModel";
import type { GitHubTarget, SessionGitHubStatus } from "../useSessionGitHub";
import type { AgentSearchRequest, AgentSearchResponse } from "./agentSearch";

// What GitHub says about each thread (`thread:<id>`) and pane (`<workspace>/<pane>`).
const github = vi.hoisted(() => ({ statuses: {} as Record<string, unknown>, quiet: [] as string[] }));
const opened = vi.hoisted(() => ({ urls: [] as string[] }));

vi.mock("../useSessionGitHub", async (original) => {
  const actual = await original<typeof import("../useSessionGitHub")>();
  const name = (target: Pick<GitHubTarget, "key" | "pane">) =>
    target.key.startsWith("thread:") ? target.key : `${target.key}/${target.pane}`;
  const reading = (target: Pick<GitHubTarget, "key" | "pane">) => ({
    status: (github.statuses[name(target)] ?? null) as SessionGitHubStatus | null,
    pending: false, answered: name(target) in github.statuses, readAt: 5_000,
  });
  return {
    ...actual,
    peekGitHubReading: reading,
    useGitHubReadings: (targets: GitHubTarget[]) => {
      github.quiet = targets.filter((target) => target.quiet).map(name);
      return new Map(targets.map((target) => [actual.gitHubTargetId(target), reading(target)]));
    },
  };
});

vi.mock("./browser/ideBrowserLinks", () => ({
  openLinkInIdeBrowser: async (url: string) => { opened.urls.push(url); return true; },
}));

function pane(name: string, workspaceId: string, overrides: Partial<WorkspacePaneRow> = {}): WorkspacePaneRow {
  return {
    workspace_id: workspaceId,
    workspace_name: workspaceId,
    folder: "/code/app",
    workspace_active: workspaceId === "w1",
    key: name,
    history_id: `${name}@${workspaceId}`,
    name,
    agent: "claude",
    display_name: "Claude Code",
    accepts_prompts: true,
    status: "live",
    exit_code: null,
    activity: "working",
    activity_since: 0,
    worked: true,
    started_at: 1,
    last_output_at: 2,
    last_prompt: "",
    last_prompt_at: null,
    recap: "",
    has_resume: false,
    readable: true,
    account: null,
    account_label: null,
    archived: false,
    ...overrides,
  };
}

function thread(id: string, overrides: Partial<AgentChatSession> = {}): AgentChatSession {
  return {
    session_id: id,
    title: `Thread ${id}`,
    provider: "claude-code",
    model: "",
    effort: "",
    cwd: "/code/app",
    permission_mode: "",
    surface: "agent",
    vendor_session: null,
    created_ms: 1_000,
    updated_ms: 1_000,
    last_message_ms: 1_000,
    message_count: 2,
    preview: "",
    running: false,
    ...overrides,
  };
}

function request(number: number, overrides: Partial<SessionGitHubStatus> = {}): SessionGitHubStatus {
  return {
    repo: "owner/repo", branch: `feat/${number}`, url: `https://github.com/owner/repo/pull/${number}`,
    owned: true, published: true, available: true, reason: "", fetched_at: 1, state: "open", number,
    title: `Change ${number}`, additions: 12, deletions: 3,
    ci_stale: false, merge_status: "blocked", review: "",
    ci: { state: "success", url: "", total: 1, passed: 1, failed: 0, pending: 0, running: 0, names: [], commit: "" },
    ...overrides,
  };
}

const project = (id: string, path: string, workspaces: string[]): IdeProject => ({
  id, name: id === "p1" ? "App" : "Blog", path, pinned: false, archived: false, scratch: false,
  workspaces: workspaces.map((workspace) => ({ id: workspace, name: workspace, folder: path, status: "open" })),
} as unknown as IdeProject);

const setThreads = (sessions: AgentChatSession[]) => act(() => useThreadChatStore.setState({ sessions }));

beforeEach(() => {
  localStorage.clear();
  github.statuses = {};
  github.quiet = [];
  opened.urls = [];
  resetWorkspacePanesPoll();
  useIdeSidePanelStore.setState({ spotlight: null });
  usePaneReviewsStore.setState({ reviewed: {} });
  usePaneRecapsStore.setState({ workspaceId: null, byName: {}, load: async () => {} });
  useWorkspacePanesStore.setState({ panes: [], activeId: "w1", loaded: true, load: async () => {} });
  useIdeProjectsStore.setState({
    projects: [project("p1", "/code/app", ["w1", "w2"]), project("p2", "/code/blog", ["w3"])],
    activeWorkspaceId: "w1",
    pendingWorkspaceId: null,
    refreshRequest: null,
    action: null,
  });
  useIdeThreadsStore.setState({
    layout: "threads", selection: { projectId: "p1", sessionId: null }, projectOf: {}, seen: {}, archived: {}, split: [], mainAt: 0,
  });
  useThreadChatStore.setState({
    sessions: [],
    activeSessionId: null,
    catalog: { providers: [{ id: "claude-code", agent: "claude", label: "Claude Code" }] } as never,
    catalogStale: false,
    loadCatalog: async () => {},
    loadSessions: async () => {},
  });
  useIdeChatStore.setState({
    paneRequest: null,
    stagedPane: null,
    workspaces: [],
    agents: [],
    terminalRequest: null,
    newChatRequest: null,
    workspaceRequest: null,
    sessionRequest: null,
    addWorkspaceRequest: null,
  });
});

afterEach(cleanup);

const column = (id: string) => screen.getByTestId(`ide-agents-column-${id}`);
const cards = (root: ParentNode = document) =>
  Array.from(root.querySelectorAll<HTMLElement>('[data-testid="ide-agent-card"]'));
const idsIn = (id: string) => cards(column(id)).map((card) => card.getAttribute("data-item"));
const cardOf = (item: string) => document.querySelector<HTMLElement>(`[data-item="${item}"]`)!;
const open = (item: string) => fireEvent.click(cardOf(item).querySelector('[data-testid="ide-agent-title"]')!);

describe("AgentsOverview board", () => {
  it("stands each thread in the column its pull request puts it in", () => {
    useThreadChatStore.setState({ sessions: [
      thread("plain"),
      thread("checks"),
      thread("review"),
      thread("ready"),
      thread("merged"),
    ] });
    github.statuses = {
      "thread:checks": request(11, { ci: { ...request(1).ci, state: "running" } }),
      "thread:review": request(12),
      "thread:ready": request(13, { merge_status: "clean" }),
      "thread:merged": request(14, { state: "merged" }),
    };
    render(<AgentsOverview />);
    expect(idsIn("building")).toEqual(["thread:plain"]);
    expect(idsIn("checks")).toEqual(["thread:checks"]);
    expect(idsIn("review")).toEqual(["thread:review"]);
    expect(idsIn("ready")).toEqual(["thread:ready"]);
    expect(screen.getByTestId("ide-agents-column-count-review").textContent).toBe("1");
    const order = Array.from(document.querySelectorAll("section[data-testid^='ide-agents-column-']"))
      .map((node) => node.getAttribute("data-testid"));
    expect(order).toEqual([
      "ide-agents-column-building", "ide-agents-column-checks", "ide-agents-column-review", "ide-agents-column-ready",
    ]);
    // Merged work is out of the columns, folded at the foot.
    expect(cardOf("thread:merged")).toBeNull();
    expect(screen.getByTestId("ide-agents-finished").textContent).toContain("1");
    fireEvent.click(screen.getByTestId("ide-agents-finished"));
    expect(cards(screen.getByTestId("ide-agents-finished-list")).map((card) => card.getAttribute("data-item"))).toEqual(["thread:merged"]);
    expect(cardOf("thread:merged").querySelector('[data-testid="ide-agent-state"]')?.textContent).toBe("Merged");
  });

  it("shows the agent's mark, the goal, where the work lives and the state on a card", () => {
    useThreadChatStore.setState({ sessions: [
      thread("a", { title: "Fix the login flow", running: true, cwd: "/code/app/.worktrees/login" }),
      thread("b", { title: "Rename the label" }),
    ] });
    github.statuses = {
      "thread:a": request(0, { state: "branch", number: null, branch: "fix/login" }),
      "thread:b": request(21, { others: [request(20, { state: "merged" })] }),
    };
    render(<AgentsOverview />);
    const a = cardOf("thread:a");
    expect(a.querySelector('[data-testid="ide-agent-title"]')?.textContent).toBe("Fix the login flow");
    expect(a.querySelector('[data-testid="agent-mark-claude"]')).not.toBeNull();
    expect(a.querySelector('[data-testid="ide-agent-branch"]')?.textContent).toBe("fix/login");
    expect(a.querySelector('[data-testid="ide-agent-state"]')?.textContent).toBe("Working");
    expect(a.getAttribute("data-activity")).toBe("working");
    // With pull requests the card names them instead of the branch, the open one first.
    const b = cardOf("thread:b");
    expect(b.querySelector('[data-testid="ide-agent-branch"]')).toBeNull();
    expect(Array.from(b.querySelectorAll('[data-testid^="ide-agent-pr-"]')).map((chip) => chip.textContent)).toEqual(["#21", "#20"]);
    expect(b.querySelector('[data-testid="ide-agent-state"]')?.textContent).toBe("Awaiting review");
  });

  it("names the worktree while GitHub knows no branch", () => {
    useThreadChatStore.setState({ sessions: [thread("a", { cwd: "/code/app/.worktrees/login" })] });
    render(<AgentsOverview />);
    expect(cardOf("thread:a").querySelector('[data-testid="ide-agent-branch"]')?.textContent).toBe("login");
  });

  it("opens a pull request from its chip without opening the thread", () => {
    useThreadChatStore.setState({ sessions: [thread("a")] });
    github.statuses = { "thread:a": request(21) };
    render(<AgentsOverview />);
    fireEvent.click(screen.getByTestId("ide-agent-pr-21"));
    expect(opened.urls).toEqual(["https://github.com/owner/repo/pull/21"]);
    expect(useIdeThreadsStore.getState().selection.sessionId).toBeNull();
  });

  it("opens the thread of a clicked card in the thread layout", () => {
    useIdeThreadsStore.setState({ layout: "grid" });
    useThreadChatStore.setState({ sessions: [thread("a")] });
    render(<AgentsOverview />);
    open("thread:a");
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(useIdeThreadsStore.getState().selection).toMatchObject({ projectId: "p1", sessionId: "a" });
    expect(cardOf("thread:a").querySelector('[data-testid="ide-agent-title"]')?.getAttribute("aria-current")).toBe("true");
  });

  it("leads a column with the thread that asks, then the ones at work", () => {
    useThreadChatStore.setState({ sessions: [
      thread("idle", { last_message_ms: 9_000 }),
      thread("busy", { running: true, last_message_ms: 2_000 }),
      thread("asks", { pending_questions: ["q1"], last_message_ms: 1_000 }),
    ] });
    render(<AgentsOverview />);
    expect(idsIn("building")).toEqual(["thread:asks", "thread:busy", "thread:idle"]);
    const state = cardOf("thread:asks").querySelector('[data-testid="ide-agent-state"]')!;
    expect(state.textContent).toBe("Needs your answer");
    expect(state.getAttribute("data-tone")).toBe("attention");
  });

  it("marks a thread with a reply nobody has read", () => {
    useIdeThreadsStore.setState({ seen: { a: 500 } });
    useThreadChatStore.setState({ sessions: [thread("a", { updated_ms: 900 })] });
    render(<AgentsOverview />);
    const state = cardOf("thread:a").querySelector('[data-testid="ide-agent-state"]')!;
    expect(state.textContent).toBe("New reply");
    expect(state.getAttribute("data-tone")).toBe("building");
  });

  it("leaves out archived threads and team members, and archives from the card", () => {
    useIdeThreadsStore.setState({ archived: { gone: 1 } });
    useThreadChatStore.setState({ sessions: [thread("gone"), thread("member", { team_id: "t1" }), thread("kept"), thread("busy", { running: true })] });
    render(<AgentsOverview />);
    expect(idsIn("building")).toEqual(["thread:busy", "thread:kept"]);
    // A thread at work stays in sight: it has no archive action.
    expect(cardOf("thread:busy").querySelector('[data-testid="ide-agent-archive"]')).toBeNull();
    fireEvent.click(cardOf("thread:kept").querySelector('[data-testid="ide-agent-archive"]')!);
    expect("kept" in useIdeThreadsStore.getState().archived).toBe(true);
    expect(idsIn("building")).toEqual(["thread:busy"]);
  });

  it("starts with the newest threads and shows the older ones on request", () => {
    const many = Array.from({ length: 45 }, (_, index) => thread(`t${index}`, { last_message_ms: 10_000 - index }));
    // An old thread that still works is never left out.
    many[44] = thread("t44", { last_message_ms: 1, running: true });
    useThreadChatStore.setState({ sessions: many });
    render(<AgentsOverview />);
    expect(cards()).toHaveLength(41);
    expect(cardOf("thread:t44")).not.toBeNull();
    expect(screen.getByTestId("ide-agents-scope-count-project").textContent).toBe("45");
    fireEvent.click(screen.getByTestId("ide-agents-older"));
    expect(cards()).toHaveLength(45);
    expect(screen.queryByTestId("ide-agents-older")).toBeNull();
  });

  it("stops asking GitHub about a resting thread whose pull requests are finished", () => {
    useThreadChatStore.setState({ sessions: [
      thread("merged", { updated_ms: 1_000 }),
      thread("open", { updated_ms: 1_000 }),
      thread("moved", { updated_ms: 9_000 }),
    ] });
    github.statuses = {
      "thread:merged": request(1, { state: "merged" }),
      "thread:open": request(2),
      "thread:moved": request(3, { state: "merged" }),
    };
    render(<AgentsOverview />);
    expect(github.quiet).toEqual(["thread:merged"]);
  });

  it("lists the project in view by default and every project on request", () => {
    useThreadChatStore.setState({ sessions: [thread("app"), thread("blog", { cwd: "/code/blog" }), thread("elsewhere", { cwd: "/tmp/x" })] });
    const { unmount } = render(<AgentsOverview />);
    expect(screen.getByTestId("ide-agents-scope-project").getAttribute("aria-checked")).toBe("true");
    expect(cards().map((card) => card.getAttribute("data-item"))).toEqual(["thread:app"]);
    expect(cardOf("thread:app").querySelector('[data-testid="ide-agent-project"]')).toBeNull();
    expect(screen.getByTestId("ide-agents-scope-count-project").textContent).toBe("1");
    expect(screen.getByTestId("ide-agents-scope-count-all").textContent).toBe("2");

    fireEvent.click(screen.getByTestId("ide-agents-scope-all"));
    expect(cards().map((card) => card.getAttribute("data-item")).sort()).toEqual(["thread:app", "thread:blog"]);
    expect(cardOf("thread:blog").querySelector('[data-testid="ide-agent-project"]')?.textContent).toBe("Blog");
    unmount();

    render(<AgentsOverview />);
    expect(screen.getByTestId("ide-agents-scope-all").getAttribute("aria-checked")).toBe("true");
    expect(cards()).toHaveLength(2);
  });

  it("follows the project of the open thread, and the front workspace's in the grid", () => {
    useThreadChatStore.setState({ sessions: [thread("app"), thread("blog", { cwd: "/code/blog" })] });
    useIdeThreadsStore.setState({ selection: { projectId: "p2", sessionId: null } });
    const { rerender } = render(<AgentsOverview />);
    expect(cards().map((card) => card.getAttribute("data-item"))).toEqual(["thread:blog"]);
    act(() => useIdeThreadsStore.setState({ layout: "grid" }));
    rerender(<AgentsOverview />);
    expect(cards().map((card) => card.getAttribute("data-item"))).toEqual(["thread:app"]);
  });

  it("starts a new thread in the project in view", () => {
    useIdeThreadsStore.setState({ layout: "grid", selection: { projectId: "p1", sessionId: "x" } });
    render(<AgentsOverview />);
    fireEvent.click(screen.getByTestId("ide-agents-new-thread"));
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(useIdeThreadsStore.getState().selection).toEqual({ projectId: "p1", sessionId: null });
  });

  it("asks for a project when none is known", () => {
    useIdeProjectsStore.setState({ projects: [], activeWorkspaceId: null });
    render(<AgentsOverview />);
    expect(screen.getByTestId("ide-workspace-agents").textContent).toContain("Open a project");
    expect(screen.queryByTestId("ide-agents-board")).toBeNull();
  });

  it("shows a loading state before the first answer", () => {
    useWorkspacePanesStore.setState({ panes: [], loaded: false });
    render(<AgentsOverview />);
    expect(screen.getByTestId("ide-agents-loading")).toBeTruthy();
    setThreads([thread("a")]);
    expect(screen.queryByTestId("ide-agents-loading")).toBeNull();
  });
});

describe("AgentsOverview terminal agents", () => {
  beforeEach(() => {
    useWorkspacePanesStore.setState({
      panes: [
        pane("T1", "w1", { activity: "working" }),
        pane("T2", "w1", { activity: "asking", agent: "codex", display_name: "Codex" }),
        pane("T3", "w1", { activity: "waiting", agent: "opencode", display_name: "opencode" }),
        pane("T1", "w3", { activity: "working", folder: "/code/blog" }),
        pane("S1", "w1", { agent: "shell" }),
        pane("T9", "w1", { archived: true }),
      ],
    });
  });

  it("lists the project's terminal agents as cards beside its threads", () => {
    usePaneRecapsStore.setState({
      workspaceId: "w1",
      byName: { T2: { recap: "Login flow — flaky tests", source: "model" } as TerminalRecap },
    });
    useThreadChatStore.setState({ sessions: [thread("a", { last_message_ms: 1 })] });
    github.statuses = { "w1/T1": request(31, { merge_status: "clean" }) };
    render(<AgentsOverview />);
    // The one that asks leads; shells, archived panes and other projects are left out.
    expect(idsIn("building")).toEqual(["pane:T2@w1", "pane:T3@w1", "thread:a"]);
    expect(idsIn("ready")).toEqual(["pane:T1@w1"]);
    const t2 = cardOf("pane:T2@w1");
    expect(t2.querySelector('[data-testid="ide-agent-title"]')?.textContent).toBe("Login flow — flaky tests");
    expect(t2.querySelector('[data-testid="agent-mark-codex"]')).not.toBeNull();
    expect(t2.querySelector('[data-testid="ide-agent-terminal"]')?.textContent).toBe("w1 · T2");
    expect(t2.querySelector('[data-testid="ide-agent-state"]')?.textContent).toBe("Needs input");
    expect(cardOf("pane:T1@w1").querySelector('[data-testid="ide-agent-state"]')?.textContent).toBe("Working");
  });

  it("brings a clicked terminal forward and counts the click as a look", () => {
    render(<AgentsOverview />);
    const state = () => cardOf("pane:T3@w1").querySelector('[data-testid="ide-agent-state"]')!;
    expect(state().getAttribute("data-tone")).toBe("building");
    open("pane:T3@w1");
    expect(useIdeChatStore.getState().paneRequest).toMatchObject({ workspaceId: "w1", pane: "T3" });
    expect(useIdeSidePanelStore.getState().spotlight).toEqual({ workspaceId: "w1", pane: "T3" });
    expect(usePaneReviewsStore.getState().reviewed["T3@w1"]).toBeGreaterThan(0);
    expect(state().getAttribute("data-tone")).toBe("quiet");
  });

  it("marks the card whose terminal is spotlit, and a failed one red", () => {
    useIdeSidePanelStore.setState({ spotlight: { workspaceId: "w1", pane: "T2" } });
    useWorkspacePanesStore.setState({
      panes: [pane("T1", "w1", { status: "error", activity: "" }), pane("T2", "w1", { activity: "asking" })],
    });
    render(<AgentsOverview />);
    expect(cardOf("pane:T2@w1").querySelector('[data-testid="ide-agent-title"]')?.getAttribute("aria-current")).toBe("true");
    expect(cardOf("pane:T1@w1").querySelector('[data-testid="ide-agent-title"]')?.getAttribute("aria-current")).toBeNull();
    expect(cardOf("pane:T1@w1").querySelector('[data-testid="ide-agent-state"]')?.getAttribute("data-tone")).toBe("danger");
  });

  it("lists the front workspace's folder while the projects are not known yet", () => {
    useIdeProjectsStore.setState({ projects: [] });
    render(<AgentsOverview />);
    expect(cards().map((card) => card.getAttribute("data-pane")).sort()).toEqual(["T1", "T2", "T3"]);
  });

  it("asks before it stops every agent", () => {
    render(<AgentsOverview />);
    fireEvent.click(screen.getByTestId("ide-agents-stop-all"));
    expect(screen.getByTestId("ide-agents-stop-confirm")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByTestId("ide-agents-stop-confirm")).toBeNull();
  });
});

describe("AgentsOverview hybrid search", () => {
  class SearchWorker {
    static latest: SearchWorker;
    messages: AgentSearchRequest[] = [];
    onmessage: ((event: MessageEvent<AgentSearchResponse>) => void) | null = null;
    constructor() { SearchWorker.latest = this; }
    postMessage(message: AgentSearchRequest) { this.messages.push(message); }
    terminate() {}
    reply(response: Omit<AgentSearchResponse, "id"> & { matches?: { id: string; score: number }[] }) {
      this.onmessage?.({ data: { ...response, id: this.messages.at(-1)!.id } } as MessageEvent<AgentSearchResponse>);
    }
  }
  beforeEach(() => {
    vi.useFakeTimers();
    vi.stubGlobal("Worker", SearchWorker);
    useWorkspacePanesStore.setState({ panes: [
      pane("T1", "w1", { recap: "Login", last_prompt: "Renew tokens", activity: "working" }),
      pane("T2", "w1", { recap: "Plugin auth", activity: "waiting" }),
      pane("T1", "w3", { recap: "External login", folder: "/code/blog" }),
    ] });
  });
  afterEach(() => { vi.useRealTimers(); vi.unstubAllGlobals(); });
  const search = () => {
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "fix expired sign-ins" } });
    act(() => vi.advanceTimersByTime(300));
    return SearchWorker.latest;
  };

  it("shows keyword and typo hits immediately, in threads and terminals alike", () => {
    useWorkspacePanesStore.setState({ panes: [pane("T1", "w1", { recap: "OAuth reconnect" })] });
    useThreadChatStore.setState({ sessions: [thread("a", { title: "Security audit" })] });
    render(<AgentsOverview />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "OAuth" } });
    expect(cards().map((card) => card.getAttribute("data-item"))).toEqual(["pane:T1@w1"]);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "securty" } });
    expect(cards().map((card) => card.getAttribute("data-item"))).toEqual(["thread:a"]);
    expect(screen.queryByTestId("ide-agents-board")).toBeNull();
  });

  it("keeps concrete results visible when related tasks are loading or unavailable", () => {
    useWorkspacePanesStore.setState({ panes: [pane("T1", "w1", { recap: "Renew expired logins" })] });
    render(<AgentsOverview />);
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "expired logins" } });
    expect(cards()).toHaveLength(1);
    act(() => vi.advanceTimersByTime(300));
    act(() => SearchWorker.latest.reply({ type: "loading" }));
    expect(cards()).toHaveLength(1);
    act(() => SearchWorker.latest.reply({ type: "error" }));
    expect(cards()).toHaveLength(1);
    expect(screen.getByRole("status").textContent).toContain("Word search still works");
    open("pane:T1@w1");
    expect(useIdeChatStore.getState().paneRequest).toMatchObject({ workspaceId: "w1", pane: "T1" });
  });

  it("searches task text within the chosen scope and ranks the best match first", () => {
    useThreadChatStore.setState({ sessions: [thread("a", { title: "Sign-in expiry", preview: "Tokens run out early" })] });
    render(<AgentsOverview />);
    const worker = search();
    expect(worker.messages.at(-1)).toMatchObject({ documents: [
      { id: "pane:T1@w1", texts: ["Login", "Renew tokens"] },
      { id: "pane:T2@w1", texts: ["Plugin auth"] },
      { id: "thread:a", texts: ["Sign-in expiry", "Tokens run out early"] },
    ] });
    act(() => worker.reply({ type: "result", matches: [
      { id: "thread:a", score: 0.9 }, { id: "pane:T2@w1", score: 0.8 }, { id: "pane:T1@w1", score: 0.7 },
    ] }));
    expect(cards().map((card) => card.getAttribute("data-item"))).toEqual(["thread:a", "pane:T2@w1", "pane:T1@w1"]);
    expect(screen.queryByTestId("ide-agents-column-building")).toBeNull();
  });

  it("shows no unrelated cards while loading, on no match, or on a failed search", () => {
    render(<AgentsOverview />);
    const worker = search();
    expect(cards()).toHaveLength(0);
    act(() => worker.reply({ type: "loading" }));
    expect(screen.getByRole("status").textContent).toContain("downloading");
    act(() => worker.reply({ type: "result", matches: [] }));
    expect(screen.getByRole("status").textContent).toBe("No matching agents.");
    expect(cards()).toHaveLength(0);
    act(() => worker.reply({ type: "error" }));
    expect(screen.getByRole("button", { name: "Try again" })).toBeTruthy();
    expect(cards()).toHaveLength(0);
  });

  it("restores the board with clear or Escape", () => {
    render(<AgentsOverview />);
    search();
    fireEvent.click(screen.getByRole("button", { name: "Clear search" }));
    expect(cards()).toHaveLength(2);
    search();
    fireEvent.keyDown(screen.getByRole("searchbox"), { key: "Escape" });
    expect(cards()).toHaveLength(2);
  });

  it("widens the search with the scope and still opens another project's terminal", () => {
    render(<AgentsOverview />);
    const worker = search();
    fireEvent.click(screen.getByTestId("ide-agents-scope-all"));
    act(() => vi.advanceTimersByTime(300));
    expect(worker.messages.at(-1)).toMatchObject({ documents: expect.arrayContaining([expect.objectContaining({ id: "pane:T1@w3" })]) });
    act(() => worker.reply({ type: "result", matches: [{ id: "pane:T1@w3", score: 0.9 }] }));
    open("pane:T1@w3");
    expect(useIdeChatStore.getState().paneRequest).toMatchObject({ workspaceId: "w3", pane: "T1" });
  });
});
