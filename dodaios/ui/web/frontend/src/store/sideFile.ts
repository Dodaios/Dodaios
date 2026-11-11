import { create } from "zustand";

import type { DiffFile } from "@/components/agentchat/toolDiff";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";

/**
 * The file a thread's work log points at, shown in the side panel's File tab.
 *
 * A click on a file an agent read, wrote or edited puts it here and brings the
 * tab forward, so the file reads beside the conversation instead of in it.
 */
export interface SideFile {
  /** The path as the tool named it: absolute, or relative to `folder`. */
  path: string;
  /** The thread's folder, which a relative path is read from. */
  folder: string;
  /** What the clicked call changed in the file, when it was an edit. */
  diff: DiffFile[] | null;
}

interface SideFileState {
  file: SideFile | null;
  /** Counts the clicks, so a second click on the same file reads it again. */
  nonce: number;
  show: (file: SideFile) => void;
}

export const useSideFileStore = create<SideFileState>((set, get) => ({
  file: null,
  nonce: 0,
  show: (file) => {
    set({ file, nonce: get().nonce + 1 });
    useIdeSidePanelStore.getState().openTab("file");
  },
}));

/** The path a thread file reads from: absolute as named, else joined to the thread's folder. */
export function absoluteFilePath(path: string, folder: string): string {
  const clean = path.trim();
  if (/^(?:[a-z]:[\\/]|[\\/])/i.test(clean) || !folder) return clean;
  const separator = folder.includes("\\") && !folder.includes("/") ? "\\" : "/";
  const relative = clean.replace(/^\.[\\/]/, "").split(/[\\/]/).join(separator);
  return `${folder.replace(/[\\/]+$/, "")}${separator}${relative}`;
}
