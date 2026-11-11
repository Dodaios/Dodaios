import { act, cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { IdeProject } from "@/lib/agenticIdeApi";
import type { GitRepoInfo } from "@/lib/gitApi";
import { useEventStore } from "@/store/events";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useIdeThreadsStore } from "@/store/ideThreads";

const git = vi.hoisted(() => ({ inspectGit: vi.fn(), prepareGit: vi.fn(), fetchLinkedRepos: vi.fn(), cloneGitHubRepo: vi.fn() }));
vi.mock("@/lib/gitApi", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/gitApi")>()), ...git }));
const github = vi.hoisted(() => ({ fetchGitHubRepos: vi.fn() }));
vi.mock("@/components/agentic/sidePanel/git/gitOverviewApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/components/agentic/sidePanel/git/gitOverviewApi")>()), ...github,
}));
const library = vi.hoisted(() => ({ openProject: vi.fn() }));
vi.mock("@/lib/chatLibraryApi", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/chatLibraryApi")>()), ...library }));
const ide = vi.hoisted(() => ({ fetchIdeProjects: vi.fn() }));
vi.mock("@/lib/agenticIdeApi", async (importOriginal) => ({ ...(await importOriginal<typeof import("@/lib/agenticIdeApi")>()), ...ide }));
const computers = vi.hoisted(() => ({ rows: [] as unknown[] }));
vi.mock("@/hooks/useComputers", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/hooks/useComputers")>()),
  useComputerChoiceList: () => ({ computers: computers.rows, loaded: true }),
}));
vi.mock("@/lib/teamThreadsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/teamThreadsApi")>()),
  useTeamThreads: () => ({ data: [] }),
}));

import { ThreadBranchBar } from "./ThreadBranchBar";
import { ThreadTree } from "./ThreadTree";

function projectRow(id: string, name: string, path: string): IdeProject {
  return { id, path, name, color: null, pinned: false, archived: false, scratch: false,
    created_at: 0, last_opened_at: 0, exists: true, chats: 0, workspaces: [] } as IdeProject;
}
const app = projectRow("p1", "Personal Jarvis", "C:\\Users\\me\\Desktop\\Personal Jarvis");
const notes = projectRow("p2", "Notes", "C:\\Users\\me\\Notes");

function repoInfo(extra: Partial<GitRepoInfo> = {}): GitRepoInfo {
  return { is_repo: true, is_worktree: false, branch: "main", dirty: false, default_branch: "main", main_root: app.path,
    branches: [{ name: "main", current: true, upstream: "", committed_at: 0, worktree: "" }], changes: [], remotes: [], ...extra } as GitRepoInfo;
}

function bar(extra: Partial<Parameters<typeof ThreadBranchBar>[0]> = {}) {
  const props = {
    folder: app.path, project: app, projects: [app, notes], onProject: vi.fn(), onConnect: vi.fn(),
    computerId: "", onComputer: vi.fn(), draft: true, checkout: "current" as const, onCheckout: vi.fn(),
    base: "", onBase: vi.fn(), locked: false, ...extra,
  };
  render(<ThreadBranchBar {...props} />);
  return props;
}

beforeEach(() => {
  localStorage.clear();
  computers.rows = [];
  git.inspectGit.mockReset().mockResolvedValue(repoInfo());
  git.fetchLinkedRepos.mockReset().mockResolvedValue({ p1: "octo/personal-jarvis" });
  git.cloneGitHubRepo.mockReset();
  github.fetchGitHubRepos.mockReset().mockResolvedValue({
    connected: true, source: "app", login: "octo", reason: "",
    repos: [
      { name: "octo/personal-jarvis", description: "", private: false, fork: false, url: "", pushed_at: "" },
      { name: "octo/blog", description: "the blog", private: true, fork: false, url: "", pushed_at: "" },
    ],
  });
  library.openProject.mockReset();
  ide.fetchIdeProjects.mockReset();
  useEventStore.setState({ toasts: [] });
});

afterEach(() => cleanup());

