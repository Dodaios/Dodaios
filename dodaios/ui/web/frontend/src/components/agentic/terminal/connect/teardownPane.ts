import { holdsSizeLead, releaseSizeLead } from "../../paneSizeLead";
import { cancelPaneReflow } from "../../paneReflowQueue";
import type { PaneState, PanePorts } from "./paneRuntime";
import type { mountTerminal } from "./mountTerminal";
import type { installPaneOutput } from "./installPaneOutput";
import type { installPaneSizing } from "./installPaneSizing";
import type { installPaneObservers } from "./installPaneObservers";

export function teardownPane(p: PanePorts, s: PaneState, a: ReturnType<typeof mountTerminal> & ReturnType<typeof installPaneOutput> & ReturnType<typeof installPaneSizing> & ReturnType<typeof installPaneObservers>) {
  const { container, termRef, fitRef, resizeRef, claimResizeRef, returnResizeRef, repaintOnReturnRef, takeOwnershipRef, heldLeadRef, visibilityRef, replayCurtainRef, replayGenerationRef, replayRevealFrameRef, settleRebuildRef } = p;
  const { term, disposeQuerySuppression, unregisterLive, renderer, synchronizedOutput, disposeMouseSelection, disposePromptSelection, disposeBrowseExit, disposeCopyBridge, disposePasteBridge, disposeNewlineBridge, cancelHoldTimer, visibility, clearSettleTimers, settleRebuild, leadKey, leadToken, clearDeferredResize, claimResize, releasePresented, unregisterPresent, reclaimOnGesture, stopLeadWatch, disposeFontSync, reflow, clearNarrowHold, observedReflow, scheduleResize, ro, onDocumentVisible } = a;
  s.disposed = true;
  replayGenerationRef.current += 1;
  replayCurtainRef.current = false;
  if (replayRevealFrameRef.current !== undefined) {
    cancelAnimationFrame(replayRevealFrameRef.current);
    replayRevealFrameRef.current = undefined;
  }
  container.style.removeProperty("visibility");
  // A pending reveal would fire into a disposed terminal, and its timers
  // would outlive the pane that armed them.
  clearSettleTimers();
  s.settleReveal = null;
  s.settlingFor = 0;
  if (settleRebuildRef.current === settleRebuild) {
    settleRebuildRef.current = null;
  }
  // Before the terminal is disposed below: a deadline flush one tick later
  // would write into it after it is gone.
  cancelHoldTimer();
  // Same for a fit still waiting for a parse gap — it would reflow a
  // disposed terminal inside a detached element.
  clearDeferredResize();
  s.resumeResize = null;
  if (s.resizeTimer !== undefined) window.clearTimeout(s.resizeTimer);
  if (s.dragRefitTimer !== undefined) window.clearTimeout(s.dragRefitTimer);
  // A queued reflow outlives the pane by up to a frame, and would then fit
  // a disposed terminal inside a detached element.
  cancelPaneReflow(reflow);
  cancelPaneReflow(observedReflow);
  clearNarrowHold();
  window.removeEventListener("resize", scheduleResize);
  window.removeEventListener("focus", claimResize);
  window.removeEventListener("pointermove", reclaimOnGesture);
  window.removeEventListener("pointerdown", reclaimOnGesture, true);
  window.removeEventListener("keydown", reclaimOnGesture, true);
  if (typeof document !== "undefined") {
    document.removeEventListener("visibilitychange", onDocumentVisible);
  }
  ro.disconnect();
  s.io?.disconnect();
  disposeFontSync();
  disposeMouseSelection();
  disposePromptSelection();
  disposeBrowseExit();
  disposeCopyBridge();
  disposePasteBridge();
  disposeNewlineBridge();
  disposeQuerySuppression();
  synchronizedOutput.dispose();
  try {
    s.socket?.close();
  } catch {
    /* ignore */
  }
  // After the socket, so this viewer is gone before another one of the
  // pane here takes the size back.
  stopLeadWatch();
  // Remembered for a rebuild of this same viewer; forgotten on unmount,
  // when nothing reads it again.
  heldLeadRef.current = holdsSizeLead(leadKey, leadToken);
  releaseSizeLead(leadKey, leadToken);
  // Before the terminal: frees this pane's WebGL context slot.
  releasePresented();
  unregisterPresent();
  unregisterLive();
  renderer.dispose();
  term.dispose();
  termRef.current = null;
  fitRef.current = null;
  resizeRef.current = null;
  claimResizeRef.current = null;
  repaintOnReturnRef.current = null;
  returnResizeRef.current = null;
  takeOwnershipRef.current = null;
  if (visibilityRef.current === visibility) visibilityRef.current = null;
}
