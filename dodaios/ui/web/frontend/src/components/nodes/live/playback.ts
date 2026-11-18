/**
 * The playback engine: an agent's batch, played back in reading order.
 *
 * An edit lands in an open editor as one batch, already laid out in its final
 * place (so nothing jumps). This engine hides the batch's units and brings
 * them back one after another: each fades from `fromOpacity` to full over
 * `fadeMs`, `staggerMs` apart, while the presence frame grows around what has
 * been written so far and the agent's cursor glides to each unit. A long
 * batch is compressed so it never takes more than `maxBatchMs`.
 *
 * The person always wins. Typing, a click into the content or a scroll
 * finishes the playback at once, and the view stops following the writing
 * for the rest of the build. With reduced motion the batch shows at once and
 * only the presence (frame, cursor, tag) moves to where it was written.
 *
 * Nothing here touches the editor's own styles or attributes: hiding and
 * fading are Web Animations on the units, so React's next render of the
 * editor never fights them. docs/node-live-build.md, "Timings".
 */
import {
  aimCursor,
  beginCursor,
  stepCursor,
  type CursorMotion,
} from "@/components/society/card/agentCursorMotion";
import type { RevealStep } from "./reveal";

export const LIVE_TIMING = {
  /** One unit's fade. */
  fadeMs: 220,
  /** From one unit's start to the next one's. */
  staggerMs: 90,
  /** The longest one batch plays, however many units it has. */
  maxBatchMs: 3_000,
  /** Where a unit's fade starts. */
  fromOpacity: 0.3,
  /** Units in one batch at most; more are revealed in groups. */
  maxUnits: 60,
  /** How long a batch waits for an editor that draws after React's commit (a text editor). */
  settleWaitMs: 160,
  /** How long after a batch starts a late change in the body still joins it. */
  captureMs: 700,
  /** The node window sliding in. */
  openSlideMs: 150,
} as const;

/** The unit's fade-in delays, compressed so the whole batch fits `maxBatchMs`. */
export function revealDelays(count: number, timing = LIVE_TIMING): number[] {
  if (count <= 0) return [];
  const room = Math.max(0, timing.maxBatchMs - timing.fadeMs);
  const step = count <= 1 ? 0 : Math.min(timing.staggerMs, room / (count - 1));
  return Array.from({ length: count }, (_, i) => Math.round(i * step));
}

/** One step of a batch: the elements that fade in together, and its status. */
export interface RevealUnit {
  elements: Element[];
  label?: string;
}

/** `elements` in document order, each once, without any element inside another listed one. */
export function readingOrder(elements: readonly Element[]): Element[] {
  const unique = [...new Set(elements)].filter((el) => el.isConnected);
  const outer = unique.filter((el) => !unique.some((other) => other !== el && other.contains(el)));
  return outer.sort((a, b) => {
    if (a === b) return 0;
    return a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING ? -1 : 1;
  });
}

function isInline(el: Element): boolean {
  if (typeof window.getComputedStyle !== "function") return false;
  const display = window.getComputedStyle(el).display;
  return display.startsWith("inline") || display === "contents";
}

/** The block an element stands in: inline wrappers (a bold word, a link) lift to their block. */
function blockOf(el: Element, root: Element): Element {
  let at = el;
  while (at.parentElement && at.parentElement !== root && isInline(at)) at = at.parentElement;
  return at;
}

const MEDIA = "img, svg, canvas, video, picture";

/** Something to see: text, or a picture. An empty cell or a spacer is not a unit. */
function hasContent(el: Element): boolean {
  return (el.textContent ?? "").trim() !== "" || el.matches(MEDIA) || el.querySelector(MEDIA) !== null;
}

/**
 * Pinned in place (sticky or fixed, or inside such): a header or a totals row
 * that stays in view. It changes with the batch but is not written in the
 * reading order, and scrolling to it would move the view to the end.
 */
export function isPinned(el: Element, root: Element): boolean {
  if (typeof window.getComputedStyle !== "function") return false;
  for (let at: Element | null = el; at && at !== root; at = at.parentElement) {
    const position = window.getComputedStyle(at).position;
    if (position === "sticky" || position === "fixed") return true;
  }
  return false;
}

/** The elements of `root` that a batch of DOM changes added or rewrote, as reading-order blocks. */
export function changedElements(records: readonly MutationRecord[], root: Element): Element[] {
  const found: Element[] = [];
  const take = (node: Node | null) => {
    const el = node instanceof Element ? node : (node?.parentElement ?? null);
    if (!el || el === root || !root.contains(el) || !el.isConnected) return;
    const block = blockOf(el, root);
    if (!hasContent(block) || isPinned(block, root)) return;
    found.push(block);
  };
  for (const record of records) {
    if (record.type === "characterData") take(record.target);
    else if (record.type === "childList") {
      record.addedNodes.forEach((node) => {
        if (node.nodeType === Node.TEXT_NODE && !(node.textContent ?? "").trim()) return;
        take(node);
      });
    }
  }
  return readingOrder(found);
}

