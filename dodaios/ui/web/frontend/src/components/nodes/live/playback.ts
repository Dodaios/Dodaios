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
 *
 * The cursor moves the way a person's does in a shared document: it sets off
 * at once and settles softly (an exponential ease-out, re-aimed every frame),
 * so it keeps up with a caret that moves every few milliseconds instead of
 * restarting a slow glide each time. The arrow leans with its speed, a ring
 * opens where it lands after a longer move, and it gives a small shake when
 * the agent starts to think.
 */
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

/**
 * A unit's own way of arriving, for a type whose content is not best shown by
 * a plain fade (text written at a caret, a picture's skeleton). The player
 * calls it in this order: `prepare` when the batch is queued (hide what is to
 * come, draw what stands in its place), `start` when the unit's turn comes,
 * `advance(1..steps)` while it runs, `finish` when it is over or interrupted
 * (everything shown, anything drawn for it removed). `finish` is safe to call
 * at any time, even without `prepare` (reduced motion). Nothing here may
 * change the editor's own DOM or styles (see `writing.ts`).
 */
export interface UnitMotion {
  /** How long the unit takes at natural speed; long batches are compressed. */
  durationMs: number;
  /** How many times `advance` is called while the unit runs. */
  steps: number;
  prepare(host: HTMLElement): void;
  start(): void;
  advance(step: number): void;
  finish(): void;
  /** Called every frame while the unit is prepared; `host` is the presence layer's box. */
  update?(host: DOMRect): void;
  /** Where the agent is writing now, in viewport pixels; null when it is not at a point. */
  caret?(): { x: number; y: number; h: number; within: Element } | null;
}

/** One step of a batch: the elements that fade in together, and its status. */
export interface RevealUnit {
  elements: Element[];
  label?: string;
  /** Replaces the plain fade for these elements. */
  motion?: UnitMotion;
  /** Extra motion as the unit is revealed (`RevealStep.enter`). */
  enter?: (el: Element) => Keyframe[] | null;
  /** Called with the unit's first element as it is revealed (`RevealStep.onReveal`). */
  onReveal?: (el: Element) => void;
  /** False: the frame does not grow to this unit (see `RevealStep.framed`). */
  framed?: boolean;
  /** Already on screen: not hidden or faded, only visited. */
  visible?: boolean;
  /** The frame sits on this unit alone. */
  solo?: boolean;
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
  let run: RevealUnit[] = [];
  const flush = () => {
    for (let i = 0; i < run.length; i += size) {
      const part = run.slice(i, i + size);
      const reveals = part.flatMap((u) => (u.onReveal ? [u.onReveal] : []));
      out.push({
        elements: part.flatMap((u) => u.elements),
        label: part.find((u) => u.label)?.label,
        framed: part.some((u) => u.framed !== false),
        visible: part.every((u) => u.visible) || undefined,
        solo: part.some((u) => u.solo) || undefined,
        onReveal: reveals.length > 0 ? (el) => reveals.forEach((reveal) => reveal(el)) : undefined,
      });
    }
    run = [];
  };
  for (const unit of units) {
    // A unit with its own motion is never merged: its motion would be lost.
    if (unit.motion) {
      flush();
      out.push(unit);
    } else run.push(unit);
  }
  flush();
  return out;
}

/**
 * When each unit of a batch starts and how long it runs, in ms from the
 * batch's start. Plain units are `staggerMs` apart (compressed, see
 * `revealDelays`); a unit with its own motion takes its `durationMs`. If the
 * whole would pass `maxBatchMs`, every start and length is scaled down.
 */
export function schedule(units: readonly RevealUnit[], timing = LIVE_TIMING): { starts: number[]; lengths: number[] } {
  if (!units.some((u) => u.motion)) {
    const starts = revealDelays(units.length, timing);
    return { starts, lengths: units.map(() => timing.staggerMs) };
  }
  const weights = units.map((u) => u.motion?.durationMs ?? timing.staggerMs);
  const before = weights.slice(0, -1).reduce((a, b) => a + b, 0);
  const room = Math.max(0, timing.maxBatchMs - timing.fadeMs);
  const scale = Math.min(1, room / Math.max(1, before + (weights[weights.length - 1] ?? 0)));
  let at = 0;
  const starts: number[] = [];
  for (const w of weights) {
    starts.push(Math.round(at * scale));
    at += w;
  }
  return { starts, lengths: weights.map((w) => Math.floor(w * scale)) };
}

