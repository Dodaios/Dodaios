import { useCallback, useEffect, useRef, useState } from "react";

/**
 * "Follow the newest, unless the reader is reading" — the scrolling rule every
 * conversation surface owes its reader.
 *
 * The wrong version is one line and looks right: scroll to the end whenever
 * anything arrives. It reads fine while you watch an answer come in and is
 * unusable the moment you want to look back — a streaming answer fires an
 * update per token, so each attempt to scroll up is undone before the next
 * frame. The rule instead: new output pulls the view along ONLY while the view
 * is already at the end. Scrolled up, the reader keeps their place, and
 * `atEnd` turns false so the surface can offer a way back.
 *
 * Use it for anything that GROWS while being read — chat threads, transcripts,
 * live logs. A view that only ever lands at its end once (a stored thread
 * opened for reading) does not need this; a plain scroll on load says that
 * more honestly.
 *
 *   const { rootRef, contentRef, atEnd, jumpToEnd } = useStickToBottom();
 *   <ScrollArea ref={rootRef}><div ref={contentRef}>…</div></ScrollArea>
 *   {!atEnd && <button onClick={jumpToEnd}>…</button>}
 *
 * Two ways lead back to the end. `snapToEnd` is for the person's own act (a
 * message sent): the view is at the end at once, with no glide. `jumpToEnd` is
 * the button's: it glides there. The glide is the delicate one. WebKit, the
 * engine of the macOS desktop app, DROPS a plain `scrollTop` write made from a
 * task while a smooth scroll runs, and stops the glide where it stands (seen
 * 2026-11-12: a view that stayed put under a sent message). So nothing writes
 * `scrollTop` from a task during a glide; the end of the glide is found frame
 * by frame, and every write that repairs something is made inside a frame,
 * where WebKit takes it. After each pin the next frames also check that the
 * view really arrived, and pin again if it did not.
 *
 * `rootRef` goes on the scrolling element or on a Radix ScrollArea root —
 * either is resolved. `contentRef` goes on the growing child, which is what
 * makes an answer that grows without a new item still pull the view along;
 * where the platform has no ResizeObserver, call `follow()` from an effect of
 * your own instead.
 */
