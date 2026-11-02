import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { AgentChatSession } from "@/lib/agentChatApi";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { useNavSidebarStore } from "@/store/navSidebar";

vi.mock("../PaneChangesDialog", () => ({
  PaneChangesDialog: ({ open, folder, title }: { open: boolean; folder: string; title: string }) =>
    open ? <div data-testid="thread-changes" data-folder={folder}>{title}</div> : null,
}));

const badges = vi.hoisted(() => ({ github: { status: null as unknown, pending: false }, gate: null as unknown }));
vi.mock("../useSessionGitHub", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../useSessionGitHub")>()),
  useThreadGitHub: () => badges.github,
}));
vi.mock("../usePaneDoneGate", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../usePaneDoneGate")>()),
  usePaneDoneGate: () => badges.gate,
}));

import { ThreadHeader } from "./ThreadHeader";
import { useThreadChatStore } from "./threadModel";

const SESSION = {
  session_id: "s1",
  title: "Fix the login",
  cli_title: "",
  provider: "claude-api",
  cwd: "/repo",
  running: false,
  pending_approvals: [],
} as unknown as AgentChatSession;

describe("ThreadHeader", () => {
  beforeEach(() => {
    useNavSidebarStore.setState({ collapsed: false });
    useThreadChatStore.setState({ sessions: [] });
    badges.github = { status: null, pending: false };
    badges.gate = null;
  });
  afterEach(cleanup);

  it("offers the grid pane's controls for the open thread", () => {
    render(<ThreadHeader session={SESSION} projectId="p1" folder="/repo" workspaceId="w1" />);
    expect(screen.getByTestId("thread-header-title").textContent).toBe("Fix the login");
    for (const id of ["review-changes", "show-in-git", "more", "maximize", "new", "close"]) {
      expect(screen.getByTestId(`thread-header-${id}`)).toBeTruthy();
    }
  });

  it("reviews the changes in the thread's folder", () => {
    render(<ThreadHeader session={SESSION} projectId="p1" folder="/repo/wt" workspaceId="w1" />);
    fireEvent.click(screen.getByTestId("thread-header-review-changes"));
    expect(screen.getByTestId("thread-changes").getAttribute("data-folder")).toBe("/repo/wt");
  });

  it("opens the Git tab, folds the sidebar, starts and closes threads", () => {
    const openTab = vi.spyOn(useIdeSidePanelStore.getState(), "openTab").mockImplementation(() => {});
    const newThread = vi.spyOn(useIdeThreadsStore.getState(), "newThread").mockImplementation(() => {});
    const archive = vi.spyOn(useIdeThreadsStore.getState(), "archiveThread").mockImplementation(() => {});
    render(<ThreadHeader session={SESSION} projectId="p1" folder="/repo" workspaceId="w1" />);

    fireEvent.click(screen.getByTestId("thread-header-show-in-git"));
    expect(openTab).toHaveBeenCalledWith("git");

    fireEvent.click(screen.getByTestId("thread-header-maximize"));
    expect(useNavSidebarStore.getState().collapsed).toBe(true);
    fireEvent.click(screen.getByTestId("thread-header-maximize"));
    expect(useNavSidebarStore.getState().collapsed).toBe(false);

    fireEvent.click(screen.getByTestId("thread-header-new"));
    expect(newThread).toHaveBeenCalledWith("p1");

    fireEvent.click(screen.getByTestId("thread-header-close"));
    expect(archive).toHaveBeenCalledWith("s1");
  });

  it("does not close a thread that is still working", () => {
    render(<ThreadHeader session={{ ...SESSION, running: true } as AgentChatSession} projectId="p1" folder="/repo" workspaceId="w1" />);
    expect((screen.getByTestId("thread-header-close") as HTMLButtonElement).disabled).toBe(true);
  });

  it("names the thread the way the sidebar does: the coding CLI's own title", () => {
    useThreadChatStore.setState({ sessions: [{ ...SESSION, cli_title: "Thread header polish" } as AgentChatSession] });
    render(<ThreadHeader session={{ ...SESSION, title: "Hello, I would like you to ..." } as AgentChatSession} projectId="p1" folder="/repo" workspaceId="w1" />);
    expect(screen.getByTestId("thread-header-title").textContent).toBe("Thread header polish");
  });

  it("shows the branch's GitHub state and the done gate's verdict like a pane", () => {
    badges.github = {
      status: {
        repo: "acme/app", branch: "feat/x", url: "https://github.com/acme/app/pull/7", published: true, owned: true,
        available: true, reason: "", fetched_at: Date.now() / 1000, state: "open", number: 7,
        ci: { state: "success" }, ci_stale: false,
      },
      pending: false,
    };
    badges.gate = { verdict: "WAIT", reason: "CI is running", next: "", pr: 7, branch: "feat/x", at: "", matched: "session" };
    render(<ThreadHeader session={SESSION} projectId="p1" folder="/repo" workspaceId="w1" />);
    expect(screen.getByTestId("session-github-status").getAttribute("href")).toBe("https://github.com/acme/app/pull/7");
    expect(screen.getByTestId("pane-done-gate-Fix the login").getAttribute("data-verdict")).toBe("WAIT");
  });
});
