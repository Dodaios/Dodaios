/**
 * Move a drawn conversation to another place in the page without drawing it
 * again, and without the reader losing their place in it.
 *
 * The node window shows the conversation the click came from. Drawing that
 * conversation a second time is the expensive way: every message is built
 * again, which on a long conversation and a busy machine held the window
 * back for a second and more (measured 2026-11-16). The conversation that is
 * already on the page is moved into the window instead, and moved back when
 * the window closes. A move costs one layout at the new width.
 *
 * A browser forgets how far an element was scrolled when it leaves the page
 * for a moment, and a conversation is narrower beside a node than on its own
 * page. So the place is kept by hand: a reader at the end stays at the end,
 * anyone else keeps the message that led their view at the same height.
 */

/** The scrolling element of the app's scroll areas. */
const VIEWPORT = "[data-radix-scroll-area-viewport]";
/** How close to the end still counts as being at the end. */
const NEAR_END_PX = 8;

interface KeptPlace {
  viewport: HTMLElement;
  atEnd: boolean;
  top: number;
  /** The first message in view, and how far under the viewport's top edge it stood. */
  anchor: HTMLElement | null;
  offset: number;
}

function placeOf(viewport: HTMLElement): KeptPlace {
  const edge = viewport.getBoundingClientRect().top;
  const atEnd = viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= NEAR_END_PX;
  let anchor: HTMLElement | null = null;
  let offset = 0;
  if (!atEnd) {
    for (const message of viewport.querySelectorAll<HTMLElement>("[data-message-id]")) {
      const box = message.getBoundingClientRect();
      if (box.bottom <= edge) continue;
      anchor = message;
      offset = box.top - edge;
      break;
    }
  }
  return { viewport, atEnd, top: viewport.scrollTop, anchor, offset };
}

function restore(place: KeptPlace): void {
  const { viewport, atEnd, top, anchor, offset } = place;
  if (atEnd) {
    viewport.scrollTop = viewport.scrollHeight;
    return;
  }
  viewport.scrollTop = top;
  if (anchor?.isConnected) {
    viewport.scrollTop += anchor.getBoundingClientRect().top - viewport.getBoundingClientRect().top - offset;
  }
}

/**
 * Make `element` the last child of `target`. Nothing happens when it already
 * is one of its children. Where the browser can move an element without
 * taking it off the page (`moveBefore`), framed pages in it do not load again.
 */
export function moveKeepingPlace(element: HTMLElement, target: HTMLElement): void {
  if (element.parentElement === target) return;
  const places = [...element.querySelectorAll<HTMLElement>(VIEWPORT)].map(placeOf);
  const mover = target as HTMLElement & { moveBefore?: (node: Node, before: Node | null) => void };
  let moved = false;
  if (typeof mover.moveBefore === "function" && element.isConnected && target.isConnected) {
    try {
      mover.moveBefore(element, null);
      moved = true;
    } catch {
      // Not movable in place (another document, a shadow tree): the plain way then.
    }
  }
  if (!moved) target.appendChild(element);
  for (const place of places) restore(place);
}
