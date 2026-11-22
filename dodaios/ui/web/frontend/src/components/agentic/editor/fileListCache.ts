import { fetchFileList, type FileList } from "./editorApi";

/** A listing is reused for this long, so Ctrl+P twice in a row opens instantly. */
const LIST_TTL_MS = 20_000;
const listCache = new Map<string, { at: number } & FileList>();

/** Drop a workspace's cached listing after the explorer created, renamed or deleted something. */
export function forgetFileList(workspaceId: string): void {
  listCache.delete(workspaceId);
}

/** The listing already here, however old: something to show while a fresh one loads. */
export function peekFileList(workspaceId: string): FileList | null {
  return listCache.get(workspaceId) ?? null;
}

/**
 * Every file path in the workspace (relative to its folder), shared by Go to
 * File and the thread's file references; reused while it is fresh.
 */
export async function loadFileList(workspaceId: string): Promise<FileList> {
  const cached = listCache.get(workspaceId);
  if (cached && Date.now() - cached.at < LIST_TTL_MS) return cached;
  const answer = await fetchFileList(workspaceId);
  listCache.set(workspaceId, { at: Date.now(), ...answer });
  return answer;
}
