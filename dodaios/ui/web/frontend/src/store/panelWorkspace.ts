import { useIdeChatStore, type IdeWorkspace, type IdeWorkspaceRow } from "@/store/ideChat";
import { useIdeThreadsStore } from "@/store/ideThreads";

/**
 * Which workspace the IDE's side panel shows: Folder, Changes, Search, Git,
 * the File tab, its terminals and the code editor over the view.
 *
 * In the grid it is the workspace at the front. In the thread layout it is the
 * open thread's folder: the person reads one conversation, and the panel next
 * to it shows that conversation's project, whichever workspace the grid had in
 * front (a chat in project B beside project A's files was the bug).
 *
 * A thread's folder that an open workspace has open is that workspace. One no
 * workspace has open (a project only ever used in threads, or a thread's own
 * worktree) is named by a folder view id, which the backend's workspace routes
 * read the same way (`dodaios/agentic_ide/folder_view.py`).
 */

const FOLDER_VIEW_PREFIX = "folder:";

/** The folder view id the backend reads `folder` by: `folder:` + URL-safe base64 of the path. */
export function folderViewId(folder: string): string {
  const bytes = new TextEncoder().encode(folder);
  let binary = "";
  for (const byte of bytes) binary += String.fromCharCode(byte);
  return FOLDER_VIEW_PREFIX + btoa(binary).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

export function isFolderView(workspaceId: string | null | undefined): boolean {
  return Boolean(workspaceId?.startsWith(FOLDER_VIEW_PREFIX));
}

/** The folder a folder view id names; "" for any other id. */
export function folderOfView(workspaceId: string | null | undefined): string {
  if (!workspaceId || !isFolderView(workspaceId)) return "";
  const body = workspaceId.slice(FOLDER_VIEW_PREFIX.length).replace(/-/g, "+").replace(/_/g, "/");
  try {
    const binary = atob(body + "=".repeat((4 - (body.length % 4)) % 4));
    return new TextDecoder().decode(Uint8Array.from(binary, (char) => char.charCodeAt(0)));
  } catch {
    return ""; // Not a folder view this app wrote: it names no folder.
  }
}

/** A folder as a comparison key: one slash kind, no trailing slash, case folded on Windows. */
function folderKey(folder: string): string {
  const posix = folder.replace(/\\/g, "/").replace(/\/+$/, "");
  return /^[a-z]:\//i.test(posix) ? posix.toLowerCase() : posix;
}

/**
 * The panel's workspace for a thread running in `folder` of project `name`:
 * the open workspace on that very folder (the front one first), else a folder
 * view of it. Null without a folder.
 */
export function threadPanelWorkspace(folder: string, name: string, open: readonly IdeWorkspaceRow[]): IdeWorkspace | null {
  if (!folder) return null;
  const key = folderKey(folder);
  const same = open.filter((row) => row.folder && folderKey(row.folder) === key);
  const match = same.find((row) => row.active) ?? same[0];
  if (match) return { id: match.id, name: match.name, path: match.folder };
  return { id: folderViewId(folder), name, path: folder };
}

function pick(layout: string, thread: IdeWorkspace | null, grid: IdeWorkspace | null): IdeWorkspace | null {
  return layout === "threads" && thread ? thread : grid;
}

/** The workspace the side panel shows, for a component. */
export function usePanelWorkspace(): IdeWorkspace | null {
  const layout = useIdeThreadsStore((state) => state.layout);
  const thread = useIdeChatStore((state) => state.threadWorkspace);
  const grid = useIdeChatStore((state) => state.workspace);
  return pick(layout, thread, grid);
}

/** The workspace the side panel shows, read once (event handlers, actions). */
export function panelWorkspace(): IdeWorkspace | null {
  const chat = useIdeChatStore.getState();
  return pick(useIdeThreadsStore.getState().layout, chat.threadWorkspace, chat.workspace);
}