describe("ThreadBranchBar", () => {
  it("names the machine, the folder and the branch a new thread works in", async () => {
    bar();
    expect(screen.getByTestId("thread-machine").textContent).toContain("This computer");
    expect(screen.getByTestId("thread-folder").textContent).toContain("Personal Jarvis");
    expect(screen.getByTestId("thread-folder").getAttribute("title")).toBe(app.path);
    await waitFor(() => expect(screen.getByTestId("thread-branch").textContent).toContain("main"));
    expect(screen.queryByText("Current checkout")).toBeNull();
  });

  it("moves the new thread to another connected folder", async () => {
    const props = bar();
    fireEvent.click(screen.getByTestId("thread-folder"));
    fireEvent.click(await screen.findByRole("menuitem", { name: /Notes/ }));
    expect(props.onProject).toHaveBeenCalledWith("p2");
  });

  it("lists only the GitHub repositories that are not a connected folder yet", async () => {
    bar();
    fireEvent.click(screen.getByTestId("thread-folder"));
    expect(await screen.findByRole("menuitem", { name: /octo\/blog/ })).toBeTruthy();
    expect(screen.queryByRole("menuitem", { name: /octo\/personal-jarvis/ })).toBeNull();
    // The connected folder says which repository it is.
    expect(screen.getByRole("menuitem", { name: /Personal Jarvis/ }).textContent).toContain("Personal Jarvis");
    fireEvent.change(screen.getByTestId("thread-folder-search"), { target: { value: "zzz" } });
    expect(screen.queryByRole("menuitem", { name: /octo\/blog/ })).toBeNull();
    expect(screen.getByText("Nothing matches")).toBeTruthy();
  });

  it("downloads a picked GitHub repository, connects it and moves the new thread there", async () => {
    const blog = projectRow("p3", "blog", "C:\\Users\\me\\Dodaios\\blog");
    git.cloneGitHubRepo.mockResolvedValue({ folder: blog.path, repo: "octo/blog", created: true });
    library.openProject.mockResolvedValue(blog);
    ide.fetchIdeProjects.mockResolvedValue({ projects: [app, notes, blog], active_project_id: null, active_workspace_id: null });
    const props = bar();
    fireEvent.click(screen.getByTestId("thread-folder"));
    const row = await screen.findByRole("menuitem", { name: /octo\/blog/ });
    await act(async () => { fireEvent.click(row); });
    await waitFor(() => expect(props.onProject).toHaveBeenCalledWith("p3"));
    expect(git.cloneGitHubRepo).toHaveBeenCalledWith("octo/blog");
    expect(library.openProject).toHaveBeenCalledWith(blog.path, "blog");
    expect(useIdeProjectsStore.getState().projects.map((entry) => entry.id)).toEqual(["p1", "p2", "p3"]);
    expect(useEventStore.getState().toasts.at(-1)?.message).toContain(blog.path);
  });

  it("says why a repository could not be downloaded and stays where it was", async () => {
    git.cloneGitHubRepo.mockRejectedValue(new Error("Git could not download octo/blog: not found"));
    const props = bar();
    fireEvent.click(screen.getByTestId("thread-folder"));
    const row = await screen.findByRole("menuitem", { name: /octo\/blog/ });
    await act(async () => { fireEvent.click(row); });
    await waitFor(() => expect(useEventStore.getState().toasts.at(-1)?.message).toContain("not found"));
    expect(props.onProject).not.toHaveBeenCalled();
    expect(screen.getByTestId("thread-folder").textContent).toContain("Personal Jarvis");
  });

  it("offers to connect GitHub when it is not connected", async () => {
    github.fetchGitHubRepos.mockResolvedValue({ connected: false, source: "", login: "", repos: [], reason: "" });
    bar();
    fireEvent.click(screen.getByTestId("thread-folder"));
    expect(await screen.findByRole("menuitem", { name: /Connect GitHub/ })).toBeTruthy();
  });

  it("gives a new thread a worktree of its own with one press", async () => {
    const props = bar();
    const toggle = await screen.findByTestId("thread-worktree-toggle");
    expect(toggle.getAttribute("aria-pressed")).toBe("false");
    fireEvent.click(toggle);
    expect(props.onCheckout).toHaveBeenCalledWith("worktree");
  });

  it("picks a connected computer and offers to connect one", async () => {
    computers.rows = [{ id: "c1", name: "Build box", enabled: true, health: { status: "online" } }];
    const props = bar();
    fireEvent.click(screen.getByTestId("thread-machine"));
    expect(screen.getByRole("menuitem", { name: /Connect a computer/ })).toBeTruthy();
    fireEvent.click(screen.getByRole("menuitem", { name: /Build box/ }));
    expect(props.onComputer).toHaveBeenCalledWith("c1");
  });

  it("names the worktree a running thread works in and offers no folder change", async () => {
    const tree = `${app.path}\\.worktrees\\amber-otter`;
    git.inspectGit.mockResolvedValue(repoInfo({ is_worktree: true, branch: "amber-otter" }));
    bar({ folder: tree, draft: false, locked: true });
    await waitFor(() => expect(screen.getByTestId("thread-folder").textContent).toBe("Personal Jarvis · amber-otter"));
    expect(screen.getByTestId("thread-folder").tagName).toBe("SPAN");
    expect(screen.queryByTestId("thread-worktree-toggle")).toBeNull();
    expect((screen.getByTestId("thread-machine") as HTMLButtonElement).disabled).toBe(true);
  });
});

describe("ThreadTree", () => {
  it("opens a folded project when the new thread moves into it", async () => {
    localStorage.setItem("jarvis.ide.threadExpansion.v1", JSON.stringify({ p2: false }));
    useIdeProjectsStore.setState({ projects: [app, notes], activeWorkspaceId: null });
    useIdeThreadsStore.setState({ layout: "threads", selection: { projectId: "p1", sessionId: null }, projectOf: {}, seen: {}, archived: {}, focusNonce: 0 });
    render(<ThreadTree />);
    expect(screen.getAllByText("New thread").filter((node) => node.closest("[aria-current=page]"))).toHaveLength(1);
    act(() => useIdeThreadsStore.getState().newThread("p2"));
    await waitFor(() => expect(JSON.parse(localStorage.getItem("jarvis.ide.threadExpansion.v1") ?? "{}")).toEqual({ p2: true }));
    expect(screen.getAllByText("New thread").filter((node) => node.closest("[aria-current=page]"))).toHaveLength(1);
  });
});
