import { openOutsideFile } from "@/components/agentic/editor/editorApi";
import { openLocalPath } from "@/lib/openLocalPath";
import { useIdeChatStore } from "@/store/ideChat";
import { revealInExplorer } from "@/store/ideExplorer";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { absoluteFilePath, useSideFileStore } from "@/store/sideFile";

/** A path with no drive, no leading slash and no `~`: an answer named it from some folder. */
function isRelative(path: string): boolean {
  return !/^(?:[a-z]:[\\/]|[\\/]|~(?:[\\/]|$))/i.test(path.trim());
}

/**
 * Open a path a thread's answer names, beside the conversation: a file in the
 * side panel's File tab, a folder of the project in its Files tab. A folder
 * elsewhere on the computer has no tree here, so the file manager shows it.
 *
 * Agents often name a file by where it is under the home folder
 * (`Downloads\demo\clip.mp4`), not by the project. A relative path that is not
 * in the project is looked for in the home folder before it reads as missing,
 * and the File tab then shows the path that was found.
 *
 * Only a click calls this, so it may grant a file outside the project to the
 * panel, the same way a modifier-click on a terminal path does.
 */
export async function openPathBeside(path: string, folder: string): Promise<void> {
  const absolute = absoluteFilePath(path, folder);
  const workspaceId = useIdeChatStore.getState().workspace?.id ?? useIdeProjectsStore.getState().activeWorkspaceId;
  const show = (shown = path) => useSideFileStore.getState().show({ path: shown, folder, diff: null });
  if (!workspaceId) { show(); return; }
  const candidates = [absolute];
  if (isRelative(path) && folder) candidates.push(`~/${path.trim().replace(/^\.[\\/]/, "").replace(/\\/g, "/")}`);
  for (const candidate of candidates) {
    try {
      const found = await openOutsideFile(workspaceId, candidate);
      if (found.kind === "directory") revealInExplorer({ workspaceId, path: found.path });
      else if (candidate === absolute) show();
      // The server answers with the full path of a file outside the project.
      else show(isRelative(found.path) ? candidate : found.path);
      return;
    } catch {
      // Not here: try the next place it may be.
    }
  }
  // Not a file, and not a folder of the project: a folder elsewhere opens
  // on the computer; anything else reads as unavailable in the File tab.
  if (!/\.[A-Za-z0-9]{1,10}$/.test(absolute.replace(/[\\/]+$/, "")) && await openLocalPath(absolute)) return;
  show();
}
