import { clearTerminalTextureAtlas } from "../../terminalRenderer";
import { syncTerminalFont } from "@/lib/terminalFont";
import { queuePaneReflow } from "../../paneReflowQueue";
import { OFFSCREEN_MARGIN_PX } from "../../offscreenBuffer";
import { DRAG_REFIT_MS, NARROW_SETTLE_MS, MIN_REAL_COLS, documentHidden } from "../paneShared";
import type { PaneState, PanePorts } from "./paneRuntime";
import type { mountTerminal } from "./mountTerminal";
import type { installPaneOutput } from "./installPaneOutput";
import type { installPaneSizing } from "./installPaneSizing";

export function installPaneObservers(p: PanePorts, s: PaneState, a: ReturnType<typeof mountTerminal> & ReturnType<typeof installPaneOutput> & ReturnType<typeof installPaneSizing>) {
  const { container, activeRef, layoutBusyRef } = p;
  const { term, fit, measurable, showPane, parkPane, revealIfOnScreen, sendResize, claimResize } = a;
  // The mount-time fit measured whatever font was loaded at that moment. If
  // the display font arrives afterwards, the cell width changes underneath the
  // already-computed column count: the agent formats its output for a width
  // the pane does not have, and every glyph is painted wider than the cell it
  // owns until the line has drifted a full column out of its grid. Both are
  // the reported symptom. See ./../../lib/terminalFont for why waiting on
  // `document.fonts.ready` and re-fitting cannot fix either.
  const disposeFontSync = syncTerminalFont(term, () => {
    if (s.disposed) return;
    clearTerminalTextureAtlas(term);
    sendResize();
  });

  // Resizes are coalesced: dragging a split or the window fires the observer
  // dozens of times a second, and every fit both reflows xterm's buffer and
  // sends a PTY resize the agent redraws for. Unthrottled that is the visible
  // flicker while resizing.
  s.resizeTimer = undefined;
  /** The pending mid-drag refit — a throttle, so it must NOT be reset per tick. */
  s.dragRefitTimer = undefined;
  // The queued form of `sendResize`, kept as ONE stable function so the queue
  // can recognise this pane's pending reflow — both to skip a duplicate and
  // to drop it when the pane goes away. See ./paneReflowQueue for why panes
  // must not reflow in the same frame as each other.
  const reflow = () => sendResize();
  /** The narrower width this pane is waiting to see hold (NARROW_SETTLE_MS). */
  let narrowCols: number | null = null;
  let narrowTimer: number | undefined;
  const clearNarrowHold = () => {
    narrowCols = null;
    if (narrowTimer !== undefined) window.clearTimeout(narrowTimer);
    narrowTimer = undefined;
  };
  /**
   * The observer's refit: a wider tile is taken at once, a narrower one only
   * once it has held for NARROW_SETTLE_MS (see there for why).
   */
  const observedReflow = () => {
    if (s.disposed) return;
    let proposedCols: number | undefined;
    // Only a pane that already gave its agent a size can hold one back; the
    // first fit after mount is never a transient.
    if (s.sentSize && measurable() && activeRef.current) {
      try {
        proposedCols = fit.proposeDimensions()?.cols;
      } catch {
        proposedCols = undefined;
      }
    }
    const cols =
      proposedCols !== undefined && Number.isFinite(proposedCols)
        ? Math.max(proposedCols, MIN_REAL_COLS)
        : undefined;
    if (cols === undefined || cols >= term.cols) {
      clearNarrowHold();
      sendResize();
      return;
    }
    if (cols === narrowCols) {
      // Held for the whole window: the tile really is this narrow now.
      if (narrowTimer === undefined) {
        narrowCols = null;
        sendResize();
      }
      return;
    }
    clearNarrowHold();
    narrowCols = cols;
    narrowTimer = window.setTimeout(() => {
      narrowTimer = undefined;
      queuePaneReflow(observedReflow);
    }, NARROW_SETTLE_MS);
  };
  const scheduleResize = () => {
    // The Verse window has its own observer. The hidden tile must not fit this pane back to 0.
    if (s.presentedHost) return;
    // While a seam or the prompt bar is being dragged the pane still
    // follows, but on a leash: at most one refit per DRAG_REFIT_MS, so the
    // text flows toward the seam in steps instead of freezing until release.
    // A throttle rather than the debounce below on purpose — the observer
    // fires continuously for as long as the seam moves, and a debounce would
    // wait for a pause that a moving pointer never offers.
    if (layoutBusyRef.current) {
      if (s.dragRefitTimer !== undefined) return;
      s.dragRefitTimer = window.setTimeout(() => {
        s.dragRefitTimer = undefined;
        // A drag that ended while this window was pending has already taken
        // its exact final size through the `layoutBusy` release effect.
        if (layoutBusyRef.current) queuePaneReflow(reflow);
      }, DRAG_REFIT_MS);
      return;
    }
    if (s.resizeTimer !== undefined) window.clearTimeout(s.resizeTimer);
    s.resizeTimer = window.setTimeout(() => {
      s.resizeTimer = undefined;
      queuePaneReflow(observedReflow);
    }, 80);
  };

  window.addEventListener("resize", scheduleResize);
  const ro = new ResizeObserver(scheduleResize);
  ro.observe(container);

  /*
   * Stop drawing panes nobody can see.
   *
   * Two cases, one mechanism: a pane scrolled past in a tall grid, and a pane
   * hidden with `display:none` because a sibling is maximized — neither
   * intersects the viewport, and both used to keep parsing and repainting an
   * agent's full-screen UI on the thread that owes the user a keystroke.
   *
   * The margin is generous on purpose: a pane one flick of the wheel away
   * catches up before it is looked at, so scrolling never shows a pane
   * mid-write. `IntersectionObserver` is absent in some test environments and
   * very old engines — there the pane simply stays visible, which is exactly
   * the behaviour this replaces.
   */
  s.io = null;
  if (typeof IntersectionObserver !== "undefined") {
    s.io = new IntersectionObserver(
      (entries) => {
        const onScreen = entries[entries.length - 1]?.isIntersecting ?? true;
        if (onScreen) {
          showPane();
          return;
        }
        // A hidden DOCUMENT is not an off-screen pane, and treating the two
        // as one is what left panes black for minutes at a time. While the
        // window is behind another one, minimized, or its tab in the
        // background, EVERY element here reports intersecting nothing — and
        // bringing the window back changes no geometry, so no further
        // callback ever arrives to undo it. Parking on that verdict meant a
        // pane opened while the user was looking elsewhere never drew again
        // (measured 2026-07-27: a workspace spawned by voice came back with
        // its new panes empty, and a chatty CLI took ~3 minutes to appear —
        // exactly how long 256 KB of output takes to force the buffer out).
        //
        // Parking is also pointless in that state: a hidden document paints
        // nothing, so there is no frame budget being defended. The whole
        // reason this exists is panes competing for the main thread WHILE the
        // user watches another one.
        if (!documentHidden()) parkPane();
      },
      { rootMargin: `${OFFSCREEN_MARGIN_PX}px` },
    );
    s.io.observe(container);
  }

  /*
   * The window came back — check whether this pane is on screen now.
   *
   * The observer cannot answer this on its own: showing a window again moves
   * neither geometry nor scroll position, which are the only things that make
   * it recompute. Without this a pane parked while the app sat behind an
   * editor stayed parked after the user switched back to it.
   */
  const onDocumentVisible = () => {
    if (documentHidden()) return;
    revealIfOnScreen();
    claimResize();
  };
  if (typeof document !== "undefined") {
    document.addEventListener("visibilitychange", onDocumentVisible);
  }
  window.addEventListener("focus", claimResize);
  return { disposeFontSync, reflow, clearNarrowHold, observedReflow, scheduleResize, ro, onDocumentVisible };
}
