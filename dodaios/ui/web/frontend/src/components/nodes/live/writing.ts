/**
 * Motions for a unit that is not best shown by a plain fade (`UnitMotion` in
 * `playback.ts`): text written at a caret, and a picture or chart that shows
 * its skeleton first.
 *
 * Neither touches the editor's DOM or styles. Unwritten text is hidden with
 * the CSS Custom Highlight API (`::highlight(live-unwritten)` in `live.css`
 * makes it transparent), which paints over ranges and so never fights a text
 * editor's own rendering. Where that API is missing, `canWriteText` is false
 * and the type falls back to a block fade.
 */
import type { UnitMotion } from "./playback";

const HIGHLIGHT = "live-unwritten";
/** One word group is written this often at natural speed. */
export const GROUP_MS = 55;
/** A long text is written in at most this many groups; longer ones get bigger groups. */
const MAX_GROUPS = 40;
const WORDS_PER_GROUP = 3;
const GHOST_FADE_MS = 260;
/** How long a skeleton stands before its picture fades in. */
export const SKELETON_MS = 320;
const SKELETON_FADE_MS = 220;

interface HighlightApi {
  registry: { set(name: string, value: unknown): void; delete(name: string): void };
  make: (...ranges: Range[]) => unknown;
}

function highlightApi(): HighlightApi | null {
  const css = (globalThis as { CSS?: { highlights?: HighlightApi["registry"] } }).CSS;
  const Highlight = (globalThis as { Highlight?: new (...ranges: Range[]) => unknown }).Highlight;
  if (!css?.highlights || typeof Highlight !== "function") return null;
  return { registry: css.highlights, make: (...ranges) => new Highlight(...ranges) };
}

/** Can text be hidden and written in without touching the editor? */
export function canWriteText(): boolean {
  return highlightApi() !== null;
}

/** Every range still waiting to be written, in any editor on the page. */
const unwritten = new Set<Range>();

function paintUnwritten(): void {
  const api = highlightApi();
  if (!api) return;
  if (unwritten.size === 0) api.registry.delete(HIGHLIGHT);
  else api.registry.set(HIGHLIGHT, api.make(...unwritten));
}

function textNodesOf(el: Element): Text[] {
  const out: Text[] = [];
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  for (let n = walker.nextNode(); n; n = walker.nextNode()) out.push(n as Text);
  return out;
}

/** The text node and offset at character `index` of the element's text. */
function pointAt(nodes: readonly Text[], index: number): { node: Text; offset: number } | null {
  let left = Math.max(0, index);
  for (const node of nodes) {
    const length = node.data.length;
    if (left <= length) return { node, offset: left };
    left -= length;
  }
  const last = nodes[nodes.length - 1];
  return last ? { node: last, offset: last.data.length } : null;
}

/** The character offsets where each word group of `text[from, to)` ends; the last is `to`. */
export function groupEnds(text: string, from: number, to: number): number[] {
  const words = [...text.slice(from, to).matchAll(/\S+\s*/g)];
  if (words.length === 0) return [to];
  const size = Math.max(WORDS_PER_GROUP, Math.ceil(words.length / MAX_GROUPS));
  const ends: number[] = [];
  for (let i = size - 1; i < words.length; i += size) {
    const word = words[i];
    ends.push(from + (word.index ?? 0) + word[0].length);
  }
  if (ends[ends.length - 1] !== to) ends.push(to);
  return ends;
}

export interface TextWriting {
  /** Where in the element's text the new words start (characters). */
  from: number;
  /** Where they end; the end of the text by default. */
  to?: number;
  /** The words they replace, shown fading out where the new ones write in. */
  removed?: string;
}

/**
 * Writes the words `[from, to)` of a text block in, a word group at a time.
 * Text before `from` stays; a replaced passage shows the old words fading out.
 */
