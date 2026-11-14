/**
 * Moving a project folder in a sidebar list by drag and drop or Alt+arrow.
 *
 * Both sidebars (the workspace tree and the thread tree) list the visible
 * projects in two sections, pinned first. A folder moves only inside its own
 * section; the whole visible order, both sections front to back, is what the
 * backend stores (`PUT /api/chat-library/projects/order`).
 */
import { ChatLibraryError } from "@/lib/chatLibraryApi";
import { IdeApiError } from "@/lib/agenticIdeApi";
import { translate } from "@/i18n";

/** The drag payload type of a project folder row. */
export const PROJECT_DRAG_MIME = "application/x-jarvis-project-id";

interface Orderable { id: string; pinned?: boolean }

/**
 * The visible order after `sourceId` is dropped before or after `targetId`,
 * or null when nothing would change (same row, other section, unknown id).
 */
export function projectOrderAfterMove<T extends Orderable>(visible: T[], sourceId: string, targetId: string, before: boolean): string[] | null {
  if (sourceId === targetId) return null;
  const pinned = visible.filter((project) => project.pinned);
  const unpinned = visible.filter((project) => !project.pinned);
  const section = pinned.some((project) => project.id === sourceId) ? pinned : unpinned;
  if (!section.some((project) => project.id === sourceId)) return null;
  if (!section.some((project) => project.id === targetId)) return null;
  const without = section.map((project) => project.id).filter((id) => id !== sourceId);
  const targetIndex = without.indexOf(targetId);
  const insertAt = before ? targetIndex : targetIndex + 1;
  const sectionNext = [...without.slice(0, insertAt), sourceId, ...without.slice(insertAt)];
  if (sectionNext.join("\u0000") === section.map((project) => project.id).join("\u0000")) return null;
  const pinnedIds = section === pinned ? sectionNext : pinned.map((project) => project.id);
  const unpinnedIds = section === unpinned ? sectionNext : unpinned.map((project) => project.id);
  return [...pinnedIds, ...unpinnedIds];
}

/** The neighbour Alt+ArrowUp/ArrowDown swaps with inside the folder's section, if any. */
export function projectNeighbour<T extends Orderable>(visible: T[], projectId: string, up: boolean): T | null {
  const project = visible.find((entry) => entry.id === projectId);
  if (!project) return null;
  const section = visible.filter((entry) => Boolean(entry.pinned) === Boolean(project.pinned));
  const index = section.findIndex((entry) => entry.id === projectId);
  return section[up ? index - 1 : index + 1] ?? null;
}

/** `items` sorted to follow `ids`; items not named keep their place at the end. */
export function sortByIds<T extends { id: string }>(items: T[], ids: string[]): T[] {
  const rank = new Map(ids.map((id, index) => [id, index] as const));
  return [...items].sort((left, right) => (rank.get(left.id) ?? ids.length) - (rank.get(right.id) ?? ids.length));
}

/** Shown when the view is newer than the backend, instead of a bare "405 Method Not Allowed". */
const REORDER_NEEDS_RESTART = "ide_projects.reorder_needs_restart";

/** A reorder failure in the user's terms: a stale backend gets the fix, anything else the server's own words. */
export function reorderErrorMessage(error: unknown): string {
  if (error instanceof IdeApiError && error.status === 405) return translate(REORDER_NEEDS_RESTART);
  if (error instanceof ChatLibraryError && error.status === 405) return translate(REORDER_NEEDS_RESTART);
  return error instanceof Error ? error.message : String(error);
}
