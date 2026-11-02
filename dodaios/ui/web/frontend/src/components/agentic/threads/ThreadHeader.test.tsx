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

import { ThreadHeader } from "./ThreadHeader";

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
});
