import { useLayoutEffect } from "react";
import type { PanePorts } from "./connect/paneRuntime";
import type { MutableRefObject } from "react";
import { captureTerminalViewport, restoreTerminalViewport } from "./paneShared";

export function usePaneStageSwitch({ active, containerRef, termRef, parkedRef, replayCurtainRef, preservedViewportRef, replayGenerationRef, replayRevealFrameRef, visibilityRef, resizeRef, returnResizeRef, claimResizeRef, repaintOnReturnRef, settleRebuildRef, activeRef, setTailReady, armCurtainWatchdog }: {
  active: boolean;
  containerRef: MutableRefObject<HTMLDivElement | null>;
  termRef: PanePorts["termRef"];
  parkedRef: MutableRefObject<boolean>;
  replayCurtainRef: PanePorts["replayCurtainRef"];
  preservedViewportRef: PanePorts["preservedViewportRef"];
  replayGenerationRef: PanePorts["replayGenerationRef"];
  replayRevealFrameRef: PanePorts["replayRevealFrameRef"];
  visibilityRef: PanePorts["visibilityRef"];
  resizeRef: PanePorts["resizeRef"];
  returnResizeRef: PanePorts["returnResizeRef"];
  claimResizeRef: PanePorts["claimResizeRef"];
  repaintOnReturnRef: PanePorts["repaintOnReturnRef"];
  settleRebuildRef: PanePorts["settleRebuildRef"];
  activeRef: PanePorts["activeRef"];
  setTailReady: PanePorts["setTailReady"];
  armCurtainWatchdog: PanePorts["armCurtainWatchdog"];
}) {
  /*
   * A chat-stage switch changes a pane from `display:none` to the full canvas
   * in one commit. Refit and restore the reader's viewport before that frame
   * paints; a pane already at the tail keeps following it, while hidden
   * siblings stay parked even when a prompt is addressed to them.
   */
  useLayoutEffect(() => {
    const departingViewport = !active
      ? captureTerminalViewport(termRef.current)
      : null;
    if (
      !active &&
      departingViewport &&
      (!replayCurtainRef.current || !preservedViewportRef.current)
    ) {
      preservedViewportRef.current = departingViewport;
    }
    // A stage change supersedes every reveal owned by the stage before it. If
    // a replay is still parsing, the active branch's queue barrier below waits
    // for it and becomes the only path allowed to lift the new curtain.
    replayGenerationRef.current += 1;
    replayCurtainRef.current = false;
    if (replayRevealFrameRef.current !== undefined) {
      cancelAnimationFrame(replayRevealFrameRef.current);
      replayRevealFrameRef.current = undefined;
    }
    if (!active) {
      containerRef.current?.style.setProperty("visibility", "hidden");
      setTailReady(false);
      visibilityRef.current?.park();
      if (termRef.current) parkedRef.current = true;
      return;
    }
    // Back from a spell off the stage, as opposed to the first time on it: the
    // agent is asked for a whole new screen (see RETURN_REPAINT_NUDGE_MS).
    const returning = parkedRef.current;
    parkedRef.current = false;
    containerRef.current?.style.setProperty("visibility", "hidden");
    setTailReady(false);
    armCurtainWatchdog();
    let cancelled = false;
    let frame: number | undefined;
    const returningViewport = preservedViewportRef.current;
    const restoreViewport = () => {
      resizeRef.current?.();
      (returning ? returnResizeRef : claimResizeRef).current?.();
      restoreTerminalViewport(termRef.current, returningViewport);
    };
    // Measure the now-mounted stage before parsing held output. Once xterm has
    // consumed that output, one final frame lets its canvas and viewport settle;
    // only then may the surface paint.
    restoreViewport();
    const settle = () => {
      if (cancelled || !activeRef.current) return;
      restoreViewport();
      frame = requestAnimationFrame(() => {
        if (cancelled || !activeRef.current) return;
        restoreViewport();
        // A replay mid-rebuild keeps the curtain: lifting it here would show
        // the rest of its history printing. Its own completion reveals the
        // pane (see `replayToPane`).
        if (replayCurtainRef.current) return;
        const reveal = () => {
          restoreViewport();
          if (returning) {
            // Draw every row from the buffer, not only the rows that changed:
            // a surface hidden for a while may have dropped what it showed.
            const term = termRef.current;
            term?.refresh?.(0, Math.max(0, term.rows - 1));
          }
          setTailReady(true);
          containerRef.current?.style.removeProperty("visibility");
          if (preservedViewportRef.current === returningViewport) {
            preservedViewportRef.current = null;
          }
        };
        // Taking the stage announces a new size, and an agent answers a size
        // by painting its whole screen again — the same redraw the replay path
        // waits out, arriving just as late. Reveal once this pane is quiet.
        const settleFn = settleRebuildRef.current;
        if (settleFn) settleFn(replayGenerationRef.current, reveal);
        else reveal();
      });
    };
    const afterFlush = () => {
      if (cancelled || !activeRef.current) return;
      restoreViewport();
      // The held flush joins the END of xterm's write queue, but a write that
      // reached the terminal earlier — a replay flushed while this pane was
      // hidden — may still be mid-parse, and settling now would lift the
      // curtain onto its tail printing. An empty write is a queue barrier:
      // its callback fires only after everything already queued has parsed.
      //
      // A returning pane asks for its new screen first: the redraw that answers
      // is output, and output keeps pushing the settle's quiet window back, so
      // it lands behind the curtain.
      if (returning) repaintOnReturnRef.current?.();
      const term = termRef.current;
      if (term) term.write("", settle);
      else settle();
    };
    const visibility = visibilityRef.current;
    if (visibility) visibility.show(afterFlush);
    else afterFlush();
    return () => {
      cancelled = true;
      if (frame !== undefined) cancelAnimationFrame(frame);
    };
  }, [active]);
}
