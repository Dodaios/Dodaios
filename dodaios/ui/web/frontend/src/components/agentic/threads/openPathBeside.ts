import { openOutsideFile } from "@/components/agentic/editor/editorApi";
import { loadFileList } from "@/components/agentic/editor/fileListCache";
import { openLocalPath } from "@/lib/openLocalPath";
import { useIdeChatStore } from "@/store/ideChat";
import { revealInExplorer } from "@/store/ideExplorer";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { absoluteFilePath, useSideFileStore } from "@/store/sideFile";
import { filesFromFolder, matchProjectPath } from "./projectPathMatch";

/** A path with no drive, no leading slash and no `~`: an answer named it from some folder. */
function isRelative(path: string): boolean {
  return !/^(?:[a-z]:[\\/]|[\\/]|~(?:[\\/]|$))/i.test(path.trim());
}

/** The folder of workspace `workspaceId`: the open one's, else the project list's. */
function workspaceFolder(workspaceId: string): string {
  const open = useIdeChatStore.getState().workspace;
  if (open?.id === workspaceId && open.path) return open.path;
  for (const project of useIdeProjectsStore.getState().projects) {
    const workspace = project.workspaces?.find((candidate) => candidate.id === workspaceId);
    if (workspace) return workspace.folder;
  }
  return "";
}

/**
 * The full path of the one file or folder of the project a relative path
 * means when it is not there as written (`core/config.py` for
 * `dodaios/core/config.py`); null when none or several fit.
 */
async function findInProject(workspaceId: string, path: string, folder: string): Promise<string | null> {
  const root = workspaceFolder(workspaceId);
  if (!root) return null;
  try {
    const listing = await loadFileList(workspaceId);
    const files = filesFromFolder(listing.paths, root, folder);
    const match = files ? matchProjectPath(path, folder, files) : null;
    return match ? absoluteFilePath(match.path, folder) : null;
  } catch {
    return null;
  }
}

/**
 * Open a path a thread's answer names, beside the conversation: a file in the
 * side panel's File tab (at `line` when the answer named one), a folder of the
 * project in its Files tab. A folder elsewhere on the computer has no tree
 * here, so the file manager shows it.
 *
 * Agents do not always name a file from the thread's folder. A relative path
 * that is not there as written is looked for in the project (the one file
 * whose path ends in it: `core/config.py` is `dodaios/core/config.py`), then
 * in the home folder (`Downloads\demo\clip.mp4`), before it reads as missing.
 * The File tab then shows the path that was found.
 *
 * Only a click calls this, so it may grant a file outside the project to the
 * panel, the same way a modifier-click on a terminal path does.
 */
export async function openPathBeside(path: string, folder: string, line?: number): Promise<void> {
  const absolute = absoluteFilePath(path, folder);
  const workspaceId = useIdeChatStore.getState().workspace?.id ?? useIdeProjectsStore.getState().activeWorkspaceId;
  const show = (shown = path) => useSideFileStore.getState().show({ path: shown, folder, diff: null, ...(line ? { line } : {}) });
  if (!workspaceId) { show(); return; }
  const lookUp = async (candidate: string) => {
    try {
      return await openOutsideFile(workspaceId, candidate);
    } catch {
      return null; // Not here: try the next place it may be.
    }
  };

  const written = await lookUp(absolute);
  if (written) {
    if (written.kind === "directory") revealInExplorer({ workspaceId, path: written.path });
    else show();
    return;
  }
  if (isRelative(path) && folder) {
    const inProject = await findInProject(workspaceId, path, folder);
    const found = inProject ? await lookUp(inProject) : null;
    if (inProject && found) {
      if (found.kind === "directory") revealInExplorer({ workspaceId, path: found.path });
      else show(inProject);
      return;
    }
    const home = `~/${path.trim().replace(/^\.[\\/]/, "").replace(/\\/g, "/")}`;
    const atHome = await lookUp(home);
    if (atHome) {
      // The server answers with the full path of a file outside the project.
      if (atHome.kind === "directory") revealInExplorer({ workspaceId, path: atHome.path });
      else show(isRelative(atHome.path) ? home : atHome.path);
      return;
    }
  }
  // Not a file, and not a folder of the project: a folder elsewhere opens
  // on the computer; anything else reads as unavailable in the File tab.
  if (!/\.[A-Za-z0-9]{1,10}$/.test(absolute.replace(/[\\/]+$/, "")) && await openLocalPath(absolute)) return;
  show();
}