export function useStickToBottom() {
  // A ref AND a state for the same node on purpose: `follow` must read the
  // current element synchronously inside a layout effect, while the listeners
  // below have to re-attach when the element appears or is replaced — which
  // only a state dependency can trigger.
  const rootElRef = useRef<HTMLElement | null>(null);
  const [rootEl, setRootEl] = useState<HTMLElement | null>(null);
  const contentElRef = useRef<HTMLElement | null>(null);
  const [contentEl, setContentEl] = useState<HTMLElement | null>(null);
  const stickRef = useRef(true);
  const [atEnd, setAtEnd] = useState(true);
  // Layout growth (a live thought, a tool row) is taller than NEAR_END_PX in
  // one frame. Overflow anchoring then fires `scroll` with the OLD top —
  // before any resize observer can pin — and `isNearEnd` would lie that the
  // reader moved away. Remembering the last size lets that event re-pin
  // instead of unsticking; a real scroll-up still unsticks.
  const lastHeightRef = useRef(0);
  const lastTopRef = useRef(0);
  // Smooth "jump to end" emits many `scroll` events that are not near the
  // end yet. Those must not clear the stick, or the next reasoning token
  // leaves the reader stranded mid-animation. While a glide runs this holds
  // where it was last seen and for how many frames it has stood still.
  const glideRef = useRef<{ startedAt: number; lastTop: number; still: number } | null>(null);
  const glideTimerRef = useRef(0);
  // The frames after a pin in which the view is checked (see `settle`).
  const settleFrameRef = useRef(0);
  const settleLeftRef = useRef(0);
  // When the reader last moved the view by hand. A view that is away from
  // the end right after a wheel turn is the reader's choice, not a lost pin.
  const handAtRef = useRef(Number.NEGATIVE_INFINITY);

  const rootRef = useCallback((node: HTMLElement | null) => {
    rootElRef.current = node;
    setRootEl(node);
  }, []);
  const contentRef = useCallback((node: HTMLElement | null) => {
    contentElRef.current = node;
    setContentEl(node);
  }, []);

  const pinToEnd = (viewport: HTMLElement) => {
    viewport.scrollTop = viewport.scrollHeight;
    lastHeightRef.current = viewport.scrollHeight;
    lastTopRef.current = viewport.scrollTop;
  };

  const endGlide = () => {
    glideRef.current = null;
    window.clearTimeout(glideTimerRef.current);
  };

  /**
   * Check on the next frames that the view is where the hook put it.
   *
   * A pin is a plain `scrollTop` write, and the engine may not take it (see
   * the note on WebKit above). Inside a frame it does, so for a few frames
   * after every pin the view is compared with its end and pinned again when
   * it fell short. The same frames watch a glide: it is over once the view
   * is near the end, stands still, or has taken too long, and the rest of
   * the way is then a pin.
   */
  const settle = useCallback(() => {
    settleLeftRef.current = SETTLE_FRAMES;
    if (settleFrameRef.current || typeof requestAnimationFrame !== "function") return;
    const tick = () => {
      settleFrameRef.current = 0;
      const viewport = scrollViewportOf(rootElRef.current);
      if (!viewport || !stickRef.current) return;
      const glide = glideRef.current;
      if (glide) {
        const top = viewport.scrollTop;
        glide.still = Math.abs(top - glide.lastTop) < 1 ? glide.still + 1 : 0;
        glide.lastTop = top;
        const over = isNearEnd(top, viewport.scrollHeight, viewport.clientHeight)
          || glide.still >= GLIDE_STILL_FRAMES
          || nowMs() - glide.startedAt > GLIDE_MAX_MS;
        if (!over) {
          settleFrameRef.current = requestAnimationFrame(tick);
          return;
        }
        endGlide();
        pinToEnd(viewport);
        setAtEnd(true);
        settleLeftRef.current = SETTLE_FRAMES;
      } else if (nowMs() - handAtRef.current < HAND_MS) {
        // The reader is moving the view: where it stands is theirs.
        return;
      } else if (!isAtEnd(viewport)) {
        pinToEnd(viewport);
        setAtEnd(true);
      }
      settleLeftRef.current -= 1;
      if (settleLeftRef.current > 0) settleFrameRef.current = requestAnimationFrame(tick);
    };
    settleFrameRef.current = requestAnimationFrame(tick);
  }, []);

  /** Pull the view to the end — but only if it was already there. */
  const follow = useCallback(() => {
    const viewport = scrollViewportOf(rootElRef.current);
    if (!viewport || !stickRef.current) return;
    // A glide is on its way to the end; a write now would stop it short.
    if (!glideRef.current) pinToEnd(viewport);
    settle();
  }, [settle]);

  /** The person acted (sent a message): the view is at the end, now, and follows from there. */
  const snapToEnd = useCallback(() => {
    const viewport = scrollViewportOf(rootElRef.current);
    if (!viewport) return;
    endGlide();
    stickRef.current = true;
    setAtEnd(true);
    pinToEnd(viewport);
    settle();
  }, [settle]);

  /** Take the reader back to the end, and follow again from there. */
  const jumpToEnd = useCallback(() => {
    const viewport = scrollViewportOf(rootElRef.current);
    if (!viewport) return;
    stickRef.current = true;
    setAtEnd(true);
    if (!prefersReducedMotion() && typeof viewport.scrollTo === "function") {
      glideRef.current = { startedAt: nowMs(), lastTop: viewport.scrollTop, still: 0 };
      viewport.scrollTo({ top: viewport.scrollHeight, behavior: "smooth" });
      // Frames do not run in a window nobody sees, and neither does the
      // glide: the timer ends it there.
      window.clearTimeout(glideTimerRef.current);
      glideTimerRef.current = window.setTimeout(() => {
        if (!glideRef.current) return;
        endGlide();
        pinToEnd(viewport);
        setAtEnd(true);
        settle();
      }, GLIDE_MAX_MS + 200);
      settle();
    } else {
      pinToEnd(viewport);
      settle();
    }
  }, [settle]);

  // One listener answers both questions: does new output pull the view along,
  // and does the surface need to offer a way back.
  useEffect(() => {
    const viewport = scrollViewportOf(rootEl);
    if (!viewport) return;
    const previousAnchor = viewport.style.overflowAnchor;
    viewport.style.overflowAnchor = "none";
    const read = () => {
      if (glideRef.current) {
        stickRef.current = true;
        if (isNearEnd(viewport.scrollTop, viewport.scrollHeight, viewport.clientHeight)) {
          endGlide();
          pinToEnd(viewport);
          setAtEnd(true);
          settle();
        }
        return;
      }
      const height = viewport.scrollHeight;
      const top = viewport.scrollTop;
      // A first observation (height still 0) is not growth — jsdom and a
      // just-mounted pane both start there. Treating it as growth would pin
      // a reader who opened the thread mid-way.
      const hadLayout = lastHeightRef.current > 0;
      const grew = hadLayout && height > lastHeightRef.current;
      const scrolledUp = hadLayout && top + 1 < lastTopRef.current;
      // Content grew while we were following, and the reader did not scroll
      // up: this `scroll` is layout, not a choice. Stay stuck and pin.
      if (stickRef.current && grew && !scrolledUp) {
        pinToEnd(viewport);
        setAtEnd(true);
        return;
      }
      lastHeightRef.current = height;
      lastTopRef.current = top;
      const near = isNearEnd(top, height, viewport.clientHeight);
      stickRef.current = near;
      setAtEnd(near);
    };
    read();
    viewport.addEventListener("scroll", read, { passive: true });
    const onScrollEnd = () => {
      if (!glideRef.current) return;
      endGlide();
      if (stickRef.current) pinToEnd(viewport);
      setAtEnd(true);
      settle();
    };
    viewport.addEventListener("scrollend", onScrollEnd);
    // The reader's own hand on the view: a glide gives way to it, and the
    // frames after a pin leave the view where the reader puts it.
    const byHand = () => {
      handAtRef.current = nowMs();
      if (glideRef.current) endGlide();
    };
    const handEvents = ["wheel", "touchmove", "pointerdown", "keydown"] as const;
    const handRoot = rootEl ?? viewport;
    for (const name of handEvents) handRoot.addEventListener(name, byHand, { passive: true });
    return () => {
      viewport.removeEventListener("scroll", read);
      viewport.removeEventListener("scrollend", onScrollEnd);
      for (const name of handEvents) handRoot.removeEventListener(name, byHand);
      viewport.style.overflowAnchor = previousAnchor;
      endGlide();
      if (settleFrameRef.current && typeof cancelAnimationFrame === "function") cancelAnimationFrame(settleFrameRef.current);
      settleFrameRef.current = 0;
    };
  }, [rootEl, settle]);

  // An answer grows WITHOUT a new item arriving, so no render-driven effect
  // fires for it; the content's own size is the honest signal.
  useEffect(() => {
    const viewport = scrollViewportOf(rootEl);
    if (!viewport || !contentEl || typeof ResizeObserver === "undefined") return;
    const ro = new ResizeObserver(() => {
      if (!stickRef.current) return;
      follow();
      setAtEnd(true);
    });
    ro.observe(contentEl);
    return () => ro.disconnect();
  }, [rootEl, contentEl, follow]);

  /**
   * The reader picked a place themselves (opened something to read in the
   * middle of the page): stop following until they are back at the end. Call
   * it BEFORE the content grows, or the growth still counts as new output.
   */
  const release = useCallback(() => {
    endGlide();
    stickRef.current = false;
    setAtEnd(false);
  }, []);

  return { rootRef, contentRef, atEnd, jumpToEnd, snapToEnd, follow, release };
}

