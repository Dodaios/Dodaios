import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { useThreadChatStore } from "./threadModel";
import { resetLauncherCacheForTests } from "../projectLaunchers";

const api = vi.hoisted(() => ({
  deleteProject: vi.fn(),
  patchProject: vi.fn(),
  openProjectIn: vi.fn(),
  fetchProjectLaunchers: vi.fn(),
  removeWorkspace: vi.fn(),
  sessions: vi.fn(),
}));
vi.mock("@/lib/chatLibraryApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/chatLibraryApi")>()),
  deleteProject: api.deleteProject,
  patchProject: api.patchProject,
  openProjectIn: api.openProjectIn,
  fetchProjectLaunchers: api.fetchProjectLaunchers,
}));
vi.mock("@/lib/agenticIdeApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/agenticIdeApi")>()),
  removeWorkspace: api.removeWorkspace,
}));
vi.mock("@/lib/agentChatApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/agentChatApi")>()),
  fetchAgentChatCatalog: vi.fn().mockResolvedValue({ default_cwd: "/", shell: "bash", selection: null, providers: [] }),
  fetchAgentChatSessions: api.sessions,
}));
vi.mock("@/lib/teamThreadsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/teamThreadsApi")>()),
  useTeamThreads: () => ({ data: [] }),
}));

import { ThreadTree } from "./ThreadTree";

function folder(id: string, name: string, extra: Partial<IdeProject> = {}): IdeProject {
  return { id, path: `/work/${id}`, name, color: null, pinned: false, archived: false, scratch: false,
    created_at: 0, last_opened_at: 0, exists: true, chats: 0, workspaces: [], ...extra } as IdeProject;
}

beforeEach(() => {
  localStorage.clear();
  resetLauncherCacheForTests();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  for (const fn of Object.values(api)) fn.mockReset();
  api.sessions.mockResolvedValue([]);
  api.deleteProject.mockResolvedValue(true);
  api.patchProject.mockResolvedValue({});
  api.openProjectIn.mockResolvedValue(true);
  api.fetchProjectLaunchers.mockResolvedValue({
    file_manager: true, editors: [{ id: "code", label: "VS Code" }, { id: "cursor", label: "Cursor", installed: false }],
    remote_url: "https://example.com/repo", remote_label: "GitHub",
  });
  useIdeProjectsStore.setState({
    projects: [folder("p1", "Dodaios"), folder("p2", "Marketing")],
    activeWorkspaceId: null,
    refreshRequest: null,
  });
  useIdeThreadsStore.setState({ layout: "threads", selection: { projectId: "p1", sessionId: null }, projectOf: {}, seen: {}, archived: {} });
  useThreadChatStore.setState({ sessions: [] });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

const openMenu = async (id: string) => {
  fireEvent.contextMenu(screen.getByTestId(`thread-project-header-${id}`), { clientX: 40, clientY: 60 });
  return screen.findByTestId("thread-project-menu");
};

it("opens the project's own menu on right-click instead of the edit menu", async () => {
  render(<ThreadTree />);
  const header = screen.getByTestId("thread-project-header-p2");
  const event = new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 40, clientY: 60 });
  const reachedDocument = vi.fn();
  document.addEventListener("contextmenu", reachedDocument);
  header.dispatchEvent(event);
  document.removeEventListener("contextmenu", reachedDocument);
  expect(event.defaultPrevented).toBe(true);
  // The app-wide Cut/Copy/Paste menu listens on document and must not see it.
  expect(reachedDocument).not.toHaveBeenCalled();
  const menu = await screen.findByTestId("thread-project-menu");
  expect(within(menu).getByText("Marketing")).toBeTruthy();
  expect(within(menu).getByText("/work/p2")).toBeTruthy();
  expect(within(menu).getByRole("menuitem", { name: "Rename project" })).toBeTruthy();
  expect(within(menu).getByRole("menuitem", { name: "Pin project" })).toBeTruthy();
  expect(within(menu).getByRole("menuitem", { name: "Copy folder path" })).toBeTruthy();
  // The editors and the web page arrive from the backend.
  expect(await within(menu).findByRole("menuitem", { name: "Open in VS Code" })).toBeTruthy();
  expect((within(menu).getByRole("menuitem", { name: /Open in Cursor/ }) as HTMLButtonElement).disabled).toBe(true);
  expect(within(menu).getByRole("menuitem", { name: "Open on GitHub" })).toBeTruthy();
});

it("opens the folder in an editor from the menu", async () => {
  render(<ThreadTree />);
  const menu = await openMenu("p1");
  fireEvent.click(await within(menu).findByRole("menuitem", { name: "Open in VS Code" }));
  await waitFor(() => expect(api.openProjectIn).toHaveBeenCalledWith("p1", "code"));
  expect(screen.queryByTestId("thread-project-menu")).toBeNull();
});

it("removes a project after asking once more, and reads the list back", async () => {
  useIdeProjectsStore.setState({
    projects: [folder("p1", "Dodaios"), folder("p2", "Marketing", {
      workspaces: [{ id: "w1", status: "closed", terminals: 0, name: "Marketing" }] as IdeProject["workspaces"],
    })],
  });
  render(<ThreadTree />);
  const menu = await openMenu("p2");
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Remove project" }));
  expect(api.deleteProject).not.toHaveBeenCalled();
  const confirm = screen.getByTestId("thread-project-confirm-remove");
  expect(confirm.textContent).toContain("Remove Marketing from the sidebar?");
  expect(confirm.textContent).toContain("folder on disk");
  fireEvent.click(screen.getByTestId("thread-project-confirm-remove-yes"));
  await waitFor(() => expect(api.deleteProject).toHaveBeenCalledWith("p2"));
  expect(api.removeWorkspace).toHaveBeenCalledWith("w1");
  await waitFor(() => expect(screen.queryByTestId("thread-project-menu")).toBeNull());
  expect(useIdeProjectsStore.getState().refreshRequest?.nonce).toBe(1);
});

it("keeps a project whose thread is still working", async () => {
  const busy = [{ session_id: "s1", cwd: "/work/p2", provider: "claude", running: true, updated_ms: 1, created_ms: 1, title: "Busy" }];
  api.sessions.mockResolvedValue(busy);
  useThreadChatStore.setState({ sessions: busy as never });
  render(<ThreadTree />);
  await screen.findByText("Busy");
  const menu = await openMenu("p2");
  const remove = within(menu).getByRole("menuitem", { name: /Remove project/ }) as HTMLButtonElement;
  expect(remove.disabled).toBe(true);
  expect(remove.textContent).toContain("1 working");
});

it("renames a project in its row", async () => {
  render(<ThreadTree />);
  const menu = await openMenu("p2");
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Rename project" }));
  const input = screen.getByTestId("thread-project-rename-p2");
  fireEvent.change(input, { target: { value: "Marketing 2027" } });
  fireEvent.submit(input.closest("form")!);
  await waitFor(() => expect(api.patchProject).toHaveBeenCalledWith("p2", { name: "Marketing 2027" }));
});

it("pins a project from its ⋯ button", async () => {
  render(<ThreadTree />);
  fireEvent.click(screen.getByTestId("thread-project-more-p2"));
  const menu = await screen.findByTestId("thread-project-menu");
  fireEvent.click(within(menu).getByRole("menuitem", { name: "Pin project" }));
  await waitFor(() => expect(api.patchProject).toHaveBeenCalledWith("p2", { pinned: true }));
});