/** Room kept clear at the foot of the view for a floating bar, and at its top. */
const VIEW_FOOT = 104;
const VIEW_HEAD = 24;

/**
 * Scroll `scroller` the least that brings `rect` (viewport pixels) into its
 * free area. Only a tall scroller (an editor's body) keeps room for the
 * floating bar at its foot; a short one (a timeline, a cell) keeps none.
 */
function bringIntoView(scroller: Element, rect: DOMRect, instant: boolean): void {
  const box = scroller.getBoundingClientRect();
  const roomy = box.height > 3 * (VIEW_FOOT + VIEW_HEAD);
  const bottom = box.bottom - (roomy ? VIEW_FOOT : 0);
  const top = box.top + (roomy ? VIEW_HEAD : 0);
  let delta = 0;
  if (rect.height > bottom - top || rect.top < top) delta = rect.top - top;
  else if (rect.bottom > bottom) delta = rect.bottom - bottom;
  if (Math.abs(delta) < 2) return;
  scroller.scrollBy({ top: delta, behavior: instant ? "auto" : "smooth" });
}

/** The nearest ancestor that scrolls, or null. */
function scrollParent(el: Element | null): Element | null {
  for (let at = el; at; at = at.parentElement) {
    if (typeof window.getComputedStyle !== "function") return null;
    const overflow = window.getComputedStyle(at).overflowY;
    if ((overflow === "auto" || overflow === "scroll") && at.scrollHeight > at.clientHeight) return at;
  }
  return null;
}

/** Whether `el` is inside `root`, looking through the shadow roots that hold it (a slide's canvas). */
function within(root: Element, el: Element): boolean {
  let at: Node | null = el;
  while (at) {
    if (root.contains(at)) return true;
    const top: Node = at.getRootNode();
    at = top instanceof ShadowRoot ? top.host : null;
  }
  return false;
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
    const unit = (elements: Element[]): RevealUnit => ({
      elements,
      label: step.label,
      framed: step.framed,
      enter: step.enter,
      onReveal: step.onReveal,
      motion: step.motion,
      visible: step.visible,
      solo: step.solo,
    });
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
      elements = within(root, target.element) ? [target.element] : [];
    } else if ("changed" in target) {
      for (const el of changed) units.push(unit([el]));
      continue;
    } else {
      for (const el of topBlocks(root)) units.push(unit([el]));
      continue;
    }
    if (elements.length > 0) units.push(unit(elements));
  }
  return grouped(units);
}

/* --- the player ----------------------------------------------------------- */

export interface PresenceElements {
  cursor: HTMLElement;
  frame: HTMLElement;
  /** The name tag, carried by the cursor; the player only turns it to the side with room. */
  tag: HTMLElement;
  /** The arrow's own box inside the cursor: it leans as the cursor travels. */
  arrow?: HTMLElement;
  /** Wraps the arrow: it shakes once when the agent starts to think. */
  art?: HTMLElement;
  /** Opens where the cursor lands after a longer move. */
  ring?: HTMLElement;
}

interface Box {
  x: number;
  y: number;
  w: number;
  h: number;
}

interface Point {
  x: number;
  y: number;
}

const FRAME_PAD = 6;
const PENDING_KEYFRAMES: Keyframe[] = [{ opacity: 0 }, { opacity: 0 }];
const HOLD_MS = 600_000;
/** How long the cursor takes to cover most of the way to the caret (ms; ease-out time constant). */
const CARET_EASE_MS = 35;
/** The same for a move from one written block to the next. */
const HOP_EASE_MS = 110;
/** The frame's ease toward what has been written. */
const FRAME_EASE_MS = 90;
/** Quiet this long after a batch before the tag says the agent is working: no flash between quick batches. */
export const THINKING_AFTER_MS = 600;
/** Room the tag keeps from the layer's edges before it turns to the other side. */
const TAG_EDGE = 6;
/** The most the arrow leans as it travels (degrees). */
const LEAN_MAX_DEG = 10;
/** The speed (px per ms) at which the arrow leans about three quarters of the most. */
const LEAN_AT_PX_PER_MS = 1.6;
/** How quickly the lean follows the speed (ms; ease-out time constant). */
const LEAN_EASE_MS = 80;
/** A move at least this long ends with a ring where the cursor lands. */
const RING_AFTER_PX = 48;
const RING_KEYFRAMES: Keyframe[] = [
  { opacity: 0.95, transform: "scale(0.25)" },
  { opacity: 0, transform: "scale(1)" },
];
/** The small shake when the agent starts to think: a few swings about the tip, dying down. */
const SHAKE_KEYFRAMES: Keyframe[] = [
  { transform: "rotate(0deg)" },
  { transform: "rotate(9deg)", offset: 0.18 },
  { transform: "rotate(-7deg)", offset: 0.4 },
  { transform: "rotate(4deg)", offset: 0.62 },
  { transform: "rotate(-2deg)", offset: 0.82 },
  { transform: "rotate(0deg)" },
];

