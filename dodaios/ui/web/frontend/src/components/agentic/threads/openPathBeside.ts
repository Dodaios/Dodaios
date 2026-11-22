import { openOutsideFile } from "@/components/agentic/editor/editorApi";
import { fetchTypeahead } from "@/lib/agentChatApi";
import { openLocalPath } from "@/lib/openLocalPath";
import { useIdeChatStore } from "@/store/ideChat";
import { revealInExplorer } from "@/store/ideExplorer";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { absoluteFilePath, useSideFileStore } from "@/store/sideFile";
import { matchProjectPath, type ProjectPathMatch } from "./projectPathMatch";

/** A path with no drive, no leading slash and no `~`: an answer named it from some folder. */
function isRelative(path: string): boolean {
  return !/^(?:[a-z]:[\\/]|[\\/]|~(?:[\\/]|$))/i.test(path.trim());
}

/** The most entries one lookup reads; the search ranks exact names first. */
const LOOKUP_LIMIT = 1000;

/**
 * The full path of the one file or folder of the project a relative path
 * means when it is not there as written (`core/config.py` for
 * `dodaios/core/config.py`); null when none or several fit.
 *
 * The candidates are the files and folders under the thread's folder whose
 * name holds the named one, from the composer's file search (`@`): it reads
 * the thread's own folder, whichever workspace is open, and the server keeps
 * the listing warm.
 */
async function findInProject(path: string, folder: string): Promise<ProjectPathMatch | null> {
  const target = path.trim().replace(/\\/g, "/").replace(/\/+$/, "");
  const name = target.slice(target.lastIndexOf("/") + 1);
  if (!name) return null;
  try {
    const found = await fetchTypeahead({ surface: "agent", provider: "", cwd: folder, trigger: "@", q: name, limit: LOOKUP_LIMIT });
    // Folders come back as `path/`, which is how the match tells them from files.
    const entries = found.items.filter((item) => item.kind === "file" || item.kind === "folder").map((item) => item.value);
    const match = matchProjectPath(path, folder, entries);
    return match ? { ...match, path: absoluteFilePath(match.path, folder) } : null;
  } catch {
    return null; // The lookup is a second chance; without it the path reads as missing.
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
  // A project folder the open workspace has no tree for opens on the computer.
  let elsewhere = absolute;
  if (isRelative(path) && folder) {
    const inProject = await findInProject(path, folder);
    const found = inProject ? await lookUp(inProject.path) : null;
    if (inProject && found) {
      if (found.kind === "directory") revealInExplorer({ workspaceId, path: found.path });
      else show(inProject.path);
      return;
    }
    if (inProject?.kind === "directory") elsewhere = inProject.path;
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
  if (!/\.[A-Za-z0-9]{1,10}$/.test(elsewhere.replace(/[\\/]+$/, "")) && await openLocalPath(elsewhere)) return;
  show();
}
