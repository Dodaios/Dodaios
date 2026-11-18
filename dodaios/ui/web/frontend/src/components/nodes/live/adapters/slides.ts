/**
 * How a deck is revealed while an agent builds it.
 *
 * Built like a person builds a deck by hand:
 * - a new slide slides into the strip, and the stage is already on it (the
 *   editor moves the stage unless the person is working on another slide; in
 *   that case the slide's thumbnail plays the build instead);
 * - on the stage the background comes first, then the texts in reading order
 *   (each written in at a caret), then the free elements one by one; a
 *   picture shows its skeleton before it resolves;
 * - an element that was moved or resized glides to its new place, and slides
 *   put in another order glide in the strip. Those are already on screen, so
 *   they are visited by the frame and never hidden.
 *
 * The frame sits on the one part being written (`solo`). Motion is short
 * ease-out; the presence stays black and white.
 *
 * The slide canvas draws in a shadow root, so this adapter finds its targets
 * itself (`{ element }`) from the markers the slides editor sets:
 * `data-strip-item`, `data-strip-thumb` (strip) and `data-slide` on the
 * canvas host. docs/node-live-build.md.
 */
import type { Deck, Slide } from "../../editors/slides/deckModel";
import { diffDecks, elementBefore, elementChange, type SlideChange } from "../../editors/slides/deckDiff";
import type { SlideElement } from "../../editors/slides/elementModel";
import { prefersReducedMotion } from "../playback";
import type { RevealAdapter, RevealInput, RevealStep } from "../reveal";

/** A motion function of this adapter as the player's per-unit hook (it also runs with reduced motion). */
function reveal(motion: (elements: Element[], instant: boolean) => void): (el: Element) => void {
  return (el) => motion([el], prefersReducedMotion());
}

const EASE = "cubic-bezier(0.22, 0.61, 0.36, 1)";

function canAnimate(el: Element): el is Element & { animate: Element["animate"] } {
  return typeof (el as { animate?: unknown }).animate === "function";
}

/** A new slide's thumbnail slides into the strip. */
function slideIn(elements: Element[], instant: boolean): void {
  if (instant) return;
  for (const el of elements) {
    const item = el.closest("[data-strip-item]") ?? el;
    if (canAnimate(item)) item.animate([{ transform: "translateY(-10px)" }, { transform: "translateY(0)" }], { duration: 260, easing: EASE });
  }
}

/** A text is written in from the left, like a caret moving along; a longer text takes longer. */
function writeIn(elements: Element[], instant: boolean): void {
  if (instant) return;
  for (const el of elements) {
    if (!canAnimate(el)) continue;
    const length = (el.textContent ?? "").length;
    const duration = Math.min(700, 180 + length * 9);
    el.animate([{ clipPath: "inset(0 100% 0 0)" }, { clipPath: "inset(0 0 0 0)" }], { duration, easing: "steps(" + Math.max(6, Math.min(40, Math.round(length / 2))) + ", end)", fill: "backwards" });
  }
}

/** A picture shows a quiet skeleton that clears as the picture resolves. */
function skeletonThenPicture(elements: Element[], instant: boolean): void {
  if (instant) return;
  for (const el of elements) {
    if (!(el instanceof HTMLElement)) continue;
    const doc = el.ownerDocument;
    const cover = doc.createElement("div");
    cover.setAttribute("aria-hidden", "true");
    cover.style.cssText =
      "position:absolute;inset:0;pointer-events:none;border-radius:inherit;background:hsl(var(--presence-skeleton, 0 0% 50% / .08));";
    el.appendChild(cover);
    const done = () => cover.remove();
    if (!canAnimate(cover)) {
      window.setTimeout(done, 400);
      continue;
    }
    const sheen = cover.animate([{ opacity: 1 }, { opacity: 1, offset: 0.55 }, { opacity: 0 }], { duration: 640, easing: "ease-out", fill: "forwards" });
    sheen.onfinish = done;
    sheen.oncancel = done;
  }
}

/** An element that moved or resized glides from where it was. */
function glide(from: SlideElement | null, to: SlideElement): (elements: Element[], instant: boolean) => void {
  return (elements, instant) => {
    if (instant || !from || !("x" in from) || !("x" in to)) return;
    for (const el of elements) {
      if (!canAnimate(el)) continue;
      const frames: Keyframe[] = [{}, {}];
      const dx = from.x - to.x;
      const dy = from.y - to.y;
      if (dx !== 0 || dy !== 0) {
        frames[0].translate = `${dx}px ${dy}px`;
        frames[1].translate = "0px 0px";
      }
      if (from.w !== to.w || from.h !== to.h) {
        frames[0].width = `${from.w}px`;
        frames[1].width = `${to.w}px`;
        frames[0].height = `${from.h}px`;
        frames[1].height = `${to.h}px`;
      }
      if ((from.rotate ?? 0) !== (to.rotate ?? 0)) {
        frames[0].rotate = `${from.rotate ?? 0}deg`;
        frames[1].rotate = `${to.rotate ?? 0}deg`;
      }
      if (Object.keys(frames[0]).length > 0) el.animate(frames, { duration: 420, easing: EASE });
    }
  };
}