function shown(el: Element): boolean {
  const box = el.getBoundingClientRect();
  return box.width > 0 || box.height > 0;
}

/**
 * The body's top-level blocks: down through the wrappers that hold one child,
 * to the first element with several, whose children are the blocks.
 */
export function topBlocks(root: Element): Element[] {
  let at: Element = root;
  for (let depth = 0; depth < 12; depth += 1) {
    const children = [...at.children].filter(shown);
    if (children.length === 0) return at === root ? [] : [at];
    if (children.length > 1) return children;
    at = children[0];
  }
  return [at];
}

/** At most `max` units: consecutive units are joined into groups when there are more. */
export function grouped(units: RevealUnit[], max: number = LIVE_TIMING.maxUnits): RevealUnit[] {
  if (units.length <= max) return units;
  const size = Math.ceil(units.length / max);
  const out: RevealUnit[] = [];
  for (let i = 0; i < units.length; i += size) {
    const part = units.slice(i, i + size);
    out.push({ elements: part.flatMap((u) => u.elements), label: part.find((u) => u.label)?.label });
  }
  return out;
}

/** The marked element for a JSON Pointer, or for its nearest marked ancestor path. */
export function elementForPath(root: Element, path: string): Element | null {
  const marked = [...root.querySelectorAll("[data-live-path]")];
  if (marked.length === 0) return null;
  const byPath = new Map<string, Element>();
  for (const el of marked) {
    const key = el.getAttribute("data-live-path") ?? "";
    if (!byPath.has(key)) byPath.set(key, el);
  }
  let at = path;
  while (at) {
    const found = byPath.get(at);
    if (found) return found;
    at = at.slice(0, Math.max(0, at.lastIndexOf("/")));
  }
  return null;
}

/**
 * An adapter's steps as units the player can play. `changed` is what the
 * core saw change in the body for this batch. A step that finds nothing is
 * left out; units are kept in the steps' order.
 */
export function unitsFor(steps: readonly RevealStep[], root: Element, changed: readonly Element[]): RevealUnit[] {
  const units: RevealUnit[] = [];
  for (const step of steps) {
    const target = step.target;
    let elements: Element[] = [];
    if ("path" in target) {
      const found = elementForPath(root, target.path);
      elements = found ? [found] : [];
    } else if ("selector" in target) {
      let found: Element | null = null;
      try {
        found = root.querySelector(target.selector);
      } catch {
        // A selector the browser cannot read finds nothing.
      }
      elements = found ? [found] : [];
    } else if ("element" in target) {
      elements = root.contains(target.element) ? [target.element] : [];
    } else if ("changed" in target) {
      for (const el of changed) units.push({ elements: [el], label: step.label });
      continue;
    } else {
      for (const el of topBlocks(root)) units.push({ elements: [el], label: step.label });
      continue;
    }
    if (elements.length > 0) units.push({ elements, label: step.label });
  }
  return grouped(units);
}

/* --- the player ----------------------------------------------------------- */

export interface PresenceElements {
  cursor: HTMLElement;
  frame: HTMLElement;
  tag: HTMLElement;
  pill: HTMLElement;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

const FRAME_PAD = 6;
/** Where the cursor waits before anything was written: the content's top left. */
const HOME = { x: 28, y: 28 };
const PENDING_KEYFRAMES: Keyframe[] = [{ opacity: 0 }, { opacity: 0 }];
const HOLD_MS = 600_000;

function canAnimate(el: Element): el is Element & { animate: Element["animate"] } {
  return typeof (el as { animate?: unknown }).animate === "function";
}

export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

/**
 * Plays batches in one editor body and moves the presence over it.
 *
 * `host` is the layer the presence is drawn in, laid over the body: its
 * coordinates are the presence's. The units are elements of the body.
 */
export class LivePlayer {
  private units: RevealUnit[] = [];
  private revealed = 0;
  private timers: number[] = [];
  /** `performance.now()` of the last scheduled reveal. */
  private slotAt = 0;
  private hidden = new Map<Element, Animation>();
  private frameBox: Box | null = null;
  private motion: CursorMotion | null = null;
  private aimed: Element | null = null;
  private loop = 0;
  private last = 0;
  private alive = true;
  /** The view scrolls to what is written; off once the person scrolled or worked. */
  following = true;

