import { mayLeadSize, onSizeLeadReleased, sizeLeadKey, takeSizeLead } from "../../paneSizeLead";
import { clearTerminalTextureAtlas } from "../../terminalRenderer";
import { attachTerminalBridge } from "@/lib/editActions";
import { alignTerminalCells } from "@/lib/terminalFont";
import { registerTerminalPresenter } from "@/lib/liveTerminals";
import { boxOnScreen } from "../../offscreenBuffer";
import { keepPresentedRendererAwake, wakePresentedRenderer } from "../../presentedRenderer";
import { installMouseSelection } from "../../terminalMouseSelection";
import { installBrowseExit } from "../../terminalBrowseExit";
import { RETURN_REPAINT_NUDGE_MS, RESIZE_PARSE_WAIT_MS, MIN_REAL_COLS, MIN_REAL_ROWS, GESTURE_RECLAIM_MS } from "../paneShared";
import type { PaneState, PanePorts } from "./paneRuntime";
import type { mountTerminal } from "./mountTerminal";
import type { installPaneOutput } from "./installPaneOutput";

export function installPaneSizing(p: PanePorts, s: PaneState, a: ReturnType<typeof mountTerminal> & ReturnType<typeof installPaneOutput>) {
  const { name, workspaceId, sizeLead, container, fontSizeRef, activeRef, resizeRef, claimResizeRef, returnResizeRef, repaintOnReturnRef, takeOwnershipRef, leadTokenRef, heldLeadRef } = p;
  const { term, fit, isMac, measurable, showPane, parkPane, revealIfOnScreen } = a;
  /*
   * The size the terminal PROCESS has actually been told.
   *
   * Recorded only when the socket took the frame, and that is the whole
   * point. A pane's socket is not open at all times — a backend restart, a
   * moment of unreachability, a reconnect in flight — and anything handed to
   * one in those states goes nowhere. Treating a size as delivered because
   * it was offered is what let one go missing for good: the pane looked
   * right, and the agent inside it went on formatting for the size it last
   * heard about, drawing its screen into a corner of a pane that had become
   * much larger. Left un-recorded, the next fit offers it again, and a fresh
   * socket is told unconditionally.
   */
  s.sentSize = null;
  /*
   * Does this pane believe it holds the one shared PTY geometry?
   *
   * A pseudo-terminal has exactly one size and a pane may be open in more
   * than one place — the desktop app, a browser tab beside it, a window a
   * tool opened to take a look — so the server hands the size to ONE viewer
   * and answers every other viewer's request with the geometry the owner
   * chose (see `onGeometry`). This flag is what tells a claim apart from a
   * repeat: a pane that owns the size and measures the same tile again has
   * nothing to say, while a pane that was displaced must speak up even
   * though its own measurement never changed. Set when a claim goes out,
   * cleared whenever the agent is reported to be in a size this pane did
   * not ask for.
   */
  s.owned = false;
  /** Is this pane showing a geometry another viewer chose? See reclaimOnGesture. */
  s.displaced = false;
  /*
   * This viewer's place among the pane's viewers in THIS window. The server
   * settles who sizes the pane between windows; inside one, a second viewer
   * of the same pane (the office's pane window over the IDE grid) would
   * otherwise take the size back on every gesture and the two would trade it
   * every GESTURE_RECLAIM_MS. See ./paneSizeLead.
   */
  const leadKey = sizeLeadKey(workspaceId, name);
  const leadToken = leadTokenRef.current;
  if (sizeLead || heldLeadRef.current) takeSizeLead(leadKey, leadToken);
  heldLeadRef.current = false;
  const mayLead = () => mayLeadSize(leadKey, leadToken);

  /*
   * May this pane take the shared size without being asked to?
   *
   * The passive test, for the moments the browser reports on its own — the
   * window regaining focus, a pane becoming the active stage, the grid
   * settling after a maximize. A window that does not hold focus is not the
   * one the user is reading, so it must not pull the agent's screen over to
   * its own dimensions.
   *
   * `document.hidden` is deliberately NOT consulted. The desktop shell can
   * report a window that is plainly on screen as hidden for minutes at a
   * time (2026-08-23), and gating ownership on it left the app unable to
   * take its own terminals back: a tab some tool had opened took the size,
   * and every click and every maximize in the app was answered with that
   * tab's geometry — the agent drawing into the top-left corner of a pane
   * that had just been made to fill the window (2026-08-25).
   */
  const viewerMayOwn = () =>
    mayLead() &&
    activeRef.current &&
    (typeof document === "undefined" ||
      typeof document.hasFocus !== "function" ||
      document.hasFocus());

  /**
   * Fit this pane to its tile and tell the agent behind it — right now.
   *
   * Only ever reached through `sendResize` below, which is what decides
   * WHEN "right now" is safe. Everything here reflows xterm's buffer, and a
   * reflow may not land in the middle of a parse (see RESIZE_PARSE_WAIT_MS).
   */
  const applyResize = (claimOwner: boolean) => {
    // A hidden pane measures 0x0 (maximizing another one hides this one), and
    // fitting to that would resize the PTY to zero columns — which permanently
    // wrecks the agent's full-screen drawing. Skip while not measurable; the
    // ResizeObserver fires again when the pane comes back. Re-checked here as
    // well as at the gate: a deferred fit runs a moment later, and the tile it
    // was asked for may be gone by then.
    if (s.disposed || !measurable()) return;
    // A pane off the stage never sizes its agent. A grid covered by the
    // maximized side panel is invisible but still laid out, in a tile the
    // panel narrowed: fitting there squeezed every agent behind it to a strip
    // (37 columns, measured) and its output stayed wrapped at that width in
    // the scrollback. Coming back on stage refits (the `active` effect).
    // The Verse window is the exception: the user is reading that host, so
    // the fit measures it (`presentedHost`) rather than the hidden tile.
    if (!activeRef.current && !s.presentedHost) return;
    // The pane draws at the READER'S text size, never one it picked itself.
    // An auto-shrink that walked this size down until the floor grid fit the
    // tile shipped and was rejected within hours (2026-08-11): it silently
    // overrode the toolbar's size on every narrow pane, which read as the
    // size controls being dead (see the floors' comment above). A stale size
    // can still linger on the terminal — a rebuild, a pane that shrank under
    // the old build — so the choice is restated before measuring.
    const desired = fontSizeRef.current;
    if (term.options.fontSize !== desired) {
      term.options.fontSize = desired;
      // A new size is a new glyph advance, and so a new floored fraction for
      // the canvas renderer to give back — same order as the fontSize effect.
      alignTerminalCells(term);
      clearTerminalTextureAtlas(term);
    }
    // Measured WITHOUT being applied yet: what the tile can show is a
    // PROPOSAL, and the floors above have the last word on it.
    let proposed: { cols: number; rows: number } | undefined;
    try {
      proposed = fit.proposeDimensions();
    } catch {
      return;
    }
    if (
      !proposed ||
      !Number.isFinite(proposed.cols) ||
      !Number.isFinite(proposed.rows)
    ) {
      return;
    }
    // The one size everyone gets — the grid here, the agent below, and it is
    // what the TILE measures. The two may never disagree: an agent laying
    // its lines out for a width its xterm does not have re-wraps every one
    // of them, and its cursor moves then land on rows that hold something
    // else (shredded one-word fragments, 2026-08-10). Only the absurd is
    // refused, which is all MIN_REAL_COLS is for now.
    const measured = {
      cols: Math.max(proposed.cols, MIN_REAL_COLS),
      rows: Math.max(proposed.rows, MIN_REAL_ROWS),
    };
    /*
     * The tile's own measurement is the size, full stop.
     *
     * Both axes follow the tile. A pane used to HOLD its columns below a
     * "workable" width and show a card instead of its terminal (2026-08-13,
     * against a coding CLI whose relative repaint wipes its own rows when it
     * is squeezed to ~13 columns). That card covered every pane of an
     * ordinary six-pane workspace at 56 columns and had to be clicked away on
     * each one, so the maintainer retired it (2026-08-18): the terminal is
     * shown at whatever width the tile has, the wizard says beforehand how
     * narrow that will be, and how many panes to open stays the user's call.
     */
    const size = measured;
    // A pane showing another viewer's geometry keeps showing it while its
    // own tile has not changed since it last asked. Fitting it back to the
    // tile here and then staying quiet (the request below would repeat one
    // already turned down) left xterm at the tile's width while the agent
    // went on drawing for the owner's: rows drawn over rows, word tails left
    // at the end of other lines, worst on returning to the IDE, where every
    // pane refits (2026-09-29). The geometry `onGeometry` applied is the one
    // the agent really draws for, so it is the one this grid must hold.
    if (
      !claimOwner &&
      s.displaced &&
      s.sentSize &&
      s.sentSize.cols === size.cols &&
      s.sentSize.rows === size.rows
    ) {
      return;
    }
    try {
      if (size.cols === proposed.cols && size.rows === proposed.rows) {
        fit.fit();
      } else if (term.cols !== size.cols || term.rows !== size.rows) {
        term.resize(size.cols, size.rows);
      }
    } catch {
      return;
    }
    // The grid now comes from a tile, so a reconnect may hand it over.
    s.mountMeasured = true;
    // Already delivered and unchanged: the fit above was the whole job.
    // Re-announcing a size makes the agent on the other end redraw its
    // entire screen, and a pane refits several times per settling layout.
    // A claim is exempt only while the pane does not hold the size — once
    // it does, a claim for the same measurement is the same repeat.
    if (
      (!claimOwner || s.owned) &&
      s.sentSize &&
      s.sentSize.cols === size.cols &&
      s.sentSize.rows === size.rows
    ) {
      return;
    }
    if (s.socket?.send({ t: claimOwner ? "claim" : "r", ...size })) {
      s.sentSize = size;
      if (claimOwner) {
        s.owned = true;
        s.displaced = false;
      }
    }
  };

  /** A fit this pane is holding back until its parser reaches a gap. */
  let deferredResize: { claimOwner: boolean } | null = null;
  /** The promise that a held-back fit happens even without a gap. */
  let deferredResizeTimer: number | undefined;

  const clearDeferredResize = () => {
    deferredResize = null;
    if (deferredResizeTimer === undefined) return;
    window.clearTimeout(deferredResizeTimer);
    deferredResizeTimer = undefined;
  };

  /**
   * Hold this fit until the parser is between chunks — or until the wait runs
   * out, whichever comes first (see RESIZE_PARSE_WAIT_MS).
   */
  const deferResize = (claimOwner: boolean) => {
    // Ownership is the stronger of the two requests: a claim carries a size
    // as well, so merging keeps it rather than letting an ordinary refit
    // arriving a millisecond later quietly drop the claim.
    deferredResize = {
      claimOwner: (deferredResize?.claimOwner ?? false) || claimOwner,
    };
    if (deferredResizeTimer !== undefined) return;
    deferredResizeTimer = window.setTimeout(() => {
      deferredResizeTimer = undefined;
      const pending = deferredResize;
      deferredResize = null;
      if (s.disposed || !pending) return;
      applyResize(pending.claimOwner);
    }, RESIZE_PARSE_WAIT_MS);
  };

  s.resumeResize = () => {
    const pending = deferredResize;
    if (!pending || s.disposed) return;
    clearDeferredResize();
    applyResize(pending.claimOwner);
  };

  /**
   * Fit this pane to its tile — at a moment when doing so cannot shred it.
   *
   * The gate, and the reason this is not simply `applyResize`. Reflowing
   * xterm's buffer while a write is still being parsed moves the rows the
   * rest of that stream is addressing, and an agent's TUI addresses rows by
   * relative moves — so the frame it was drawing is finished into the wrong
   * ones. See RESIZE_PARSE_WAIT_MS for what that looks like on screen and for
   * why the wait is bounded rather than indefinite.
   */
  const sendResize = (claimOwner = false) => {
    if (!measurable()) return;
    // Resizing a pane is the other half of the un-park story. Maximizing one,
    // dragging a seam, changing the font — all of them are a user opening up
    // a pane to READ it, and the pane it opens must not be a parked one still
    // holding its agent's screen.
    //
    // BEFORE the gate rather than after the fit, and that ordering is the
    // second half of this bug. Parked output was drawn for the size the pane
    // is LEAVING; written once the grid had already moved it painted an old
    // screen into a new geometry — the doubled rules and half-erased answers
    // the gate below exists to stop, arriving through the one path that used
    // to walk straight past it. Un-parked here, those bytes go in first and
    // the fit waits for them like any other write.
    revealIfOnScreen();
    if (s.parsing > 0) {
      deferResize(claimOwner);
      return;
    }
    applyResize(claimOwner);
  };
  resizeRef.current = sendResize;
  /**
   * Take the shared size if this window may, and refit either way.
   *
   * A refit that merely ASKS is answered, when another viewer holds the
   * pane, with that viewer's geometry — so a pane maximized in this window
   * would be fitted to its full tile and then resized straight back to the
   * strip some other window is showing. Every size change the user causes
   * here therefore claims rather than asks. The fallback matters just as
   * much: a pane that may not own (inactive, or in a window without focus)
   * still has to follow its tile, or the effects that route through this
   * would stop refitting exactly the panes that are not in front.
   */
  const claimResize = () => sendResize(viewerMayOwn());
  claimResizeRef.current = claimResize;
  // The Verse takeover borrows this xterm: the element itself moves into the
  // window, so clicks and keystrokes hit it with no forwarding. FitAddon
  // measures term.element's parent, which is that window while it is borrowed.
  let presentedWatch: ResizeObserver | null = null;
  let presentedTimer: number | undefined;
  let releasePresentedExtras = () => {};
  let releasePresentedRenderer = () => {};
  const releasePresented = () => {
    if (!s.presentedHost) return;
    if (presentedTimer !== undefined) window.clearTimeout(presentedTimer);
    presentedTimer = undefined;
    presentedWatch?.disconnect();
    presentedWatch = null;
    s.presentedHost = null;
    releasePresentedRenderer();
    releasePresentedRenderer = () => {};
    releasePresentedExtras();
    releasePresentedExtras = () => {};
    const element = term.element;
    if (element && element.parentElement !== container && container.isConnected) container.appendChild(element);
    const box = container.getBoundingClientRect();
    const viewport = { width: window.innerWidth || 0, height: window.innerHeight || 0 };
    if (!boxOnScreen(box, viewport)) parkPane();
  };
  const unregisterPresent = registerTerminalPresenter(workspaceId ?? "", name, (host) => {
    releasePresented();
    s.presentedHost = host;
    const element = term.element;
    if (element && element.parentElement !== host) host.appendChild(element);
    // Before the flush below, so the bytes just released actually land on
    // the canvas and a late intersection entry cannot pause them again.
    releasePresentedRenderer = keepPresentedRendererAwake(term);
    attachTerminalBridge(host, {
      getSelection: () => term.getSelection(),
      paste: (text) => term.paste(text),
      focus: () => term.focus(),
      selectAll: () => term.selectAll(),
    });
    const disposeMouse = installMouseSelection(host, term, isMac);
    const disposeBrowse = installBrowseExit(host, term);
    releasePresentedExtras = () => {
      disposeMouse();
      disposeBrowse();
    };
    // Un-park even when the IDE tile is hidden. The window is what is on screen.
    showPane();
    if (typeof ResizeObserver !== "undefined") {
      presentedWatch = new ResizeObserver(() => {
        if (presentedTimer !== undefined) window.clearTimeout(presentedTimer);
        presentedTimer = window.setTimeout(() => {
          presentedTimer = undefined;
          // This window is the one the user is reading, so it takes the size.
          if (!s.presentedHost) return;
          wakePresentedRenderer(term);
          showPane();
          sendResize(true);
        }, 80);
      });
      presentedWatch.observe(host);
    }
    sendResize(true);
    if (term.rows > 0) term.refresh(0, term.rows - 1);
    return releasePresented;
  });
  /**
   * Make the agent paint its whole screen again at the size this pane holds:
   * one row short, then back, like the server's repaint nudge. An agent
   * answers a new size with a full redraw, and a size equal to the one it
   * has is no new size at all — hence the detour.
   *
   * For a pane returning to the stage (see RETURN_REPAINT_NUDGE_MS). It also
   * puts the agent back on this pane's size when it drifted away while the
   * pane was hidden, which a plain refit cannot do: a refit to an unchanged
   * tile is deliberately silent (see `applyResize`).
   */
  const repaintOnReturn = () => {
    // The grid this pane HOLDS, never the size it last asked for. The two
    // differ while the pane follows a geometry the server chose (see
    // `onGeometry`), and a nudge carrying the old request was granted
    // silently: the agent went back to the tile's width while xterm stayed
    // at the followed one, so every line it drew wrapped into word
    // fragments down the pane's edge (reported 2026-10-06, after switching
    // from the thread layout back to the grid).
    const size = s.sentSize ? { cols: term.cols, rows: term.rows } : null;
    if (s.disposed || !size || !s.socket) return;
    // Coming back on stage is a change made in THIS window (see `returnResize`).
    const claimOwner = activeRef.current && mayLead();
    const kind = claimOwner ? "claim" : "r";
    const shorter = Math.max(MIN_REAL_ROWS, size.rows - 1);
    if (shorter === size.rows) return;
    if (!s.socket.send({ t: kind, cols: size.cols, rows: shorter })) return;
    window.setTimeout(() => {
      if (s.disposed) return;
      // A refit may have landed during the wait; give back the grid as it is now.
      const back = { cols: term.cols, rows: term.rows };
      if (!s.socket?.send({ t: kind, cols: back.cols, rows: back.rows })) return;
      // What the agent was last asked for, so the next refit of the tile is
      // compared against it and not against an older request.
      s.sentSize = back;
      if (claimOwner) {
        s.owned = true;
        s.displaced = false;
      }
    }, RETURN_REPAINT_NUDGE_MS);
  };
  repaintOnReturnRef.current = repaintOnReturn;
  /**
   * Refit a pane that comes back on stage, taking the size if this window may.
   *
   * A layout switch, a workspace switch or leaving the Verse is something the
   * user did in this window, so it claims like a gesture in the pane does —
   * without asking `document.hasFocus()`, whose answer the desktop shell lets
   * lag (see `viewerMayOwn`). Only asking left a pane that had followed
   * another geometry while it was hidden at that geometry: `applyResize`
   * stays silent for a tile it already requested.
   */
  const returnResize = () => sendResize(activeRef.current && mayLead());
  returnResizeRef.current = returnResize;
  /**
   * The same, on the strength of a gesture INSIDE this pane.
   *
   * A pointer pressed on the pane is proof enough that this is the window in
   * front of the user, whatever `document.hasFocus()` has to say — the
   * desktop shell's answer to that question can lag the truth, and a click
   * that is not allowed to take the pane back leaves the user with no way
   * to do so at all.
   *
   * It also makes this viewer the pane's lead in this window, so the view
   * the user just pressed keeps the size instead of another viewer of the
   * same pane here taking it straight back on the next mouse move.
   */
  const takeOwnership = () => {
    if (!activeRef.current) return;
    takeSizeLead(leadKey, leadToken);
    sendResize(true);
  };
  takeOwnershipRef.current = takeOwnership;
  /**
   * Any gesture in this WINDOW takes back every pane another viewer sized.
   *
   * A click inside one pane only ever repaired that pane, and the window
   * `focus` event is exactly what the desktop shell does not reliably
   * deliver. So a browser tab some tool had opened on the same workspace
   * left all eight panes of the app drawing in the tab's geometry — text
   * cut mid-word on the right, rows of empty space below the agent's
   * status line (reported 2026-09-29) — until each pane was clicked.
   * Pointer or keyboard activity here is proof the user is in front of this
   * window. Only a displaced pane reacts, at most once per
   * {@link GESTURE_RECLAIM_MS}, so an owning pane pays one boolean check
   * and two windows being used at once cannot trade the size on every
   * mouse move.
   */
  let lastGestureReclaimAt = 0;
  const reclaimOnGesture = () => {
    // Another viewer of this pane in this very window holds it: the gesture
    // is as much that viewer's as this one's, and taking the size back here
    // is what made the two trade it forever.
    if (!s.displaced || !activeRef.current || !mayLead()) return;
    const now = Date.now();
    if (now - lastGestureReclaimAt < GESTURE_RECLAIM_MS) return;
    lastGestureReclaimAt = now;
    sendResize(true);
  };
  window.addEventListener("pointermove", reclaimOnGesture, { passive: true });
  window.addEventListener("pointerdown", reclaimOnGesture, true);
  window.addEventListener("keydown", reclaimOnGesture, true);
  /*
   * The lead viewer went away (the office's pane window closed): the size is
   * this window's to set again, and this pane's tile is what it shows. Its
   * own refits stayed quiet while it only watched, so nothing else would
   * hand the agent this tile's size back.
   */
  const stopLeadWatch = onSizeLeadReleased(leadKey, () => {
    if (s.disposed) return;
    // A claim, not a request: the lead that just left was THIS window's,
    // closed from here, and a request would be answered with the size the
    // departed viewer chose — whatever the desktop shell says about focus.
    sendResize(activeRef.current);
  });
  return { leadKey, leadToken, viewerMayOwn, clearDeferredResize, sendResize, claimResize, releasePresented, unregisterPresent, reclaimOnGesture, stopLeadWatch };
}