/** Frames after a pin in which the view is checked against its end. */
const SETTLE_FRAMES = 4;
/** A glide that has not moved for this many frames is over (it starts a few frames late). */
const GLIDE_STILL_FRAMES = 8;
/** No glide is given longer than this. */
const GLIDE_MAX_MS = 1500;
/** For this long after a wheel turn, a touch or a key, the view is the reader's. */
const HAND_MS = 300;

function nowMs(): number {
  return typeof performance !== "undefined" ? performance.now() : Date.now();
}

/** At the end to the pixel, which a view that follows has to be. */
function isAtEnd(viewport: HTMLElement): boolean {
  return viewport.scrollHeight - viewport.scrollTop - viewport.clientHeight <= 1;
}

/**
 * Within this many pixels of the bottom counts as "at the end", so sub-pixel
 * rounding — or the half line a growing answer adds between two frames —
 * never reads as "they scrolled away".
 */
export const NEAR_END_PX = 72;

export function isNearEnd(scrollTop: number, scrollHeight: number, clientHeight: number): boolean {
  return scrollHeight - scrollTop - clientHeight <= NEAR_END_PX;
}

/** Radix renders the scrolling element as a viewport inside the ScrollArea root. */
export function scrollViewportOf(root: HTMLElement | null): HTMLElement | null {
  if (!root) return null;
  return (root.querySelector("[data-radix-scroll-area-viewport]") as HTMLElement | null) ?? root;
}

function prefersReducedMotion(): boolean {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    ? window.matchMedia("(prefers-reduced-motion: reduce)").matches
    : false;
}