function canAnimate(el: Element): el is Element & { animate: Element["animate"] } {
  return typeof (el as { animate?: unknown }).animate === "function";
}

export function prefersReducedMotion(): boolean {
  return typeof window.matchMedia === "function" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
}

function overlaps(a: Box, b: Box): boolean {
  return a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
}

/** Text that is not the content itself: an editor's own controls, a chart's axis labels. */
const NOT_CONTENT = "button, [role='button'], select, svg, [aria-hidden='true']";

/**
 * The end of the last line of written text in `el`, in viewport pixels; null
 * when it holds no laid-out text of its own (a picture, a chart, an input, a
 * marker). An editor's controls inside it ("Add row") are not its text.
 */
export function textEnd(el: Element): { x: number; y: number; h: number } | null {
  if (typeof document.createRange !== "function" || typeof document.createTreeWalker !== "function") return null;
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT);
  const texts: Text[] = [];
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    if ((node as Text).data.trim() === "") continue;
    const control = node.parentElement?.closest(NOT_CONTENT) ?? null;
    if (control && control !== el && el.contains(control)) continue;
    texts.push(node as Text);
  }
  // From the last one back: a hidden label (a screen-reader text) has no box to rest on.
  for (let i = texts.length - 1; i >= 0 && i >= texts.length - 12; i -= 1) {
    const text = texts[i];
    let end = text.data.length;
    while (end > 0 && /\s/.test(text.data[end - 1] ?? "")) end -= 1;
    const range = document.createRange();
    try {
      range.setStart(text, Math.max(0, end - 1));
      range.setEnd(text, end);
    } catch {
      continue;
    }
    if (typeof range.getClientRects !== "function") return null;
    const rects = range.getClientRects();
    const rect = rects.length > 0 ? rects[rects.length - 1] : null;
    if (rect && (rect.width > 0 || rect.height > 0)) return { x: rect.right, y: rect.top, h: rect.height };
  }
  return null;
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
  /** Units with their own motion that are prepared and not yet over. */
  private moving = new Set<UnitMotion>();
  private frameBox: Box | null = null;
  /** Where the cursor's tip is, and where it heads, inside the layer. */
  private at: Point | null = null;
  private goal: Point | null = null;
  /** The element the cursor was last sent to, to tell a scroll (it rides along) from a new aim. */
  private aimed: Element | null = null;
  /** The arrow's lean now, and as last written (degrees). */
  private lean = 0;
  private leanShown = 0;
  /** A longer move is under way: a ring opens where it lands. */
  private ringDue = false;
  private thinkTimer = 0;
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
    this.host.dataset.placed = "false";
    this.loop = window.requestAnimationFrame((now) => this.tick(now));
  }

  /** A batch is playing: units still to reveal, or text still being written. */
  get playing(): boolean {
    return this.revealed < this.units.length || this.moving.size > 0;
  }

  /** Play `units`, finishing the batch before at once. */
  play(units: RevealUnit[]): void {
    this.finish();
    this.units = [];
    this.revealed = 0;
    this.frameBox = null;
    // The last batch's frame goes at once, not one tick later.
    this.view.frame.dataset.shown = "false";
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
    this.writing();
    if (this.reduced()) {
      this.revealUpTo(this.units.length);
      return;
    }
    const added = this.units.slice(start);
    for (const unit of added) {
      if (unit.motion) {
        unit.motion.prepare(this.host);
        this.moving.add(unit.motion);
      } else if (!unit.visible) for (const el of unit.elements) this.hide(el);
    }
    // Late units queue behind the ones already scheduled, never ahead of them.
    const now = performance.now();
    const base = start > 0 ? Math.max(0, this.slotAt + this.timing.staggerMs - now) : 0;
    const { starts, lengths } = schedule(added, this.timing);
    starts.forEach((delay, i) => {
      this.timers.push(window.setTimeout(() => this.revealUpTo(start + i + 1), base + delay));
      const motion = added[i].motion;
      if (!motion) return;
      for (let k = 1; k <= motion.steps; k += 1) {
        const at = base + delay + (lengths[i] * k) / motion.steps;
        this.timers.push(window.setTimeout(() => this.stepMotion(motion, k), at));
      }
    });
    this.slotAt = now + base + (starts[starts.length - 1] ?? 0);
  }

  /** One sub-step of a unit's own motion; its last one ends the unit. */
  private stepMotion(motion: UnitMotion, step: number): void {
    if (!this.moving.has(motion)) return;
    motion.advance(step);
    if (step >= motion.steps) {
      motion.finish();
      this.moving.delete(motion);
    }
    this.followCaret(motion);
    this.settle();
  }

  /** The view keeps the writing in sight (until the person scrolled or worked). */
  private followCaret(motion: UnitMotion): void {
    const caret = this.following ? motion.caret?.() : null;
    if (!caret) return;
    const scroller = scrollParent(caret.within);
    if (scroller) bringIntoView(scroller, new DOMRect(caret.x, caret.y, 1, caret.h), this.reduced());
  }

  /** Reveal everything of the batch now. */
  finish(): void {
    for (const timer of this.timers) window.clearTimeout(timer);
    this.timers = [];
    this.revealUpTo(this.units.length, true);
    for (const motion of this.moving) motion.finish();
    this.moving.clear();
    this.settle();
  }

  /** The person acted in the node: the batch shows at once and the view stays where they put it. */
  interrupt(): void {
    this.following = false;
    this.finish();
  }

  destroy(): void {
    this.alive = false;
    this.finish();
    window.clearTimeout(this.thinkTimer);
    for (const animation of this.hidden.values()) animation.cancel();
    this.hidden.clear();
    window.cancelAnimationFrame(this.loop);
    this.host.dataset.placed = "false";
  }

  /** The agent is writing: the tag shows its name. */
  private writing(): void {
    window.clearTimeout(this.thinkTimer);
    this.thinkTimer = 0;
    this.host.dataset.phase = "writing";
  }

  /** The batch is over: after a quiet moment the tag says the agent is working on. */
  private settle(): void {
    if (this.playing || this.host.dataset.phase === "thinking" || this.thinkTimer !== 0) return;
    this.thinkTimer = window.setTimeout(() => {
      this.thinkTimer = 0;
      if (this.playing) return;
      this.host.dataset.phase = "thinking";
      this.shake();
    }, this.reduced() ? 0 : THINKING_AFTER_MS);
  }

  /** The arrow's small shake as the agent starts to think (not with reduced motion, not once the agent is done). */
  private shake(): void {
    const art = this.view.art;
    if (!art || this.reduced() || !canAnimate(art)) return;
    if (this.host.dataset.placed !== "true" || this.host.dataset.building === "false") return;
    art.animate(SHAKE_KEYFRAMES, { duration: 1_100, easing: "ease-in-out" });
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
      if (unit.motion) {
        // Its own arrival: started on its turn, or shown at once.
        if (reduced) {
          unit.motion.finish();
          this.moving.delete(unit.motion);
        } else unit.motion.start();
      }
      for (const el of unit.motion ? [] : unit.elements) {
        this.hidden.get(el)?.cancel();
        this.hidden.delete(el);
        if (!reduced && !unit.visible && canAnimate(el)) {
          el.animate([{ opacity: this.timing.fromOpacity }, { opacity: 1 }], {
            duration: this.timing.fadeMs,
            easing: "ease-out",
          });
          const extra = unit.enter?.(el);
          if (extra && extra.length > 0) el.animate(extra, { duration: this.timing.fadeMs, easing: "ease-out" });
        }
      }
      const first = unit.elements[0];
      if (unit.onReveal && first?.isConnected) {
        try {
          unit.onReveal(first);
        } catch {
          // A type's hook must never stop the batch.
        }
      }
      const lead = unit.elements[0];
      if (
        this.following &&
        lead instanceof HTMLElement &&
        typeof lead.scrollIntoView === "function" &&
        !isPinned(lead, this.host.parentElement ?? document.body)
      ) {
        const scroller = scrollParent(lead);
        if (scroller) bringIntoView(scroller, lead.getBoundingClientRect(), reduced);
        else lead.scrollIntoView({ block: "nearest", inline: "nearest", behavior: reduced ? "auto" : "smooth" });
      }
    }
    this.settle();
  }

  /** The nearest scrolling ancestor of an element inside the host's parent: what clips the written part. */
  private clipper = new WeakMap<Element, Element | null>();

  private clipOf(el: Element): Element | null {
    if (this.clipper.has(el)) return this.clipper.get(el) ?? null;
    let found: Element | null = null;
    const stop = this.host.parentElement;
    for (let at = el.parentElement; at && at !== stop; at = at.parentElement) {
      if (typeof window.getComputedStyle !== "function") break;
      const overflow = window.getComputedStyle(at).overflow;
      if (/(auto|scroll|hidden)/.test(overflow)) {
        found = at;
        break;
      }
    }
    this.clipper.set(el, found);
    return found;
  }

  /** The element's box inside the layer, cut to the scrolling area it sits in; w and h are 0 when it is scrolled out of view. */
  private local(el: Element, clipped = true): Box {
    const outer = this.host.getBoundingClientRect();
    const box = el.getBoundingClientRect();
    let left = box.left;
    let top = box.top;
    let right = box.right;
    let bottom = box.bottom;
    const clip = clipped ? this.clipOf(el) : null;
    if (clip) {
      const view = clip.getBoundingClientRect();
      left = Math.max(left, view.left);
      top = Math.max(top, view.top);
      right = Math.min(right, view.right);
      bottom = Math.min(bottom, view.bottom);
      if (right <= left || bottom <= top) return { x: 0, y: 0, w: 0, h: 0 };
    }
    return { x: left - outer.left, y: top - outer.top, w: right - left, h: bottom - top };
  }

  /** The written part of the batch, padded, inside the layer; null when none of it is in view. */
  private frameTarget(): Box | null {
    let box: Box | null = null;
    const written = this.units.slice(0, this.revealed);
    const last = written[written.length - 1];
    for (const unit of last?.solo ? [last] : written) {
      if (unit.framed === false) continue;
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

  /** Where the arrow's tip goes for a text point in viewport pixels: just after it, low on its line. */
  private textPoint(point: { x: number; y: number; h: number }): Point {
    const outer = this.host.getBoundingClientRect();
    return this.clampPoint({ x: point.x - outer.left + 2, y: point.y - outer.top + point.h * 0.8 });
  }

  private clampPoint(point: Point): Point {
    return {
      x: Math.min(Math.max(point.x, 8), Math.max(8, this.host.clientWidth - 16)),
      y: Math.min(Math.max(point.y, 8), Math.max(8, this.host.clientHeight - 16)),
    };
  }

  /**
   * Where the arrow points for a written element: the end of its last line of
   * text, where a writer's hand would rest; for a picture, a chart or a
   * shape, its lower right corner.
   */
  private anchor(el: Element): Point | null {
    if (!el.isConnected) return null;
    const end = textEnd(el);
    if (end) return this.textPoint(end);
    const b = this.local(el, false);
    if (b.w === 0 && b.h === 0) return null;
    return this.clampPoint({ x: b.x + Math.max(8, b.w - 12), y: b.y + Math.max(8, b.h - 8) });
  }

  private tick(now: number): void {
    if (!this.alive) return;
    const dt = this.last === 0 ? 16 : Math.min(64, now - this.last);
    this.last = now;
    const reduced = this.reduced();

    /* The frame grows toward what has been written, and follows it when the body scrolls.
       A jump to a place apart from it (the next slide, a new column) is not a flight across
       the editor: the frame lands there and fades in. */
    const target = this.frameTarget();
    const frame = this.view.frame;
    if (target === null) {
      this.frameBox = null;
    } else if (this.frameBox === null || reduced) {
      this.frameBox = target;
    } else if (!overlaps(this.frameBox, target)) {
      this.frameBox = target;
      if (canAnimate(frame)) frame.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 180, easing: "ease-out" });
    } else {
      const k = 1 - Math.exp(-dt / FRAME_EASE_MS);
      const f = this.frameBox;
      this.frameBox = {
        x: f.x + (target.x - f.x) * k,
        y: f.y + (target.y - f.y) * k,
        w: f.w + (target.w - f.w) * k,
        h: f.h + (target.h - f.h) * k,
      };
    }
    if (this.frameBox === null) {
      frame.dataset.shown = "false";
    } else {
      const f = this.frameBox;
      frame.dataset.shown = "true";
      frame.style.transform = `translate3d(${f.x.toFixed(1)}px, ${f.y.toFixed(1)}px, 0)`;
      frame.style.width = `${f.w.toFixed(1)}px`;
      frame.style.height = `${f.h.toFixed(1)}px`;
    }

    /* The cursor: at the caret while text is being written, else at the end of the last unit written. */
    if (this.moving.size > 0) {
      const outer = this.host.getBoundingClientRect();
      for (const own of this.moving) own.update?.(outer);
    }
    const lastUnit = this.revealed > 0 ? this.units[this.revealed - 1] : null;
    const el = lastUnit ? lastUnit.elements[lastUnit.elements.length - 1] : null;
    const caret = lastUnit?.motion && this.moving.has(lastUnit.motion) ? (lastUnit.motion.caret?.() ?? null) : null;
    const point = caret ? this.textPoint(caret) : el ? this.anchor(el) : null;
    if (point) {
      const before = this.at ? { ...this.at } : null;
      let ride = { x: 0, y: 0 };
      if (this.at === null || this.goal === null || reduced) {
        this.at = { ...point };
      } else if (!caret && el === this.aimed) {
        // The same element moved (a scroll, a reflow): the cursor rides along instead of trailing it.
        ride = { x: point.x - this.goal.x, y: point.y - this.goal.y };
        this.at = { x: this.at.x + ride.x, y: this.at.y + ride.y };
      } else if (!caret && el !== this.aimed && Math.hypot(point.x - this.at.x, point.y - this.at.y) >= RING_AFTER_PX) {
        this.ringDue = true;
      }
      if (caret) this.ringDue = false;
      this.goal = point;
      this.aimed = caret ? null : el;
      const k = 1 - Math.exp(-dt / (caret ? CARET_EASE_MS : HOP_EASE_MS));
      this.at = { x: this.at.x + (point.x - this.at.x) * k, y: this.at.y + (point.y - this.at.y) * k };

      /* The arrow leans with its speed, as a hand tilts a mouse it moves; riding along a scroll is no move. */
      const arrow = this.view.arrow;
      if (arrow) {
        let target = 0;
        if (before && !reduced) {
          const vx = (this.at.x - before.x - ride.x) / dt;
          const vy = (this.at.y - before.y - ride.y) / dt;
          target = LEAN_MAX_DEG * Math.tanh(((vx - vy) * Math.SQRT1_2) / LEAN_AT_PX_PER_MS);
        }
        this.lean = reduced ? 0 : this.lean + (target - this.lean) * (1 - Math.exp(-dt / LEAN_EASE_MS));
        if (Math.abs(this.lean - this.leanShown) > 0.05) {
          this.leanShown = this.lean;
          arrow.style.transform = Math.abs(this.lean) < 0.05 ? "" : `rotate(${this.lean.toFixed(2)}deg)`;
        }
      }

      /* Landed after a longer move: a ring opens where it stands. */
      if (this.ringDue && Math.hypot(point.x - this.at.x, point.y - this.at.y) < 2) {
        this.ringDue = false;
        const ring = this.view.ring;
        if (ring && !reduced && canAnimate(ring)) ring.animate(RING_KEYFRAMES, { duration: 600, easing: "ease-out" });
      }
      this.view.cursor.style.transform = `translate3d(${this.at.x.toFixed(1)}px, ${this.at.y.toFixed(1)}px, 0)`;
      if (this.host.dataset.placed !== "true") this.host.dataset.placed = "true";

      /* The tag rides beside the arrow, on whichever side has room. */
      const tag = this.view.tag;
      const side = this.at.x + 12 + tag.offsetWidth > this.host.clientWidth - TAG_EDGE ? "left" : "right";
      const vside = this.at.y + 14 + tag.offsetHeight > this.host.clientHeight - TAG_EDGE ? "up" : "down";
      if (tag.dataset.side !== side) tag.dataset.side = side;
      if (tag.dataset.vside !== vside) tag.dataset.vside = vside;
    }
    this.loop = window.requestAnimationFrame((time) => this.tick(time));
  }
}
