import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { IdeProject } from "@/lib/agenticIdeApi";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { useEventStore } from "@/store/events";

const reorderProjects = vi.hoisted(() => vi.fn());
vi.mock("@/lib/chatLibraryApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/chatLibraryApi")>()),
  reorderProjects,
}));
vi.mock("@/lib/agentChatApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/agentChatApi")>()),
  fetchAgentChatCatalog: vi.fn().mockResolvedValue({ default_cwd: "/", shell: "bash", selection: null, providers: [] }),
  fetchAgentChatSessions: vi.fn().mockResolvedValue([]),
}));
vi.mock("@/lib/teamThreadsApi", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/teamThreadsApi")>()),
  useTeamThreads: () => ({ data: [] }),
}));

import { ThreadTree } from "./ThreadTree";

function folder(id: string, name: string, pinned = false): IdeProject {
  return { id, path: `/${id}`, name, color: null, pinned, archived: false, scratch: false,
    created_at: 0, last_opened_at: 0, exists: true, chats: 0, workspaces: [] } as IdeProject;
}

function dataTransfer() {
  const data = new Map<string, string>();
  return {
    types: ["application/x-jarvis-project-id"],
    effectAllowed: "",
    dropEffect: "",
    setData: (kind: string, value: string) => void data.set(kind, value),
    getData: (kind: string) => data.get(kind) ?? "",
  };
}

const order = () => useIdeProjectsStore.getState().projects.map((project) => project.id);

beforeEach(() => {
  localStorage.clear();
  vi.stubGlobal("ResizeObserver", class { observe() {} unobserve() {} disconnect() {} });
  reorderProjects.mockReset().mockResolvedValue([]);
  useIdeProjectsStore.setState({
    projects: [folder("p1", "Dodaios"), folder("p2", "Musikvideo"), folder("p3", "Marketing")],
    activeWorkspaceId: null,
    refreshRequest: null,
  });
  useIdeThreadsStore.setState({ layout: "threads", selection: { projectId: "p1", sessionId: null }, projectOf: {}, seen: {}, archived: {} });
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("drags a folder below another one, shows the new order at once and stores it", async () => {
  render(<ThreadTree />);
  const source = screen.getByTestId("thread-project-header-p1");
  const target = screen.getByTestId("thread-project-header-p2");
  expect(source.getAttribute("draggable")).toBe("true");
  const transfer = dataTransfer();
  fireEvent.dragStart(source, { dataTransfer: transfer });
  target.getBoundingClientRect = () => ({ top: 0, height: 32, left: 0, width: 300 } as DOMRect);
  // jsdom leaves clientY out of drag events, so the drop lands in the lower half.
  fireEvent.dragOver(target, { dataTransfer: transfer, clientY: 30 });
  fireEvent.drop(target, { dataTransfer: transfer, clientY: 30 });
  expect(order()).toEqual(["p2", "p1", "p3"]);
  await waitFor(() => expect(reorderProjects).toHaveBeenCalledWith(["p2", "p1", "p3"]));
  await waitFor(() => expect(useIdeProjectsStore.getState().refreshRequest?.nonce).toBe(1));
});

it("ignores a thread row dragged over a folder", () => {
  render(<ThreadTree />);
  const target = screen.getByTestId("thread-project-header-p1");
  const transfer = { ...dataTransfer(), types: ["application/x-jarvis-thread"] };
  fireEvent.dragOver(target, { dataTransfer: transfer, clientY: 4 });
  fireEvent.drop(target, { dataTransfer: transfer, clientY: 4 });
  expect(reorderProjects).not.toHaveBeenCalled();
});

it("moves a folder one place with Alt and an arrow key", async () => {
  render(<ThreadTree />);
  fireEvent.keyDown(screen.getByRole("button", { name: "Collapse Dodaios" }), { key: "ArrowDown", altKey: true });
  await waitFor(() => expect(reorderProjects).toHaveBeenCalledWith(["p2", "p1", "p3"]));
});

it("keeps a pinned folder in its own section", () => {
  useIdeProjectsStore.setState({ projects: [folder("p1", "Dodaios", true), folder("p2", "Musikvideo")] });
  render(<ThreadTree />);
  const transfer = dataTransfer();
  fireEvent.dragStart(screen.getByTestId("thread-project-header-p1"), { dataTransfer: transfer });
  const target = screen.getByTestId("thread-project-header-p2");
  target.getBoundingClientRect = () => ({ top: 0, height: 32, left: 0, width: 300 } as DOMRect);
  fireEvent.dragOver(target, { dataTransfer: transfer, clientY: 30 });
  fireEvent.drop(target, { dataTransfer: transfer, clientY: 30 });
  expect(reorderProjects).not.toHaveBeenCalled();
});

it("tells the person and reloads the stored order when saving fails", async () => {
  reorderProjects.mockRejectedValueOnce(new Error("stale list"));
  const pushToast = vi.fn();
  useEventStore.setState({ pushToast } as never);
  render(<ThreadTree />);
  fireEvent.keyDown(screen.getByRole("button", { name: "Collapse Dodaios" }), { key: "ArrowDown", altKey: true });
  await waitFor(() => expect(pushToast).toHaveBeenCalledWith("error", "stale list"));
  expect(useIdeProjectsStore.getState().refreshRequest?.nonce).toBe(1);
});
