import { cleanup, fireEvent, render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { AgentChatSession } from "@/lib/agentChatApi";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { useThreadFlagsStore } from "@/store/threadFlags";
import { useThreadChatStore } from "./threadModel";

vi.mock("@/lib/teamThreadsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/teamThreadsApi")>()),
  useTeamThreads: () => ({ data: [] }),
}));
vi.mock("../useSessionGitHub", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../useSessionGitHub")>()),
  useThreadGitHub: () => ({ status: null, pending: false }),
}));

import { ThreadTree } from "./ThreadTree";

const project = { id: "p1", path: "/work/app", name: "App", color: null, pinned: false, archived: false, scratch: false,
  created_at: 0, last_opened_at: 0, exists: true, chats: 0, workspaces: [] } as unknown as IdeProject;

const session = (id: string, title: string) => ({ session_id: id, title, provider: "claude", model: "", effort: "", cwd: project.path,
  permission_mode: "", vendor_session: null, created_ms: 0, updated_ms: Date.now() - 60_000,
  message_count: 1, preview: "" }) as AgentChatSession;

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  useThreadFlagsStore.setState({ flags: {}, names: {} });
  useIdeProjectsStore.setState({ projects: [project], activeWorkspaceId: null });
  useIdeThreadsStore.setState({ layout: "threads", selection: { projectId: "p1", sessionId: null }, projectOf: {}, seen: {}, archived: {} });
  useThreadChatStore.setState({ sessions: [session("s1", "Fix login"), session("s2", "Ship docs")],
    loadSessions: vi.fn().mockResolvedValue(undefined), loadCatalog: vi.fn().mockResolvedValue(undefined) });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const flagMenu = (id: string) => {
  fireEvent.contextMenu(screen.getByTestId(`thread-row-${id}`));
  return screen.getByTestId("thread-flag-menu");
};

it("flags a thread from its right-click menu and names the flag on hover", () => {
  render(<ThreadTree />);
  expect(screen.queryByTestId("thread-flag-s1")).toBeNull();
  fireEvent.click(within(flagMenu("s1")).getByRole("menuitem", { name: "Important" }));
  const mark = screen.getByTestId("thread-flag-s1");
  expect(mark.getAttribute("data-flag")).toBe("red");
  expect(mark.getAttribute("title")).toBe("Important");
  // The menu closed; the other thread stays unflagged.
  expect(screen.queryByTestId("thread-flag-menu")).toBeNull();
  expect(screen.queryByTestId("thread-flag-s2")).toBeNull();
  expect(JSON.parse(localStorage.getItem("jarvis.agenticIde.threadFlags.v1") ?? "{}")).toEqual({ s1: "red" });
});

it("moves a thread to another flag, and the same flag again takes it off", () => {
  render(<ThreadTree />);
  fireEvent.click(within(flagMenu("s1")).getByRole("menuitem", { name: "Important" }));
  fireEvent.click(within(flagMenu("s1")).getByRole("menuitem", { name: "Later" }));
  expect(screen.getByTestId("thread-flag-s1").getAttribute("data-flag")).toBe("blue");
  fireEvent.click(within(flagMenu("s1")).getByRole("menuitem", { name: /Later/ }));
  expect(screen.queryByTestId("thread-flag-s1")).toBeNull();
});

it("gives each flag kind the person's own name, shown on every thread with it", () => {
  render(<ThreadTree />);
  fireEvent.click(within(flagMenu("s1")).getByRole("menuitem", { name: "Follow up" }));
  fireEvent.click(within(flagMenu("s2")).getByRole("menuitem", { name: "Follow up" }));
  fireEvent.click(within(flagMenu("s1")).getByRole("menuitem", { name: "Name flags…" }));
  fireEvent.change(screen.getByTestId("thread-flag-name-orange"), { target: { value: "  Waiting for review " } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByTestId("thread-flag-s1").getAttribute("title")).toBe("Waiting for review");
  expect(screen.getByTestId("thread-flag-s2").getAttribute("title")).toBe("Waiting for review");
  // An empty name brings the default words back.
  fireEvent.click(within(flagMenu("s1")).getByRole("menuitem", { name: "Name flags…" }));
  fireEvent.change(screen.getByTestId("thread-flag-name-orange"), { target: { value: "" } });
  fireEvent.click(screen.getByRole("button", { name: "Save" }));
  expect(screen.getByTestId("thread-flag-s1").getAttribute("title")).toBe("Follow up");
});
