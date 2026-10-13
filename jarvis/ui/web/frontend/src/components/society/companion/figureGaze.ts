/**
 * Eyes that follow the pointer. Every living pair of eyes on screen (see
 * ShapeFigure) registers its wrapper here; one passive listener for the
 * whole window turns the pointer's place into two CSS lengths per pair, at
 * most once a frame and only while the pointer moves. Out of reach, a pair
 * goes back to glancing about by itself.
 */

/** A pair looks at the pointer while it is this close, CSS pixels. */
const REACH_PX = 380;
/** The eyes are fully turned once the pointer is this far away. */
const FULL_PX = 110;
/** How far the pair moves across and up or down, in symbol units (`em` on the wrapper). */
const TURN_X = 1.35, TURN_Y = 0.85;

const pairs = new Set<HTMLElement>();
let pointerX = 0, pointerY = 0;
let scheduled = false;

function rest(pair: HTMLElement): void {
  if (!pair.dataset.following) return;
  delete pair.dataset.following;
  pair.style.removeProperty("--agent-look-x");
  pair.style.removeProperty("--agent-look-y");
}

function look(): void {
  scheduled = false;
  // Measure every pair first, then write: no layout is forced between two writes.
  const measured = [...pairs].map(pair => ({ pair, box: pair.getBoundingClientRect() }));
  for (const { pair, box } of measured) {
    const dx = pointerX - (box.left + box.width / 2), dy = pointerY - (box.top + box.height / 2);
    const distance = Math.hypot(dx, dy);
    if (!box.width || distance > REACH_PX) { rest(pair); continue; }
    const pull = Math.min(1, distance / FULL_PX) / (distance || 1);
    pair.style.setProperty("--agent-look-x", `${(dx * pull * TURN_X).toFixed(2)}em`);
    pair.style.setProperty("--agent-look-y", `${(dy * pull * TURN_Y).toFixed(2)}em`);
    pair.dataset.following = "true";
  }
}

function onMove(event: PointerEvent): void {
  pointerX = event.clientX;
  pointerY = event.clientY;
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(look);
}

function onLeave(): void {
  pairs.forEach(rest);
}

/**
 * Lets a pair of eyes follow the pointer until the returned function is
 * called. With reduced motion (or without a window) nothing is registered.
 */
export function followPointer(pair: HTMLElement): () => void {
  if (typeof window === "undefined" || typeof window.matchMedia !== "function") return () => {};
  if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return () => {};
  pairs.add(pair);
  if (pairs.size === 1) {
    window.addEventListener("pointermove", onMove, { passive: true });
    document.documentElement.addEventListener("pointerleave", onLeave);
  }
  return () => {
    pairs.delete(pair);
    if (pairs.size) return;
    window.removeEventListener("pointermove", onMove);
    document.documentElement.removeEventListener("pointerleave", onLeave);
  };
}
