/**
 * The node window's outline and how its code is fetched: the two things the
 * app needs BEFORE the window's own chunk is there.
 *
 * The window has to be on screen at the click (the maintainer, 2026-11-16:
 * it took three to five seconds the first time, behind nothing but a dimmed
 * page). Two things make that so:
 *
 * - its chunk (the stage and everything the stage draws with, some fifty
 *   files) is fetched while the app idles, and again when the pointer reaches
 *   a card that opens it, so the click finds it loaded;
 * - when a click is still faster than that, the window's frame is drawn at
 *   once from these classes with the node's name and a working close button
 *   (`NodePeekHost`), and the content takes its place inside the same frame.
 *
 * Nothing here may import the window: this file is part of the app's entry.
 */

/** The dimmed ground. No blur: a blurred full-window layer over a live app costs every frame. */
export const PEEK_SCRIM_CLASS = "absolute inset-0 bg-scrim/60";

/** Under the window caption (32px), then the same margin on every side. */
export const PEEK_FRAME_CLASS =
  "absolute inset-x-3 bottom-3 top-11 flex overflow-hidden rounded-2xl border border-border-strong bg-background shadow-float outline-none " +
  "sm:inset-x-6 sm:bottom-6 sm:top-14 xl:inset-x-10 xl:bottom-9 xl:top-[68px]";

type WindowModule = typeof import("./NodePeekWindow");

let pending: Promise<WindowModule> | null = null;

/** The window's chunk, fetched once. A fetch that failed is tried again on the next call. */
export function loadNodePeekWindow(): Promise<WindowModule> {
  pending ??= import("./NodePeekWindow").catch((error: unknown) => {
    pending = null;
    throw error;
  });
  return pending;
}

/**
 * Fetch what the window needs ahead of the click: its own chunk, the
 * conversation it draws beside the node, and the watcher every typed node
 * mounts. Safe to call often; a failure is the click's to report.
 */
export function preloadNodePeek(): void {
  void loadNodePeekWindow().catch(() => undefined);
  void import("@/components/home/ChatStage").catch(() => undefined);
  void import("@/components/nodes/NodeUpkeepBar").catch(() => undefined);
}
