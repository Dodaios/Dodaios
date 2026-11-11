import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { AgentChatSession } from "@/lib/agentChatApi";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { ProjectThreadRows } from "./ProjectThreadRows";
import { useThreadChatStore } from "./threadModel";

const project = { id: "p1", path: "C:\\work\\app", name: "App", color: null, pinned: false, archived: false,
  scratch: false, created_at: 0, last_opened_at: 0, exists: true, chats: 0, workspaces: [] } as IdeProject;

function thread(id: string, updated: number, extra: Partial<AgentChatSession> = {}): AgentChatSession {
  return { session_id: id, title: `Thread ${id}`, cwd: project.path, updated_ms: updated, running: false, ...extra } as AgentChatSession;
}

beforeEach(() => {
  localStorage.clear();
  useIdeThreadsStore.setState({ layout: "grid", selection: { projectId: "", sessionId: null }, projectOf: {}, archived: {} });
});
afterEach(() => cleanup());

describe("ProjectThreadRows", () => {
  it("names a folder's newest threads and opens one on the thread face", () => {
    useThreadChatStore.setState({ sessions: [thread("a", 1), thread("b", 2)] });
    render(<ProjectThreadRows project={project} projects={[project]} />);
    const rows = screen.getAllByTestId(/^ide-project-thread-[ab]$/);
    expect(rows.map((row) => row.textContent)).toEqual(["Thread b", "Thread a"]);
    fireEvent.click(screen.getByTestId("ide-project-thread-a"));
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(useIdeThreadsStore.getState().selection).toMatchObject({ projectId: "p1", sessionId: "a" });
  });

  it("leaves archived threads and team members out, and folds a long list", () => {
    const many = Array.from({ length: 7 }, (_, index) => thread(`t${index}`, index + 1));
    useThreadChatStore.setState({ sessions: [...many, thread("old", 99), thread("member", 98, { team_id: "team" })] });
    useIdeThreadsStore.setState({ archived: { old: 1 } });
    render(<ProjectThreadRows project={project} projects={[project]} />);
    expect(screen.queryByTestId("ide-project-thread-old")).toBeNull();
    expect(screen.queryByTestId("ide-project-thread-member")).toBeNull();
    expect(screen.getAllByTestId(/^ide-project-thread-t\d$/)).toHaveLength(5);
    fireEvent.click(screen.getByTestId("ide-project-threads-more-p1"));
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
  });

  it("starts a new thread in the folder", () => {
    useThreadChatStore.setState({ sessions: [] });
    render(<ProjectThreadRows project={project} projects={[project]} />);
    fireEvent.click(screen.getByTestId("ide-project-thread-new-p1"));
    expect(useIdeThreadsStore.getState().layout).toBe("threads");
    expect(useIdeThreadsStore.getState().selection).toMatchObject({ projectId: "p1", sessionId: null });
  });
});
