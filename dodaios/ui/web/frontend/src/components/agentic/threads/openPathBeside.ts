import { openOutsideFile } from "@/components/agentic/editor/editorApi";
import { openLocalPath } from "@/lib/openLocalPath";
import { useIdeChatStore } from "@/store/ideChat";
import { revealInExplorer } from "@/store/ideExplorer";
import { useIdeProjectsStore } from "@/store/ideProjects";
import { absoluteFilePath, useSideFileStore } from "@/store/sideFile";

/**
 * Open a path a thread's answer names, beside the conversation: a file in the
 * side panel's File tab, a folder of the project in its Files tab. A folder
 * elsewhere on the computer has no tree here, so the file manager shows it.
 *
 * Only a click calls this, so it may grant a file outside the project to the
 * panel, the same way a modifier-click on a terminal path does.
 */
export async function openPathBeside(path: string, folder: string): Promise<void> {
  const absolute = absoluteFilePath(path, folder);
  const workspaceId = useIdeChatStore.getState().workspace?.id ?? useIdeProjectsStore.getState().activeWorkspaceId;
  const show = () => useSideFileStore.getState().show({ path, folder, diff: null });
  if (!workspaceId) { show(); return; }
  try {
    const found = await openOutsideFile(workspaceId, absolute);
    if (found.kind === "directory") revealInExplorer({ workspaceId, path: found.path });
    else show();
  } catch {
    // Not a file, and not a folder of the project: a folder elsewhere opens
    // on the computer; anything else reads as unavailable in the File tab.
    if (!/\.[A-Za-z0-9]{1,10}$/.test(absolute.replace(/[\\/]+$/, "")) && await openLocalPath(absolute)) return;
    show();
  }
}
