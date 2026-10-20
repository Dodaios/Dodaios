import { useEffect, useRef, useState, type RefObject } from "react";

import { placeNativeBrowser, type PanelPlacement } from "./nativeBrowserApi";

/**
 * Popups of the app that can open over the panel. The browser is a separate
 * native window drawn above the page, so it would cover them; while one
 * overlaps the panel the browser is hidden instead.
 */
const OVERLAY_SELECTOR = [
  '[role="dialog"]',
  '[role="alertdialog"]',
  '[role="menu"]',
  '[role="listbox"]',
  "[data-radix-popper-content-wrapper]",
].join(",");

interface Box {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

export function boxesOverlap(a: Box, b: Box): boolean {
  return a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom;
}

/** Whether an app popup (outside `panel`) currently covers part of the panel. */
export function overlayCovers(panel: HTMLElement, root: ParentNode = document): boolean {
  const own = panel.getBoundingClientRect();
  for (const node of Array.from(root.querySelectorAll<HTMLElement>(OVERLAY_SELECTOR))) {
    if (panel.contains(node) || node.contains(panel)) continue;
    const box = node.getBoundingClientRect();
    if (box.width <= 0 || box.height <= 0) continue;
    if (boxesOverlap(own, box)) return true;
  }
  return false;
}

/**
 * What to tell the backend about `panel` right now. `covered` passes the popup
 * scan's answer in when it is already known (the scan runs less often).
 */
export function measurePanel(
  panel: HTMLElement | null,
  owner: string,
  covered?: boolean,
): PanelPlacement {
  const hidden: PanelPlacement = { owner, visible: false, rect: null, dpr: window.devicePixelRatio || 1 };
  if (!panel || document.visibilityState === "hidden") return hidden;
  const box = panel.getBoundingClientRect();
  // A `hidden` ancestor (another side panel tab, another workspace) gives a 0 box.
  if (box.width < 2 || box.height < 2) return hidden;
  if (covered ?? overlayCovers(panel)) return hidden;
  return {
    owner,
    visible: true,
    rect: { x: box.x, y: box.y, width: box.width, height: box.height },
    dpr: window.devicePixelRatio || 1,
  };
}

const HEARTBEAT_MS = 1000;
const OVERLAY_SCAN_MS = 100;
const HIDDEN_CHECK_MS = 250;

function samePlacement(a: PanelPlacement | null, b: PanelPlacement): boolean {
  if (!a || a.visible !== b.visible || a.dpr !== b.dpr) return false;
  if (!a.rect || !b.rect) return a.rect === b.rect;
  return (
    Math.round(a.rect.x) === Math.round(b.rect.x)
    && Math.round(a.rect.y) === Math.round(b.rect.y)
    && Math.round(a.rect.width) === Math.round(b.rect.width)
    && Math.round(a.rect.height) === Math.round(b.rect.height)
  );
}

/**
 * Keep the native browser window on `panel`'s rectangle, and hide it whenever
 * the panel is not on screen. Returns whether the panel is visible.
 *
 * The rectangle is read on every animation frame while the panel is on screen,
 * so the browser window follows a dragged panel edge or a layout animation
 * frame by frame (a ResizeObserver misses moves without a resize). The scan
 * for app popups over the panel is heavier: it runs every 100 ms, and at once
 * after a click or key press (which is how app menus open). While the panel is
 * hidden it is checked every 250 ms. Only changes are sent, one request at a
 * time, and only the newest placement waits behind it.
 */
export function useNativePlacement(
  panel: RefObject<HTMLElement | null>,
  owner: string,
  generation: unknown,
): boolean {
  const [visible, setVisible] = useState(false);
  const sent = useRef<PanelPlacement | null>(null);
  const inFlight = useRef(false);
  const queued = useRef<PanelPlacement | null>(null);

  useEffect(() => {
    let disposed = false;
    sent.current = null; // a new generation (window taken, profile switched) resends

    let lastSentAt = 0;
    const send = (placement: PanelPlacement) => {
      if (inFlight.current) {
        queued.current = placement;
        return;
      }
      inFlight.current = true;
      lastSentAt = Date.now();
      void placeNativeBrowser(placement).then((result) => {
        // Remember it only once the backend took it: a lost hide is sent again.
        sent.current = result.ok ? placement : null;
      }).finally(() => {
        inFlight.current = false;
        const next = queued.current;
        queued.current = null;
        if (next && !samePlacement(sent.current, next)) send(next);
      });
    };

    let covered = false;
    let coveredAt = 0;
    let forceScan = true;
    const check = (): boolean => {
      const now = performance.now();
      if (forceScan || now - coveredAt > OVERLAY_SCAN_MS) {
        covered = panel.current ? overlayCovers(panel.current) : false;
        coveredAt = now;
        forceScan = false;
      }
      const placement = measurePanel(panel.current, owner, covered);
      setVisible(placement.visible);
      // A shown window is confirmed every second; the backend hides it when the
      // confirmations stop (the page reloaded or crashed without cleaning up).
      const heartbeat = placement.visible && Date.now() - lastSentAt > HEARTBEAT_MS;
      if (heartbeat || !samePlacement(sent.current, placement)) send(placement);
      return placement.visible;
    };

    // Every frame while shown; a slow timer while hidden.
    let frame = 0;
    let idle = 0;
    const tick = () => {
      frame = 0;
      idle = 0;
      if (disposed) return;
      if (check()) frame = requestAnimationFrame(tick);
      else idle = window.setTimeout(tick, HIDDEN_CHECK_MS);
    };
    const wake = () => {
      forceScan = true;
      if (frame || disposed) return;
      window.clearTimeout(idle);
      frame = requestAnimationFrame(tick);
    };

    // Menus and dialogs open from a click or a key: look again right after.
    const soon = () => {
      wake();
      window.setTimeout(wake, 60);
    };

    tick();
    window.addEventListener("resize", wake);
    document.addEventListener("visibilitychange", wake);
    document.addEventListener("pointerdown", soon, true);
    document.addEventListener("keydown", soon, true);
    return () => {
      disposed = true;
      if (frame) cancelAnimationFrame(frame);
      window.clearTimeout(idle);
      window.removeEventListener("resize", wake);
      document.removeEventListener("visibilitychange", wake);
      document.removeEventListener("pointerdown", soon, true);
      document.removeEventListener("keydown", soon, true);
    };
  }, [panel, owner, generation]);

  // Leaving the page (tab closed, workspace removed, reload) hides the window.
  useEffect(() => {
    const hide = () => {
      void placeNativeBrowser({ owner, visible: false, rect: null, dpr: window.devicePixelRatio || 1 });
    };
    window.addEventListener("pagehide", hide);
    return () => {
      window.removeEventListener("pagehide", hide);
      hide();
    };
  }, [owner]);

  return visible;
}
