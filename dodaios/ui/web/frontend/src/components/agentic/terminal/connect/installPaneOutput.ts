import { clearTuiCanvasFill } from "../../terminalGlass";
import { createLightPaneInk } from "../../terminalLightInk";
import { boxOnScreen, OffscreenBuffer, PARKED_RECHECK_MS } from "../../offscreenBuffer";
import { wakePresentedRenderer } from "../../presentedRenderer";
import { FULL_SCREEN_ERASE_SCAN_TAIL, hasFullScreenErase } from "../../terminalRepaint";
import { captureTerminalViewport, restoreTerminalViewport, REBUILD_QUIET_MS, REBUILD_SETTLE_MAX_MS, REPAINT_WAIT_MAX_MS, PaneStatus } from "../paneShared";
import type { PaneState, PanePorts } from "./paneRuntime";
import type { mountTerminal } from "./mountTerminal";

export function installPaneOutput(p: PanePorts, s: PaneState, a: ReturnType<typeof mountTerminal>) {
  const { container, onStatusRef, appearanceRef, activeRef, visibilityRef, statusRef, setVisibleStatus, setStatusDetail, setPainted, setTailReady, replayCurtainRef, preservedViewportRef, replayGenerationRef, replayRevealFrameRef, settleRebuildRef, armCurtainWatchdog } = p;
  const { term, synchronizedOutput, measurable } = a;
  const report = (status: PaneStatus, detail?: string) => {
    statusRef.current = status;
    setVisibleStatus(status);
    setStatusDetail(detail ?? "");
    onStatusRef.current?.(status, detail);
  };

  s.socket = null;
  s.disposed = false;
  // At most one line per KIND of trouble: one when the connection starts
  // wobbling, one if it is declared unreachable. A reconnect that succeeds
  // redraws the screen from the server's replay buffer anyway, so narrating
  // every attempt would scroll the agent's own output away for nothing — and
  // a pane that keeps knocking every half minute would otherwise stamp a red
  // line into the terminal twice a minute forever.
  s.troubleShown = null;
  // And at most one line per WORDING, which is a separate limit. A refused
  // attach reaches this twice — once as the reason the server sent, then
  // again as the verdict on the close that immediately follows it — and the
  // two are now the same sentence, because the second one no longer invents
  // its own. Printing it again in red under itself in yellow reads like two
  // problems.
  s.troubleText = "";

  /*
   * Is anyone actually looking at this pane?
   *
   * A workspace holds dozens of terminals and the browser draws all of them on
   * the SAME thread that has to notice a keypress — so a pane scrolled out of
   * the grid, or hidden behind a maximized sibling, was spending real frames
   * painting pixels nobody could see, at the direct expense of the pane being
   * typed into. Its output is parked instead and written in one call when it
   * comes back (see ./offscreenBuffer).
   *
   * Starts as VISIBLE: the observer's first callback is asynchronous, and a
   * pane that withheld output until it arrived would flicker blank on mount.
   */
  let paneVisible = activeRef.current;
  const offscreen = new OffscreenBuffer();
  /** When this pane last measured itself while parked (see `recheckParked`). */
  let parkedCheckedAt = 0;
  /** The pending deadline flush, if this pane is holding anything. */
  let holdTimer: number | undefined;

  const cancelHoldTimer = () => {
    if (holdTimer === undefined) return;
    window.clearTimeout(holdTimer);
    holdTimer = undefined;
  };

  /*
   * How many writes this pane has handed xterm that have not finished
   * parsing.
   *
   * The one thing a resize has to know. xterm parses a write in time slices,
   * so "the socket delivered it" and "the screen has it" are different
   * moments, and reflowing the buffer in between moves the rows the rest of
   * that stream is addressing (see RESIZE_PARSE_WAIT_MS). Counted rather
   * than asked, because xterm exposes no such question — every byte this
   * pane draws goes through `writeToTerminal` below, which is what makes the
   * count complete.
   */
  s.parsing = 0;
  /**
   * Run the geometry change this pane is holding back, if it is holding one.
   *
   * Assigned once the resize path below exists; the writes above are defined
   * first because everything else in this scope draws through them.
   */
  s.resumeResize = null;

  /** This pane's light-ground re-inker; it tracks the CLI's faint state. */
  const lightInk = createLightPaneInk();

  /** Hand bytes to xterm, keeping the count of what is still being parsed. */
  const writeToTerminal = (text: string, afterWrite?: () => void) => {
    s.parsing += 1;
    // A TUI that paints its theme ground on every cell would hide the
    // glass this pane sits on. Default-background those fills here, on
    // the way into xterm — see ./terminalGlass. A light pane also re-inks
    // the dark-theme truecolor most CLIs paint — see ./terminalLightInk.
    const glass = clearTuiCanvasFill(text);
    term.write(appearanceRef.current === "light" ? lightInk(glass) : glass, () => {
      s.parsing = Math.max(0, s.parsing - 1);
      afterWrite?.();
      // The parser is between chunks — the one safe moment to reflow.
      if (s.parsing === 0) s.resumeResize?.();
    });
  };

  /**
   * Write what is held, whether or not this pane believes it is watched.
   *
   * The deadline half of parking (see ./offscreenBuffer): being wrong about
   * visibility must cost a coalesced write, never a screen that stopped.
   */
  const flushHeld = (afterFlush?: () => void) => {
    cancelHoldTimer();
    const held = offscreen.drain();
    if (held) {
      writeToTerminal(held, afterFlush);
      return;
    }
    afterFlush?.();
  };

  /** Make sure the held output has a flush coming, without moving one nearer. */
  const armHoldTimer = () => {
    if (holdTimer !== undefined) return;
    const due = offscreen.dueIn();
    if (due === null) return;
    holdTimer = window.setTimeout(() => {
      holdTimer = undefined;
      if (s.disposed) return;
      flushHeld();
    }, due);
  };

  const showPane = (afterFlush?: () => void) => {
    // The Verse window is a reader even while the IDE tile is off the stage.
    if (!activeRef.current && !s.presentedHost) return;
    // Output held for a size the hidden tile never had would sit until the
    // offscreen deadline — about a second — while the user is already
    // typing into the window. The window is measurable; the report is not
    // what they are waiting on.
    if (s.presentedHost && s.awaitingSizeReport && measurable()) {
      s.awaitingSizeReport = false;
    }
    if (paneVisible) {
      if (s.awaitingSizeReport) afterFlush?.();
      else flushHeld(afterFlush);
      return;
    }
    paneVisible = true;
    // Held output waits for the size report (see `awaitingSizeReport`); its
    // deadline flush is still armed, so waiting cannot freeze the pane.
    if (s.awaitingSizeReport) afterFlush?.();
    else flushHeld(afterFlush);
  };

  const parkPane = () => {
    if (s.presentedHost) return;
    paneVisible = false;
    // The next chunk of output measures immediately rather than waiting out
    // an interval that started before this pane was even parked.
    parkedCheckedAt = 0;
  };
  const visibility = { show: showPane, park: parkPane };
  visibilityRef.current = visibility;

  /**
   * Un-park this pane if it is genuinely on screen — measured, not remembered.
   *
   * The observer below reports CHANGES, and a pane can be left parked in a
   * state no change ever leads out of (see `boxOnScreen`). This is the way
   * back, and it is called from the two moments that produce exactly that
   * state: the document becoming visible again, and the pane being resized.
   */
  const revealIfOnScreen = () => {
    // The IDE tile is off the stage on purpose while the window has the
    // xterm. That must not count as "nobody is looking".
    if (s.presentedHost) {
      showPane();
      return;
    }
    if (!activeRef.current) return;
    if (paneVisible) return;
    const box = container.getBoundingClientRect();
    const viewport = {
      width: window.innerWidth || 0,
      height: window.innerHeight || 0,
    };
    if (boxOnScreen(box, viewport)) showPane();
  };

  /**
   * A parked pane that is still being talked to, asking the only question
   * that matters: can the user see me right now?
   *
   * The observer answers that for every state it reports. The failure this
   * guards is the state it does NOT report — and the two known ones
   * (`visibilitychange`, resize) were found one live incident at a time, so
   * assuming they are the last two is how the next one costs another
   * afternoon. The symptom is always identical and always severe: Jarvis
   * types a prompt into a pane, the agent starts work, and the user watches
   * an empty rectangle and concludes nothing was sent (reported 2026-07-27,
   * where the prompt reached the agent 1.4 s BEFORE it was announced and the
   * pane showed its boot screen for another minute).
   *
   * Throttled, because output arrives in frames and a rectangle measurement
   * forces layout: at most one per {@link PARKED_RECHECK_MS} per parked pane,
   * and none at all for a parked pane whose agent has gone quiet — nobody
   * misses a screen that is not changing.
   */
  const recheckParked = () => {
    const now = Date.now();
    if (now - parkedCheckedAt < PARKED_RECHECK_MS) return;
    parkedCheckedAt = now;
    revealIfOnScreen();
  };

  /*
   * Reveal a rebuilt pane on QUIET, not on one write having finished.
   *
   * Two timers, and the difference between them is the whole contract. The
   * quiet timer is restarted by every chunk that arrives while the curtain is
   * down, so the repaint the server asks for after a replay plays out behind
   * it. The deadline is armed once and NEVER restarted by output — it is the
   * promise that the pane comes back even if the agent never stops talking.
   */
  let quietTimer: number | undefined;
  let deadlineTimer: number | undefined;
  /** What to run once the rebuild has settled; null while none is pending. */
  s.settleReveal = null;
  /** The rebuild being waited out, so a superseded one cannot reveal. */
  s.settlingFor = 0;
  /**
   * Is the current rebuild still waiting for the repaint's whole-screen
   * erase (see {@link REPAINT_WAIT_MAX_MS})? Set by a replay that announced
   * one, cleared by the erase arriving — which may happen before the replay
   * has even finished parsing.
   */
  let repaintPending = false;
  /** The last bytes of the preceding chunk, in case it split the erase. */
  let eraseScanTail = "";

  const noteRepaintOutput = (text: string) => {
    if (!repaintPending) return;
    const scanned = eraseScanTail + text;
    if (hasFullScreenErase(scanned)) {
      repaintPending = false;
      eraseScanTail = "";
      return;
    }
    eraseScanTail = scanned.slice(-FULL_SCREEN_ERASE_SCAN_TAIL);
  };

  const clearSettleTimers = () => {
    if (quietTimer !== undefined) window.clearTimeout(quietTimer);
    if (deadlineTimer !== undefined) window.clearTimeout(deadlineTimer);
    quietTimer = undefined;
    deadlineTimer = undefined;
  };

  const finishSettle = () => {
    const reveal = s.settleReveal;
    const generation = s.settlingFor;
    clearSettleTimers();
    s.settlingFor = 0;
    s.settleReveal = null;
    repaintPending = false;
    eraseScanTail = "";
    // Before the guards, deliberately: a settle abandoned because the pane
    // went away must not leave the curtain flag raised, or the next stage
    // switch would refuse to lift a curtain nobody owns any more.
    replayCurtainRef.current = false;
    if (
      s.disposed ||
      !activeRef.current ||
      generation !== replayGenerationRef.current
    ) {
      return;
    }
    reveal?.();
  };

  /** Something is still being drawn — push the reveal back one quiet window. */
  const noteRebuildOutput = () => {
    if (s.settlingFor === 0) return;
    if (quietTimer !== undefined) window.clearTimeout(quietTimer);
    quietTimer = undefined;
    // Quiet proves nothing while the promised repaint has not started: the
    // agent may simply not have answered yet. Only the deadline runs then.
    if (repaintPending) return;
    quietTimer = window.setTimeout(finishSettle, REBUILD_QUIET_MS);
  };

  const settleRebuild = (generation: number, reveal: () => void) => {
    if (s.disposed || generation !== replayGenerationRef.current) return;
    clearSettleTimers();
    s.settlingFor = generation;
    s.settleReveal = reveal;
    deadlineTimer = window.setTimeout(
      finishSettle,
      repaintPending ? REPAINT_WAIT_MAX_MS : REBUILD_SETTLE_MAX_MS,
    );
    noteRebuildOutput();
  };
  settleRebuildRef.current = settleRebuild;

  // Everything this pane draws goes through here, not just the agent's
  // stream: an exit banner written straight to xterm while output is parked
  // would appear ABOVE the output it is supposed to follow.
  const writeToPane = (text: string, afterWrite?: () => void) => {
    if (!text) return;
    // Anything drawn while a rebuild settles belongs to that rebuild. The
    // viewport is deliberately NOT touched here — where the pane opens is
    // the reveal's decision, and it restores what the reader was looking at.
    noteRepaintOutput(text);
    noteRebuildOutput();
    // The first byte is what retires the "starting" overlay — and it is taken
    // HERE rather than at the socket, so a pane whose output is parked
    // offscreen still counts as painted. It has a screen; nobody is looking
    // at it. Cheap to call per chunk: React bails out on an unchanged value.
    setPainted(true);
    // The Verse window is the reader. Parking its bytes until
    // OFFSCREEN_MAX_HOLD_MS is the pause between a keystroke and the glyph:
    // the hidden IDE tile is not the surface being watched, and a paused
    // xterm renderer would keep the previous frame even after the write.
    if (s.presentedHost && s.awaitingSizeReport && measurable()) {
      s.awaitingSizeReport = false;
    }
    // Recheck BEFORE the decision. A parked pane that is actually on screen
    // un-parks itself here, and this same chunk is what the user is waiting
    // to see — reading the flag from before the recheck parked it again.
    if (!paneVisible && !s.presentedHost) recheckParked();
    if ((paneVisible || s.presentedHost !== null) && !s.awaitingSizeReport) {
      if (s.presentedHost) wakePresentedRenderer(term);
      // Older parked bytes belong under this chunk, never after it.
      if (offscreen.pending > 0) flushHeld();
      writeToTerminal(text, afterWrite);
      return;
    }
    offscreen.push(text);
    // A pane that has parked all it may hold WRITES rather than forgets. An
    // agent's TUI is drawn by relative cursor moves, so a stream that lost
    // its front does not repair itself — the pane would come back showing
    // the spinner row it rewrote last and blank rows where its prompt box
    // belongs. Parsing into a surface nobody is painting is the cheap half
    // of what parking avoids; a permanently broken screen is not.
    //
    // The same answer, for the same reason, once it has held long enough:
    // this pane's belief that nobody is watching may simply be wrong, and
    // that must cost a coalesced write rather than a frozen terminal. The
    // timer covers the case this branch cannot — an agent that goes quiet
    // right after saying something would otherwise hold that last word for
    // as long as it stays quiet.
    if (offscreen.full || offscreen.stale()) {
      flushHeld();
      return;
    }
    armHoldTimer();
  };

  /**
   * Draw the screen this pane is re-joining — on a terminal cleared first.
   *
   * A replay is not a big chunk of output, it is a REBUILD: the server hands
   * over the raw bytes that drew the screen the agent is looking at, so that
   * a pane which was away — a reconnect, a backend restart, a workspace
   * switch — comes back showing the interface rather than a blank rectangle.
   *
   * Writing it onto whatever is already here draws that interface a second
   * time over the copy still on screen, and the two do not stack tidily. An
   * Ink TUI (Claude Code, Codex) skips unchanged cells with cursor moves
   * instead of overwriting them with spaces, so the first copy shows THROUGH
   * the second, character by character: "plus everything new" came back as
   * "plueverythingwnew" (reported 2026-07-29, three panes, unreadable). Nor does
   * it heal — the agent repaints its own visible rows and never the
   * scrollback above them, so every reconnect added another layer.
   *
   * `reset()` rather than `clear()`: the replay re-states the screen modes
   * the agent negotiated (alternate screen, mouse tracking), and those have
   * to start from a known state or the pane inherits half of the old one.
   */
  const replayToPane = (text: string, awaitRepaint = false) => {
    if (!text) return;
    // A newer replay replaces whatever an older one was waiting for.
    repaintPending = false;
    eraseScanTail = "";
    const replayViewport =
      preservedViewportRef.current ?? captureTerminalViewport(term);
    if (replayViewport) preservedViewportRef.current = replayViewport;
    const generation = replayGenerationRef.current + 1;
    replayGenerationRef.current = generation;
    if (replayRevealFrameRef.current !== undefined) {
      cancelAnimationFrame(replayRevealFrameRef.current);
      replayRevealFrameRef.current = undefined;
    }
    // Parked output belongs to the screen this replay REPLACES, and it was
    // captured before it. Written afterwards it would paint the older screen
    // over the newer one; written before, it would be reset away regardless.
    // The deadline goes with it — a flush firing after this would draw the
    // screen this replay just replaced.
    cancelHoldTimer();
    offscreen.drain();
    // React state is not a synchronous paint barrier. In a real WebSocket
    // callback, `setTailReady(false)` may not reach the DOM before xterm's
    // write queue starts parsing. Hide the canvas host imperatively BEFORE
    // reset/write; React still mirrors the curtain below for later renders.
    // A replay waiting for the size report is held (see
    // `awaitingSizeReport`), and the callback that would lift a curtain
    // goes with it.
    const curtain = paneVisible && !s.awaitingSizeReport && activeRef.current;
    if (curtain) {
      container.style.visibility = "hidden";
      replayCurtainRef.current = true;
      setTailReady(false);
      armCurtainWatchdog();
    }
    synchronizedOutput.reset();
    term.reset();
    // A normal-buffer CLI's replay is its whole scrollback — the rows the
    // server kept as they scrolled off, up to this terminal's own 10,000
    // (`ScrollbackMirror` in dodaios/agentic_ide/scrollback.py), then the
    // screen — and xterm parses it in time slices. `reset()` above has just
    // emptied this terminal's own history, so the replay is the only copy:
    // whatever it leaves out cannot be scrolled back to (reported
    // 2026-11-12, when it was 128 KB of raw output and nothing at all after
    // a resize). Written onto a VISIBLE surface, the history prints top to
    // bottom with the viewport chasing it for the length of the parse
    // (reported 2026-08-08: every switch onto a fresh Codex pane opened on
    // the top of its history and visibly raced down). Alt-screen replays
    // repaint in place, which is why only normal-buffer CLIs ever showed
    // it. So the surface is hidden for the length of the rebuild — the same
    // curtain a chat-stage switch drops — and lifted one settled frame
    // after the reader's viewport has been restored.
    // Through the ordinary path, so a replay arriving while nobody is looking
    // is parked and un-parked by the same rules as anything else — and so it
    // counts as the pane having painted.
    writeToPane(text, () => {
      if (generation !== replayGenerationRef.current) return;
      if (s.disposed || !activeRef.current) {
        // A callback that fired while the pane was away must not leave the
        // stage-switch settle step refusing to lift the curtain forever.
        replayCurtainRef.current = false;
        return;
      }
      restoreTerminalViewport(term, replayViewport);
      if (!curtain) {
        replayCurtainRef.current = false;
        if (preservedViewportRef.current === replayViewport) {
          preservedViewportRef.current = null;
        }
        return;
      }
      // The bytes have parsed; the REPAINT they provoke has not arrived yet.
      // Stay hidden until this pane stops being drawn — see REBUILD_QUIET_MS.
      settleRebuild(generation, () => {
        replayRevealFrameRef.current = requestAnimationFrame(() => {
          replayRevealFrameRef.current = undefined;
          if (
            s.disposed ||
            !activeRef.current ||
            generation !== replayGenerationRef.current
          ) {
            return;
          }
          restoreTerminalViewport(term, replayViewport);
          setTailReady(true);
          container.style.removeProperty("visibility");
          if (preservedViewportRef.current === replayViewport) {
            preservedViewportRef.current = null;
          }
        });
      });
    });
    // Armed only AFTER the replay went in: its own bytes may well contain
    // an older erase, and that must not count as the repaint's answer.
    // Output from here on is live, so the erase it waits for can arrive
    // before the replay has finished parsing — the settle then starts on
    // an ordinary quiet window.
    if (curtain && awaitRepaint) repaintPending = true;
  };
  return { report, cancelHoldTimer, writeToTerminal, flushHeld, showPane, parkPane, visibility, revealIfOnScreen, clearSettleTimers, settleRebuild, writeToPane, replayToPane };
}