  constructor(
    private readonly host: HTMLElement,
    private readonly view: PresenceElements,
    private readonly reduced: () => boolean = prefersReducedMotion,
    private readonly timing = LIVE_TIMING,
  ) {
    this.loop = window.requestAnimationFrame((now) => this.tick(now));
  }

  /** A batch is playing. */
  get playing(): boolean {
    return this.revealed < this.units.length;
  }

  /** Play `units`, finishing the batch before at once. */
  play(units: RevealUnit[]): void {
    this.finish();
    this.units = [];
    this.revealed = 0;
    this.frameBox = null;
    this.add(units);
  }

  /** Units that joined the running batch late (an editor that draws after React). */
  add(units: RevealUnit[]): void {
    const known = new Set(this.units.flatMap((u) => u.elements));
    const fresh = units
      .map((u) => ({ ...u, elements: u.elements.filter((el) => !known.has(el)) }))
      .filter((u) => u.elements.length > 0);
    if (fresh.length === 0) return;
    const start = this.units.length;
    this.units = [...this.units, ...grouped(fresh, Math.max(1, this.timing.maxUnits - start))];
    if (this.reduced()) {
      this.revealUpTo(this.units.length);
      return;
    }
    for (const unit of this.units.slice(start)) for (const el of unit.elements) this.hide(el);
    // Late units queue behind the ones already scheduled, never ahead of them.
    const now = performance.now();
    const base = start > 0 ? Math.max(0, this.slotAt + this.timing.staggerMs - now) : 0;
    const delays = revealDelays(this.units.length - start, this.timing);
    delays.forEach((delay, i) => {
      this.timers.push(window.setTimeout(() => this.revealUpTo(start + i + 1), base + delay));
    });
    this.slotAt = now + base + (delays[delays.length - 1] ?? 0);
    this.host.dataset.phase = "writing";
  }

  /** Reveal everything of the batch now. */
  finish(): void {
    for (const timer of this.timers) window.clearTimeout(timer);
    this.timers = [];
    this.revealUpTo(this.units.length, true);
  }

  /** The person acted in the node: the batch shows at once and the view stays where they put it. */
  interrupt(): void {
    this.following = false;
    this.finish();
  }

  destroy(): void {
    this.alive = false;
    this.finish();
    for (const animation of this.hidden.values()) animation.cancel();
    this.hidden.clear();
    window.cancelAnimationFrame(this.loop);
  }

  private hide(el: Element): void {
    if (this.hidden.has(el) || !canAnimate(el)) return;
    this.hidden.set(el, el.animate(PENDING_KEYFRAMES, { duration: HOLD_MS, fill: "forwards" }));
  }

  private revealUpTo(count: number, instant = false): void {
    const reduced = instant || this.reduced();
    while (this.revealed < Math.min(count, this.units.length)) {
      const unit = this.units[this.revealed];
      this.revealed += 1;
      for (const el of unit.elements) {
        this.hidden.get(el)?.cancel();
        this.hidden.delete(el);
        if (!reduced && canAnimate(el)) {
          el.animate([{ opacity: this.timing.fromOpacity }, { opacity: 1 }], {
            duration: this.timing.fadeMs,
            easing: "ease-out",
          });
        }
      }
      const lead = unit.elements[0];
      if (
        this.following &&
        lead instanceof HTMLElement &&
        typeof lead.scrollIntoView === "function" &&
        !isPinned(lead, document.body)
      ) {
        lead.scrollIntoView({ block: "nearest", inline: "nearest", behavior: reduced ? "auto" : "smooth" });
      }
    }
    if (!this.playing) this.host.dataset.phase = "thinking";
  }

  private local(el: Element): Box {
    const outer = this.host.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    return { x: box.left - outer.left, y: box.top - outer.top, w: box.width, h: box.height };
  }

  /** The written part of the batch, padded, inside the layer; null when none of it is in view. */
  private frameTarget(): Box | null {
    let box: Box | null = null;
    for (const unit of this.units.slice(0, this.revealed)) {
      for (const el of unit.elements) {
        if (!el.isConnected) continue;
        const b = this.local(el);
        if (b.w === 0 && b.h === 0) continue;
        box = box === null
          ? b
          : {
              x: Math.min(box.x, b.x),
              y: Math.min(box.y, b.y),
              w: Math.max(box.x + box.w, b.x + b.w) - Math.min(box.x, b.x),
              h: Math.max(box.y + box.h, b.y + b.h) - Math.min(box.y, b.y),
            };
      }
    }
    if (box === null) return null;
    const width = this.host.clientWidth;
    const height = this.host.clientHeight;
    const x0 = Math.max(1, box.x - FRAME_PAD);
    const y0 = Math.max(1, box.y - FRAME_PAD);
    const x1 = Math.min(width - 1, box.x + box.w + FRAME_PAD);
    const y1 = Math.min(height - 1, box.y + box.h + FRAME_PAD);
    if (x1 - x0 < 4 || y1 - y0 < 4) return null;
    return { x: x0, y: y0, w: x1 - x0, h: y1 - y0 };
  }