/** A thumbnail that took another place in the strip glides there. */
function stripGlide(fromIndex: number, toIndex: number): (elements: Element[], instant: boolean) => void {
  return (elements, instant) => {
    if (instant) return;
    for (const el of elements) {
      const item = el.closest("[data-strip-item]");
      const list = item?.parentElement?.parentElement;
      if (!item || !list || !canAnimate(item)) continue;
      const items = [...list.querySelectorAll("[data-strip-item]")];
      if (items.length < 2) continue;
      const pitch = items[1].getBoundingClientRect().top - items[0].getBoundingClientRect().top;
      const dy = (fromIndex - toIndex) * pitch;
      if (dy !== 0) item.animate([{ transform: `translateY(${dy}px)` }, { transform: "translateY(0)" }], { duration: 380, easing: EASE });
    }
  };
}

function stageOf(root: HTMLElement): { host: HTMLElement; shadow: ShadowRoot; index: number } | null {
  const host = root.querySelector<HTMLElement>('[data-testid="slides-canvas"]');
  const shadow = host?.shadowRoot;
  if (!host || !shadow) return null;
  const index = Number(host.dataset.slide);
  return { host, shadow, index: Number.isFinite(index) ? index : -1 };
}

function thumbOf(root: HTMLElement, index: number): Element | null {
  return root.querySelector(`[data-strip-thumb="${index}"]`);
}

/** The value of a slide at a field key such as `title`, `bullets/2` or `stats/0/value`. */
function valueAt(slide: Slide | null, key: string): unknown {
  let at: unknown = slide;
  for (const part of key.split("/")) {
    if (at === null || typeof at !== "object") return undefined;
    at = (at as Record<string, unknown>)[part];
  }
  return at;
}

const differs = (a: unknown, b: unknown): boolean => JSON.stringify(a ?? null) !== JSON.stringify(b ?? null);

/** Steps for the slide on the stage: background, texts in reading order, media, then the free elements. */
function stageSteps(change: SlideChange, shadow: ShadowRoot): RevealStep[] {
  const steps: RevealStep[] = [];
  const { slide, before } = change;
  const layoutChanged = before !== null && before.layout !== slide.layout;

  const background = shadow.querySelector(".sl-bg");
  if (background && (before === null || layoutChanged || differs(before.background, slide.background))) {
    steps.push({ target: { element: background }, solo: true });
  }

  for (const field of shadow.querySelectorAll("[data-field]")) {
    const key = field.getAttribute("data-field") ?? "";
    const now = valueAt(slide, key);
    if (typeof now !== "string" || now.trim() === "") continue;
    if (before !== null && !layoutChanged && !differs(valueAt(before, key), now)) continue;
    steps.push({ target: { element: field }, onReveal: reveal(writeIn), solo: true });
  }

  const media = (["chart", "table", "image"] as const).some((k) => differs(before?.[k], slide[k]));
  if (media) {
    const picture = shadow.querySelector(".sl-pic, .sl-plot, .sl-table");
    if (picture) steps.push({ target: { element: picture }, onReveal: reveal(skeletonThenPicture), solo: true });
  }

  (slide.elements ?? []).forEach((element, index) => {
    const how = before === null ? "added" : elementChange(before.elements, element, index);
    if (how === null) return;
    const box = shadow.querySelector(`[data-el="${index}"]`);
    if (!box) return;
    if (how === "added") {
      steps.push({ target: { element: box }, onReveal: element.type === "image" ? reveal(skeletonThenPicture) : element.type === "text" ? reveal(writeIn) : undefined, solo: true });
    } else {
      steps.push({
        target: { element: box },
        visible: true,
        solo: true,
        onReveal: how === "moved" ? reveal(glide(elementBefore(before?.elements, element, index), element)) : undefined,
      });
    }
  });
  return steps;
}

export function slideSteps(input: RevealInput<Deck>): RevealStep[] {
  const { previous, next, ops, initial, root } = input;
  const diff = diffDecks(initial ? null : previous, next, ops);
  const stage = stageOf(root);
  const steps: RevealStep[] = [];

  // Opened mid-build: the strip fills first, then the slide on the stage is written.
  const stageLater: SlideChange[] = [];
  for (const change of diff.changes) {
    const thumb = thumbOf(root, change.index);
    if (change.kind === "moved") {
      if (thumb) steps.push({ target: { element: thumb }, visible: true, solo: true, onReveal: reveal(stripGlide(change.from ?? change.index, change.index)) });
      continue;
    }
    const onStage = stage !== null && stage.index === change.index;
    // The strip shows every new slide arriving; the thumbnail alone plays a slide the person is not on.
    if (thumb && (change.kind === "added" || !onStage)) {
      steps.push({ target: { element: thumb }, solo: true, visible: change.kind === "edited", onReveal: change.kind === "added" && !initial ? reveal(slideIn) : undefined });
    }
    if (onStage && stage) {
      if (initial) stageLater.push(change);
      else steps.push(...stageSteps(change, stage.shadow));
    }
  }
  for (const change of stageLater) if (stage) steps.push(...stageSteps(change, stage.shadow));
  return steps;
}

export const slidesReveal = { steps: slideSteps } as unknown as RevealAdapter;
