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

/** What to tell the backend about `panel` right now. */
export function measurePanel(panel: HTMLElement | null, owner: string): PanelPlacement {
  const hidden: PanelPlacement = { owner, visible: false, rect: null, dpr: window.devicePixelRatio || 1 };
  if (!panel || document.visibilityState === "hidden") return hidden;
  const box = panel.getBoundingClientRect();
  // A `hidden` ancestor (another side panel tab, another workspace) gives a 0 box.
  if (box.width < 2 || box.height < 2) return hidden;
  if (overlayCovers(panel)) return hidden;
  return {
    owner,
    visible: true,
    rect: { x: box.x, y: box.y, width: box.width, height: box.height },
    dpr: window.devicePixelRatio || 1,
  };
}

const HEARTBEAT_MS = 1000;

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
 * Layout changes that move the panel without resizing it (a sidebar folding,
 * the window being maximized) do not reach a ResizeObserver, so the rectangle
 * is also checked on a short timer, and right after every click or key press
 * (which is how app menus open). Only changes are sent, one request at a
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

    const check = () => {
      if (disposed) return;
      const placement = measurePanel(panel.current, owner);
      setVisible(placement.visible);
      // A shown window is confirmed every second; the backend hides it when the
      // confirmations stop (the page reloaded or crashed without cleaning up).
      const heartbeat = placement.visible && Date.now() - lastSentAt > HEARTBEAT_MS;
      if (heartbeat || !samePlacement(sent.current, placement)) send(placement);
    };

    let frame = 0;
    const schedule = () => {
      if (frame) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        check();
      });
    };

    // Menus and dialogs open from a click or a key: look again right after.
    const soon = () => {
      schedule();
      window.setTimeout(schedule, 60);
    };

    check();
    const timer = window.setInterval(check, 250);
    const resize = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(schedule);
    if (panel.current) resize?.observe(panel.current);
    window.addEventListener("resize", schedule);
    document.addEventListener("visibilitychange", schedule);
    document.addEventListener("pointerdown", soon, true);
    document.addEventListener("keydown", soon, true);
    return () => {
      disposed = true;
      if (frame) cancelAnimationFrame(frame);
      window.clearInterval(timer);
      resize?.disconnect();
      window.removeEventListener("resize", schedule);
      document.removeEventListener("visibilitychange", schedule);
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
