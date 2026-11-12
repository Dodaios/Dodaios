/**
 * "Select all" stays inside what the person is reading.
 *
 * Pressed outside a text field, ⌘A / Ctrl+A selects the whole document: the
 * sidebar, the composer, every panel. Nobody means that, and in the desktop
 * app's engine (WebKit) it also paints the selection colour over the empty
 * ground beside and between everything selected: grey slabs left and right of
 * a conversation and a grey band across the composer.
 *
 * A region that is read marks its content with `data-select-all`. The chord
 * then selects that content only: the region the person last pressed or
 * focused in, or else the first one on screen. A text field keeps its own
 * "select all", an open dialog keeps the engine's, and a page without such a
 * region behaves as before.
 */

import { isTextEntryTarget } from "@/lib/shortcutOverlayTrigger";

const SCOPE = "[data-select-all]";
const MODAL = '[role="dialog"][aria-modal="true"], dialog[open]';

function shown(element: Element): boolean {
  if (!element.isConnected || element.closest("[hidden], [inert]")) return false;
  // Without a layout engine (tests) there is nothing more to measure.
  if (typeof element.checkVisibility !== "function") return true;
  return element.checkVisibility({ visibilityProperty: true });
}

/**
 * The content "select all" means when the person is at `from`: the marked
 * region around it, or the nearest one beside it (the conversation of the
 * pane whose header was pressed), or the first one on screen.
 */
export function selectAllScope(from: Node | null): Element | null {
  const start = from instanceof Element ? from : from?.parentElement ?? null;
  for (let element: Element | null = start?.isConnected ? start : document.body; element; element = element.parentElement) {
    if (element.matches(SCOPE) && shown(element)) return element;
    const inside = Array.from(element.querySelectorAll(SCOPE)).find(shown);
    if (inside) return inside;
  }
  return null;
}

/** ⌘A on a Mac keyboard, Ctrl+A elsewhere; never with a second modifier. */
function isSelectAll(event: KeyboardEvent): boolean {
  if (event.key !== "a" && event.key !== "A") return false;
  if (event.shiftKey || event.altKey || event.repeat || event.isComposing) return false;
  return event.metaKey !== event.ctrlKey;
}

/** Listens on the window. Returns the function that removes the listeners. */
export function installSelectAllScope(): () => void {
  let last: Node | null = null;
  const note = (event: Event) => {
    if (event.target instanceof Node) last = event.target;
  };
  const onKeyDown = (event: KeyboardEvent) => {
    if (event.defaultPrevented || !isSelectAll(event) || isTextEntryTarget(event.target)) return;
    const modal = Array.from(document.querySelectorAll(MODAL)).some(shown);
    const scope = modal ? null : selectAllScope(last);
    const selection = scope && document.getSelection();
    if (!scope || !selection) return;
    event.preventDefault();
    selection.selectAllChildren(scope);
  };
  window.addEventListener("pointerdown", note, { capture: true, passive: true });
  window.addEventListener("focusin", note, { capture: true, passive: true });
  window.addEventListener("keydown", onKeyDown);
  return () => {
    window.removeEventListener("pointerdown", note, { capture: true });
    window.removeEventListener("focusin", note, { capture: true });
    window.removeEventListener("keydown", onKeyDown);
  };
}