  /** Where the arrow points for `el`: the end of what was written, inside the layer. */
  private anchor(el: Element | null): { x: number; y: number } {
    if (!el || !el.isConnected) return HOME;
    const b = this.local(el);
    const tall = b.h > this.host.clientHeight * 0.6;
    const x = tall ? b.x + 24 : b.x + Math.max(8, b.w - 10);
    const y = tall ? b.y + 24 : b.y + Math.max(8, b.h - 6);
    return {
      x: Math.min(Math.max(x, 8), Math.max(8, this.host.clientWidth - 24)),
      y: Math.min(Math.max(y, 8), Math.max(8, this.host.clientHeight - 24)),
    };
  }

  private tick(now: number): void {
    if (!this.alive) return;
    const dt = this.last === 0 ? 16 : Math.min(64, now - this.last);
    this.last = now;
    const reduced = this.reduced();

    /* The frame grows toward what has been written, and follows it when the body scrolls. */
    const target = this.frameTarget();
    if (target === null) {
      this.frameBox = null;
    } else if (this.frameBox === null || reduced) {
      this.frameBox = target;
    } else {
      const k = 1 - Math.exp(-dt / 90);
      const f = this.frameBox;
      this.frameBox = {
        x: f.x + (target.x - f.x) * k,
        y: f.y + (target.y - f.y) * k,
        w: f.w + (target.w - f.w) * k,
        h: f.h + (target.h - f.h) * k,
      };
    }
    const frame = this.view.frame;
    if (this.frameBox === null) {
      frame.dataset.shown = "false";
    } else {
      const f = this.frameBox;
      frame.dataset.shown = "true";
      frame.style.transform = `translate3d(${f.x.toFixed(1)}px, ${f.y.toFixed(1)}px, 0)`;
      frame.style.width = `${f.w.toFixed(1)}px`;
      frame.style.height = `${f.h.toFixed(1)}px`;
    }

    /* The cursor glides to the last unit written; it rides along when the body scrolls. */
    const lastUnit = this.revealed > 0 ? this.units[this.revealed - 1] : null;
    const el = lastUnit ? lastUnit.elements[lastUnit.elements.length - 1] : null;
    const point = this.anchor(el);
    if (this.motion === null) this.motion = beginCursor(point.x, point.y, now);
    if (el !== this.aimed) {
      this.aimed = el;
      const distance = Math.hypot(point.x - this.motion.x, point.y - this.motion.y);
      this.motion = aimCursor(this.motion, { x: point.x, y: point.y, clickId: 0, clickX: 0, clickY: 0 }, distance, now, reduced).motion;
    } else if (Math.abs(point.x - this.motion.toX) > 0.5 || Math.abs(point.y - this.motion.toY) > 0.5) {
      // The same unit moved (a scroll, a reflow): the whole glide moves with it.
      const dx = point.x - this.motion.toX;
      const dy = point.y - this.motion.toY;
      const m = this.motion;
      this.motion = { ...m, x: m.x + dx, y: m.y + dy, fromX: m.fromX + dx, fromY: m.fromY + dy, ctrlX: m.ctrlX + dx, ctrlY: m.ctrlY + dy, toX: point.x, toY: point.y };
    }
    this.motion = stepCursor(this.motion, now).motion;
    const { x, y } = this.motion;
    this.view.cursor.style.transform = `translate3d(${x.toFixed(1)}px, ${y.toFixed(1)}px, 0)`;
    this.view.pill.style.transform = `translate3d(${(x + 18).toFixed(1)}px, ${(y + 22).toFixed(1)}px, 0)`;

    /* The name tag sits on the frame's top-left corner, or beside the cursor before there is one. */
    const tag = this.view.tag;
    if (this.frameBox !== null) {
      const f = this.frameBox;
      const above = f.y - tag.offsetHeight - 2;
      tag.style.transform = `translate3d(${f.x.toFixed(1)}px, ${(above >= 0 ? above : f.y + 4).toFixed(1)}px, 0)`;
      tag.dataset.on = "frame";
    } else {
      tag.style.transform = `translate3d(${(x + 18).toFixed(1)}px, ${(y + 2).toFixed(1)}px, 0)`;
      tag.dataset.on = "cursor";
    }
    this.loop = window.requestAnimationFrame((time) => this.tick(time));
  }
}
