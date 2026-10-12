import { useEffect } from "react";
import { create } from "zustand";

import { fetchFileVersion } from "@/components/agentic/editor/editorApi";
import { isOutsidePath, openTerminalTarget, probeWorkspaceFile } from "@/lib/agenticIdeApi";
import { OPEN_PATH_EVENT } from "@/lib/terminalLinks";
import { useCodeEditorStore } from "@/store/codeEditor";
import { useEventStore } from "@/store/events";
import { useIdeChatStore } from "@/store/ideChat";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";

/**
 * The side panel's Changes and Folder tabs.
 *
 * Files open in the code editor (store/codeEditor). This store only carries a
 * "reveal" request: show one path in the Folder tab's tree, expanding the
 * folders above it — the editor's "Reveal in Explorer", and a Ctrl+click on a
 * folder a coding agent printed in its terminal.
 */
export type ExplorerView = "files" | "changes";

export interface OpenedFile {
  workspaceId: string;
  /** Workspace-relative POSIX path. */
  path: string;
}

export interface RevealRequest extends OpenedFile {
  nonce: number;
}

interface IdeExplorerState {
  revealed: RevealRequest | null;
  reveal: (file: OpenedFile) => void;
}

let nonce = 0;

export const useIdeExplorerStore = create<IdeExplorerState>((set) => ({
  revealed: null,
  reveal: (file) => set({ revealed: { ...file, nonce: ++nonce } }),
}));

/** Show a path in the Folder tab, bringing the side panel up if needed. */
export function revealInExplorer(file: OpenedFile): void {
  useIdeExplorerStore.getState().reveal(file);
  useIdeSidePanelStore.getState().openTab("files");
}

export interface OpenPathDetail {
  workspaceId: string;
  path: string;
  /** Ctrl/Cmd was held: what the app cannot show may go to the OS opener. */
  launch?: boolean;
}

export interface PrintedPath {
  /** Workspace-relative POSIX path; null when it points outside the workspace. */
  path: string | null;
  /** Set with a null `path`: where on this computer the file lies instead. */
  outside?: string;
  line?: number;
  column?: number;
}

const LOCATION = /(?:#L(\d+)(?::(\d+))?|:(\d+)(?::(\d+))?|\((\d+)(?:,(\d+))?\))$/i;

/**
 * A path as a coding agent printed it (`src/app.ts:42:7`, an absolute path,
 * a `file:` URI) turned into a workspace-relative path and a line to jump to.
 */
export function parsePrintedPath(workspaceRoot: string, printed: string): PrintedPath {
  let value = printed.trim().replace(/^["'`]|["'`]$/g, "");
  let line: number | undefined;
  let column: number | undefined;
  const location = LOCATION.exec(value);
  if (location) {
    const [, l1, c1, l2, c2, l3, c3] = location;
    line = Number(l1 ?? l2 ?? l3);
    const col = c1 ?? c2 ?? c3;
    column = col ? Number(col) : undefined;
    value = value.slice(0, location.index);
  }
  if (/^file:/i.test(value)) {
    try {
      value = decodeURIComponent(new URL(value).pathname).replace(/^\/([a-z]:)/i, "$1");
    } catch {
      return { path: null };
    }
  }
  const slashes = (text: string) => text.replace(/\\/g, "/");
  let path = slashes(value);
  const root = slashes(workspaceRoot).replace(/\/+$/, "");
  if (isOutsidePath(path)) {
    // Windows paths compare case-insensitively; POSIX paths exactly.
    const windows = /^[a-z]:\//i.test(root);
    const head = windows ? path.slice(0, root.length + 1).toLowerCase() : path.slice(0, root.length + 1);
    const want = windows ? `${root.toLowerCase()}/` : `${root}/`;
    if (head !== want) return { path: null, outside: path };
    path = path.slice(root.length + 1);
  }
  path = path.replace(/^(\.\/)+/, "").replace(/\/+$/, "");
  if (!path) return { path: null };
  // `../shared/x.png` leaves the workspace; the server resolves where to.
  if (path.split("/").includes("..")) return { path: null, outside: `${root}/${path}` };
  return { path, line, column };
}

/**
 * Open what a terminal path points at: a file in the editor (at its line), a
 * folder in the Folder tab. A file outside the workspace opens in the editor
 * too, read-only. `launch` (a Ctrl/Cmd-click) lets the system app take what
 * the app itself cannot show.
 */
export async function openPrintedPath(
  workspaceId: string,
  workspaceRoot: string,
  printed: string,
  launch = false,
): Promise<void> {
  const parsed = parsePrintedPath(workspaceRoot, printed);
  const fail = (error: unknown) => useEventStore.getState().pushToast("error", (error as Error).message);
  const external = async () => {
    if (launch) await openTerminalTarget(workspaceId, printed).catch(fail);
  };
  if (parsed.path === null) {
    if (!parsed.outside) {
      await external();
      return;
    }
    try {
      await probeWorkspaceFile(workspaceId, parsed.outside);
    } catch (error) {
      fail(error);
      return;
    }
    useCodeEditorStore.getState().openFile(workspaceId, parsed.outside, { preview: false });
    return;
  }
  let version: string | null;
  try {
    version = await fetchFileVersion(workspaceId, parsed.path);
  } catch (error) {
    if (launch) await external();
    else fail(error);
    return;
  }
  if (version === null) {
    revealInExplorer({ workspaceId, path: parsed.path });
    return;
  }
  useCodeEditorStore.getState().openFile(workspaceId, parsed.path, {
    preview: false,
    line: parsed.line,
    column: parsed.column,
  });
}

/**
 * Route terminal path clicks into the editor while the Agentic IDE is mounted.
 *
 * Only for the workspace on screen: a path from another workspace's pane has
 * no tree here to show it in, so it keeps the old behaviour.
 */
export function useExplorerPathRouting(): void {
  useEffect(() => {
    const onOpen = (event: Event) => {
      const detail = (event as CustomEvent<OpenPathDetail>).detail;
      const workspace = useIdeChatStore.getState().workspace;
      if (!detail?.workspaceId || !detail.path || workspace?.id !== detail.workspaceId) return;
      event.preventDefault();
      void openPrintedPath(detail.workspaceId, workspace.path, detail.path, detail.launch ?? false);
    };
    window.addEventListener(OPEN_PATH_EVENT, onOpen);
    return () => window.removeEventListener(OPEN_PATH_EVENT, onOpen);
  }, []);
}