export function textWriting(element: Element, spec: TextWriting): UnitMotion {
  const full = element.textContent ?? "";
  const end = Math.min(full.length, spec.to ?? full.length);
  const from = Math.min(spec.from, end);
  const ends = groupEnds(full, from, end);
  const removed = (spec.removed ?? "").replace(/\s+/g, " ").trim();
  let written = from;
  let hidden: Range | null = null;
  let ghost: HTMLElement | null = null;
  let ghostFade: Animation | null = null;

  const point = (index: number) => pointAt(textNodesOf(element), index);

  const dropGhost = () => {
    ghostFade?.cancel();
    ghostFade = null;
    ghost?.remove();
    ghost = null;
  };

  const dropHidden = () => {
    if (hidden) unwritten.delete(hidden);
    hidden = null;
    paintUnwritten();
  };

  /** The line box of the character just before `index`, or the first one after it. */
  const boxAt = (index: number): { x: number; y: number; h: number } | null => {
    const nodes = textNodesOf(element);
    const text = nodes.map((n) => n.data).join("");
    let at = Math.min(index, text.length) - 1;
    while (at > 0 && /\s/.test(text[at] ?? "")) at -= 1;
    const [a, b, atEnd] = at >= 0 ? [at, at + 1, true] : [0, Math.min(1, text.length), false];
    const start = pointAt(nodes, a);
    const stop = pointAt(nodes, b);
    if (!start || !stop || typeof document.createRange !== "function") return null;
    const range = document.createRange();
    try {
      range.setStart(start.node, start.offset);
      range.setEnd(stop.node, stop.offset);
    } catch {
      return null;
    }
    const rects = range.getClientRects();
    const rect = rects.length > 0 ? rects[rects.length - 1] : null;
    if (!rect || (rect.width === 0 && rect.height === 0)) return null;
    return { x: atEnd ? rect.right : rect.left, y: rect.top, h: rect.height };
  };

  const placeGhost = (outer: DOMRect) => {
    if (!ghost) return;
    const lead = boxAt(from);
    if (!lead) return;
    const x = lead.x - outer.left;
    const room = element.getBoundingClientRect().right - lead.x;
    ghost.style.transform = `translate3d(${x.toFixed(1)}px, ${(lead.y - outer.top).toFixed(1)}px, 0)`;
    ghost.style.maxWidth = `${Math.max(40, room).toFixed(0)}px`;
    ghost.style.height = `${lead.h.toFixed(1)}px`;
  };

  return {
    durationMs: ends.length * GROUP_MS,
    steps: ends.length,
    prepare(host) {
      const a = point(from);
      const b = point(end);
      if (a && b && typeof document.createRange === "function") {
        hidden = document.createRange();
        hidden.setStart(a.node, a.offset);
        hidden.setEnd(b.node, b.offset);
        unwritten.add(hidden);
        paintUnwritten();
      }
      if (removed && typeof window.getComputedStyle === "function") {
        const style = window.getComputedStyle(element);
        ghost = document.createElement("span");
        ghost.className = "live-ghost";
        ghost.textContent = removed;
        ghost.style.font = style.font;
        ghost.style.color = style.color;
        host.appendChild(ghost);
        placeGhost(host.getBoundingClientRect());
      }
    },
    start() {
      if (ghost && typeof ghost.animate === "function") {
        ghostFade = ghost.animate([{ opacity: 0.7 }, { opacity: 0 }], {
          duration: GHOST_FADE_MS,
          easing: "ease-out",
          fill: "forwards",
        });
        ghostFade.onfinish = dropGhost;
      } else dropGhost();
    },
    advance(step) {
      written = ends[Math.min(step, ends.length) - 1] ?? end;
      if (hidden) {
        const next = point(written);
        if (next && written < end) {
          hidden.setStart(next.node, next.offset);
          paintUnwritten();
        } else dropHidden();
      }
    },
    finish() {
      written = end;
      dropHidden();
      dropGhost();
    },
    update(outer) {
      placeGhost(outer);
    },
    caret() {
      return boxAt(written);
    },
  };
}

/**
 * A picture or chart that shows a quiet skeleton where it will stand, then
 * fades in as the skeleton fades out. The element itself is only held
 * transparent with an animation, as the player does for any unit.
 */
export function skeletonReveal(element: Element, fromOpacity = 0.3): UnitMotion {
  let overlay: HTMLElement | null = null;
  let hold: Animation | null = null;
  let done = false;

  const canAnimate = typeof (element as { animate?: unknown }).animate === "function";

  const place = (outer: DOMRect) => {
    if (!overlay) return;
    const box = element.getBoundingClientRect();
    overlay.style.transform = `translate3d(${(box.left - outer.left).toFixed(1)}px, ${(box.top - outer.top).toFixed(1)}px, 0)`;
    overlay.style.width = `${box.width.toFixed(1)}px`;
    overlay.style.height = `${Math.max(box.height, 24).toFixed(1)}px`;
  };

  const clear = () => {
    hold?.cancel();
    hold = null;
    overlay?.remove();
    overlay = null;
  };

  return {
    durationMs: SKELETON_MS + 120,
    steps: 1,
    prepare(host) {
      if (canAnimate) hold = element.animate([{ opacity: 0 }, { opacity: 0 }], { duration: 600_000, fill: "forwards" });
      overlay = document.createElement("div");
      overlay.className = "live-skeleton live-skeleton-block live-media-skeleton";
      overlay.style.opacity = "0";
      host.appendChild(overlay);
      place(host.getBoundingClientRect());
    },
    start() {
      overlay?.animate?.([{ opacity: 0 }, { opacity: 1 }], { duration: 160, easing: "ease-out", fill: "forwards" });
    },
    advance() {
      if (done) return;
      // The picture fades in while the skeleton fades out.
      hold?.cancel();
      hold = null;
      if (canAnimate) element.animate([{ opacity: fromOpacity }, { opacity: 1 }], { duration: SKELETON_FADE_MS, easing: "ease-out" });
      const gone = overlay;
      overlay = null;
      const out = gone?.animate?.([{ opacity: 1 }, { opacity: 0 }], { duration: SKELETON_FADE_MS, easing: "ease-out", fill: "forwards" });
      if (out) out.onfinish = () => gone?.remove();
      else gone?.remove();
    },
    finish() {
      done = true;
      clear();
    },
    update: place,
  };
}
