import { ChatLibraryError, fetchProjectLaunchers, type ProjectLaunchers } from "@/lib/chatLibraryApi";
import cursorLogo from "@/assets/editors/cursor.svg?url";
import vscodeLogo from "@/assets/editors/vscode.svg?url";
import { translate } from "@/i18n";

/**
 * Where a project's folder can be opened (editors, the file manager, its
 * web page), shared by both sidebars' project menus.
 */

export const NO_LAUNCHERS: ProjectLaunchers = { file_manager: false, editors: [], remote_url: null, remote_label: null };

/**
 * What a 405 on a project route means: this view already knows the action,
 * but the backend serving it predates the endpoint. A restart brings the two
 * back in step.
 */
export const NEEDS_RESTART = "ide_projects.reorder_needs_restart";

// Launchers outlive the tree, so a menu opened after switching views is
// complete at once instead of growing its editor rows a moment later.
const launcherCache = new Map<string, ProjectLaunchers>();
const launcherRequests = new Map<string, Promise<ProjectLaunchers>>();

/** The launchers already known for a project, without asking the backend. */
export function cachedLaunchers(projectId: string): ProjectLaunchers | undefined {
  return launcherCache.get(projectId);
}

/** Every cached launcher set, for a view's first render. */
export function allCachedLaunchers(): Record<string, ProjectLaunchers> {
  return Object.fromEntries(launcherCache);
}

/** One launcher request per project at a time; settles into the cache. */
export function loadLaunchers(projectId: string): Promise<ProjectLaunchers> {
  const pending = launcherRequests.get(projectId);
  if (pending) return pending;
  const request = fetchProjectLaunchers(projectId)
    // A headless or older backend has no launchers; the menu simply omits them.
    .catch(() => NO_LAUNCHERS)
    .then((found) => { launcherCache.set(projectId, found); return found; })
    .finally(() => { launcherRequests.delete(projectId); });
  launcherRequests.set(projectId, request);
  return request;
}

/** Test hook: forget every cached launcher set. */
export function resetLauncherCacheForTests(): void {
  launcherCache.clear();
  launcherRequests.clear();
}

/** Why opening a folder failed, in the user's terms. */
export function revealErrorMessage(error: unknown): string {
  if (error instanceof ChatLibraryError && error.message === "native-file-actions-disabled") {
    return translate("ide_projects.reveal_desktop_only");
  }
  if (error instanceof ChatLibraryError && (error.status === 405 || (error.status === 404 && error.message === "Not Found"))) {
    return translate(NEEDS_RESTART);
  }
  return error instanceof Error ? error.message : String(error);
}

/** What the OS calls its file manager, for the "show the folder" item (a locale key). */
export const FILE_MANAGER_LABEL = (() => {
  const platform = typeof navigator === "undefined" ? "" : navigator.userAgent;
  if (/Windows/i.test(platform)) return "ide_projects.show_in_explorer";
  if (/Mac OS X|Macintosh/i.test(platform)) return "ide_projects.show_in_finder";
  return "ide_projects.show_in_file_manager";
})();

/** Each featured editor's own app icon, in its real colours. */
export const EDITOR_LOGOS: Record<string, string> = { code: vscodeLogo, cursor: cursorLogo };
/** Single-colour editor glyphs (src/assets/editors/LOGOS.md), drawn in the text ink. */
export const MONO_EDITOR_LOGOS = new Set(["cursor"]);
