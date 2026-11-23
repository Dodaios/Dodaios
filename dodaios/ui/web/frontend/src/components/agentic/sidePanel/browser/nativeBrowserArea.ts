import { create } from "zustand";

/** A panel's box in CSS pixels of the page. */
export interface AreaBox {
  left: number;
  top: number;
  right: number;
  bottom: number;
}

interface NativeBrowserAreaState {
  /** The box of every browser panel on screen, by owner. */
  areas: Record<string, AreaBox>;
  setArea: (owner: string, box: AreaBox | null) => void;
}

function sameBox(a: AreaBox | undefined, b: AreaBox | null): boolean {
  if (!a || !b) return !a && !b;
  return a.left === b.left && a.top === b.top && a.right === b.right && a.bottom === b.bottom;
}

/**
 * Where the native browser panel stands on the page. The browser is a native
 * window drawn above the page, so page layers that must stay readable (the
 * toast stack) read this to stand beside it. It holds the panel's box while
 * the panel is on screen, also while a popup hides the window for a moment:
 * a layer that moved aside must not jump back and forth.
 */
export const useNativeBrowserArea = create<NativeBrowserAreaState>((set, get) => ({
  areas: {},
  setArea: (owner, box) => {
    const rounded = box && {
      left: Math.round(box.left),
      top: Math.round(box.top),
      right: Math.round(box.right),
      bottom: Math.round(box.bottom),
    };
    if (sameBox(get().areas[owner], rounded)) return;
    set((s) => {
      const areas = { ...s.areas };
      if (rounded) areas[owner] = rounded;
      else delete areas[owner];
      return { areas };
    });
  },
}));

/** Width of the toast stack plus its margins. */
const STACK_WIDTH = 320;
const EDGE = 16;
/** The stack's top edge (top-12) and a generous height for a few toasts. */
const STACK_TOP = 48;
const STACK_REACH = 360;

/**
 * Where the toast stack goes so no browser panel covers it. `right` is the
 * stack's distance from the right edge of the page when it must move left of
 * a panel; `hidesBrowser` is set when no room is left beside the panel, so the
 * browser steps back while a toast shows (the popup scan sees the stack).
 */
export function toastPlacement(
  areas: Record<string, AreaBox>,
  pageWidth: number,
): { right: number | null; hidesBrowser: boolean } {
  let right: number | null = null;
  for (const box of Object.values(areas)) {
    const stackRight = right ?? EDGE;
    const stackLeft = pageWidth - stackRight - STACK_WIDTH;
    const overlaps = box.left < pageWidth - stackRight && box.right > stackLeft
      && box.top < STACK_TOP + STACK_REACH && box.bottom > STACK_TOP;
    if (!overlaps) continue;
    const moved = pageWidth - box.left + EDGE;
    if (pageWidth - moved - STACK_WIDTH < EDGE) return { right: null, hidesBrowser: true };
    right = Math.max(right ?? 0, moved);
  }
  return { right, hidesBrowser: false };
}
