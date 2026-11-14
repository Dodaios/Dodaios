/**
 * The person's library of reusable shapes, shared by every board.
 *
 * It lives in this module while the app runs, so a shape kept on one board
 * is there on the next one, and is mirrored into the page's storage. The
 * desktop window starts each run with empty storage, so the library does not
 * outlive the app yet; a library file exported from its menu does.
 */
import type { LibraryItems } from "@excalidraw/excalidraw/types";

const STORAGE_KEY = "dodaios.whiteboard.library";

let current: LibraryItems | null = null;

export function readBoardLibrary(): LibraryItems {
  if (current !== null) return current;
  try {
    const stored = window.localStorage.getItem(STORAGE_KEY);
    const parsed: unknown = stored ? JSON.parse(stored) : [];
    current = Array.isArray(parsed) ? (parsed as LibraryItems) : [];
  } catch {
    // Storage unavailable or unreadable: start with an empty library.
    current = [];
  }
  return current;
}

export function writeBoardLibrary(items: LibraryItems): void {
  current = items;
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify(items));
  } catch {
    // Storage full or unavailable: the library still lasts for this run.
  }
}
