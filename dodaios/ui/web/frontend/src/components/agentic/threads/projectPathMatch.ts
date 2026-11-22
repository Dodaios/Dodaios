/**
 * Which file or folder of the project a path in an answer means, when it is
 * not there as written.
 *
 * Agents often name a file from inside a package (`core/config.py` for
 * `dodaios/core/config.py`), repeat the project folder's own name
 * (`Dodaios/docs/x.md`), or give only a name (`state.py`). One file that fits
 * is that file; several that fit are no answer, so a guess never opens the
 * wrong one.
 *
 * Adapted from pingdotgg/t3code @ 2c4310eb
 * (packages/client-runtime/src/workspaceBasenameLookup.ts:
 * stripRepeatedWorkspacePrefix, pickWorkspaceLinkMatch,
 * pickWorkspaceBasenameMatch), MIT License, Copyright (c) 2026 T3 Tools Inc.
 * — third_party/t3code/LICENSE. Changes: it reads the project's whole file
 * list instead of a search, a bare name must be unique, and folders are found
 * the same way.
 */

export interface ProjectPathMatch {
  /** Relative to the thread's folder, with forward slashes. */
  path: string;
  kind: "file" | "directory";
}

function isWindowsPath(path: string): boolean {
  return /^[a-z]:[\\/]/i.test(path);
}

function baseName(path: string): string {
  return path.slice(path.lastIndexOf("/") + 1);
}

/** `Dodaios/docs/x.md` named from `/Users/me/Dodaios` is `docs/x.md`. */
function stripRepeatedFolder(path: string, folder: string): string | null {
  const parts = path.split("/");
  const folderParts = folder.split(/[\\/]+/).filter(Boolean);
  const fold = isWindowsPath(folder) ? (part: string | undefined) => part?.toLowerCase() : (part: string | undefined) => part;
  for (let count = Math.min(folderParts.length, parts.length - 1); count > 0; count -= 1) {
    const tail = folderParts.slice(-count);
    if (tail.every((part, index) => fold(part) === fold(parts[index]))) return parts.slice(count).join("/") || null;
  }
  return null;
}

/** The one file of that name; failing that, the one whose name matches ignoring case. */
function uniqueName(name: string, files: readonly string[]): string | null {
  const exact = files.filter((file) => baseName(file) === name);
  if (exact.length) return exact.length === 1 ? exact[0] : null;
  const folded = name.toLowerCase();
  const loose = files.filter((file) => baseName(file).toLowerCase() === folded);
  return loose.length === 1 ? loose[0] : null;
}

/** Every folder whose path is `tail` or ends in `/tail`, read off the files inside them. */
function foldersEndingWith(tail: string, files: readonly string[]): string[] {
  const found = new Set<string>();
  const inner = `/${tail}/`;
  for (const file of files) {
    if (file.startsWith(`${tail}/`)) found.add(tail);
    for (let at = file.indexOf(inner); at >= 0; at = file.indexOf(inner, at + 1)) {
      found.add(file.slice(0, at + inner.length - 1));
    }
  }
  return [...found];
}

/**
 * The file or folder `written` means among `files` (paths relative to the
 * thread's `folder`), or null when none or several fit. A path that cannot be
 * meant from inside the project (absolute, `~`, `./`, `../`) is never looked up.
 */
export function matchProjectPath(written: string, folder: string, files: readonly string[]): ProjectPathMatch | null {
  const clean = written.trim().replace(/\\/g, "/");
  if (!clean || clean.startsWith("/") || isWindowsPath(clean) || /^(?:\.{1,2}|~)(?:\/|$)/.test(clean)) return null;
  const wantsFolder = clean.endsWith("/");
  const target = clean.replace(/\/+$/, "");
  if (!target) return null;

  if (!target.includes("/")) {
    const file = wantsFolder ? null : uniqueName(target, files);
    if (file) return { path: file, kind: "file" };
    const folders = foldersEndingWith(target, files);
    return folders.length === 1 ? { path: folders[0], kind: "directory" } : null;
  }

  const stripped = stripRepeatedFolder(target, folder);
  if (stripped) {
    if (!wantsFolder && files.includes(stripped)) return { path: stripped, kind: "file" };
    if (files.some((file) => file.startsWith(`${stripped}/`))) return { path: stripped, kind: "directory" };
  }
  if (!wantsFolder) {
    const hits = files.filter((file) => file === target || file.endsWith(`/${target}`));
    if (hits.length) return hits.length === 1 ? { path: hits[0], kind: "file" } : null;
  }
  const folders = foldersEndingWith(target, files);
  return folders.length === 1 ? { path: folders[0], kind: "directory" } : null;
}

/**
 * The project's files as seen from the thread's folder: the listing is
 * relative to the workspace folder, the answer to the thread's. A thread
 * outside the workspace folder has no listing here (null).
 */
export function filesFromFolder(files: readonly string[], workspaceFolder: string, threadFolder: string): string[] | null {
  const windows = isWindowsPath(workspaceFolder);
  const key = (path: string) => {
    const clean = path.replace(/\\/g, "/").replace(/\/+$/, "");
    return windows ? clean.toLowerCase() : clean;
  };
  const root = key(workspaceFolder);
  const here = key(threadFolder);
  if (!root || !here) return null;
  if (here === root) return files.map((file) => file.replace(/\\/g, "/"));
  if (!here.startsWith(`${root}/`)) return null;
  const prefix = `${here.slice(root.length + 1)}/`;
  const fold = windows ? (path: string) => path.toLowerCase() : (path: string) => path;
  return files
    .map((file) => file.replace(/\\/g, "/"))
    .filter((file) => fold(file).startsWith(prefix))
    .map((file) => file.slice(prefix.length));
}
