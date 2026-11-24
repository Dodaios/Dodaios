import { afterEach, describe, expect, it } from "vitest";

import { useIdeChatStore, type IdeWorkspaceRow } from "@/store/ideChat";
import { useIdeThreadsStore } from "@/store/ideThreads";
import { folderOfView, folderViewId, isFolderView, panelWorkspace, threadPanelWorkspace } from "./panelWorkspace";

const harald: IdeWorkspaceRow = { id: "ide_harald", name: "Harald", folder: "C:\\Users\\me\\Harald", active: true };
const gridFront = { id: harald.id, name: harald.name, path: harald.folder };

afterEach(() => {
  useIdeChatStore.setState({ workspace: null, threadWorkspace: null });
  useIdeThreadsStore.setState({ layout: "threads" });
});

describe("threadPanelWorkspace", () => {
  it("is the open workspace on the thread's own folder", () => {
    expect(threadPanelWorkspace("c:/users/me/harald/", "Harald", [harald])).toEqual(gridFront);
  });

  it("is a folder view of a project no workspace has open", () => {
    const mit = threadPanelWorkspace("C:\\Users\\me\\MIT", "MIT", [harald]);

    expect(mit?.name).toBe("MIT");
    expect(mit?.path).toBe("C:\\Users\\me\\MIT");
    expect(isFolderView(mit?.id)).toBe(true);
    expect(folderOfView(mit?.id)).toBe("C:\\Users\\me\\MIT");
  });

  it("keeps case apart on POSIX paths", () => {
    const row: IdeWorkspaceRow = { id: "ide_a", name: "A", folder: "/home/me/App", active: true };

    expect(isFolderView(threadPanelWorkspace("/home/me/app", "app", [row])?.id)).toBe(true);
  });

  it("is nothing without a folder", () => {
    expect(threadPanelWorkspace("", "MIT", [harald])).toBeNull();
  });
});

describe("folder view ids", () => {
  it("carry any path, the way the backend decodes it", () => {
    const folder = "/home/zoë/projects/café ñ+é 漢字?";
    const id = folderViewId(folder);

    expect(id).toMatch(/^folder:[A-Za-z0-9_-]+$/);
    expect(folderOfView(id)).toBe(folder);
  });

  it("name no folder for an open workspace's id", () => {
    expect(isFolderView("ide_harald")).toBe(false);
    expect(folderOfView("ide_harald")).toBe("");
  });
});

describe("panelWorkspace", () => {
  it("follows the open thread in the thread layout, not the grid's front workspace", () => {
    const mit = threadPanelWorkspace("C:\\Users\\me\\MIT", "MIT", [harald]);
    useIdeChatStore.setState({ workspace: gridFront, threadWorkspace: mit });

    expect(panelWorkspace()).toEqual(mit);
  });

  it("is the grid's front workspace in the grid layout", () => {
    useIdeChatStore.setState({ workspace: gridFront, threadWorkspace: threadPanelWorkspace("C:\\MIT", "MIT", []) });
    useIdeThreadsStore.setState({ layout: "grid" });

    expect(panelWorkspace()).toEqual(gridFront);
  });

  it("falls back to the grid's workspace while no thread is open", () => {
    useIdeChatStore.setState({ workspace: gridFront, threadWorkspace: null });

    expect(panelWorkspace()).toEqual(gridFront);
  });
});
