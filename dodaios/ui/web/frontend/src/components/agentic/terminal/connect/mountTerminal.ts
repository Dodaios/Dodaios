import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { WebLinksAddon } from "@xterm/addon-web-links";
import { Unicode11Addon } from "@xterm/addon-unicode11";
import { MINIMUM_CONTRAST_RATIO, themeFor } from "../../terminalThemes";
import { attachTerminalRenderer } from "../../terminalRenderer";
import { attachTerminalBridge } from "@/lib/editActions";
import { robustCopy, robustPaste } from "@/lib/clipboard";
import { TERMINAL_FONT_STACK, alignTerminalCells, terminalFontWeights } from "@/lib/terminalFont";
import { createTerminalLinkActivator, createTerminalOscLinkHandler, TerminalPathLinksAddon } from "@/lib/terminalLinks";
import { installPasteBridge } from "../../terminalPaste";
import { installCopyBridge } from "../../terminalCopy";
import { createKeyEventChain } from "../../terminalKeyChain";
import { registerLiveTerminal } from "@/lib/liveTerminals";
import { installNewlineBridge } from "../../terminalNewline";
import { installQuerySuppression } from "../../terminalQueries";
import { installSynchronizedOutput } from "../../terminalSynchronizedOutput";
import { captureWheelForTerminalHistory } from "../../terminalScrollSurface";
import { installMouseSelection } from "../../terminalMouseSelection";
import { installPromptSelectionBridge } from "../../terminalPromptSelection";
import { installBrowseExit } from "../../terminalBrowseExit";
import { translate } from "@/i18n";
import { MIN_REAL_COLS, MIN_REAL_ROWS, windowCollapsed } from "../paneShared";
import type { PaneState, PanePorts } from "./paneRuntime";

export function mountTerminal(p: PanePorts, s: PaneState) {
  const { name, workspaceId, container, onAttachErrorRef, fontSizeRef, appearanceRef, activeRef, focusedRef, termRef, fitRef, setPainted, setTailReady, setTerminalEpoch, replayCurtainRef, replayGenerationRef, replayRevealFrameRef } = p;
  // A restart builds a brand-new terminal on a blank screen, so the pane owes
  // the user the same "it is coming up" answer it owed on its first mount.
  setPainted(false);
  // And it must not inherit a curtain: a rebuild can tear the old terminal
  // down between a replay dropping the curtain and its write callback (see
  // `replayToPane`), which would leave the new terminal invisible with
  // nothing left to lift it.
  replayGenerationRef.current += 1;
  replayCurtainRef.current = false;
  if (replayRevealFrameRef.current !== undefined) {
    cancelAnimationFrame(replayRevealFrameRef.current);
    replayRevealFrameRef.current = undefined;
  }
  setTailReady(activeRef.current);

  const linkOptions = {
    workspaceId,
    onError: (message: string) => onAttachErrorRef.current?.(message),
    hasSelection: (): boolean => term.hasSelection(),
  };
  const activateLink = createTerminalLinkActivator(linkOptions);
  const term: Terminal = new Terminal({
    convertEol: false,
    // A dark pane keeps the canvas clear so the shared section glass and the
    // desktop artwork show through. A light pane is opaque: xterm rasterises
    // glyphs on a transparent canvas with greyscale anti-aliasing only, and
    // dark ink on paper drawn that way reads thin and grey — on a 4K screen
    // at 100 % scaling, barely legible (maintainer, 2026-10-01). On an
    // opaque ground the glyph atlas gets the system's subpixel smoothing.
    allowTransparency: appearanceRef.current !== "light",
    // A CLI configured for the other ground paints truecolor a palette can
    // never remap — dark-theme white text into a light pane. This floor
    // nudges any unreadable foreground toward legibility; the theme's
    // transparent background carries the ground RGB it measures against.
    minimumContrastRatio: MINIMUM_CONTRAST_RATIO,
    // Shared with the measurement in ./../../lib/terminalFont: a pane that
    // measured a different stack from the one it draws with is the bug that
    // module exists to prevent.
    fontFamily: TERMINAL_FONT_STACK,
    fontSize: fontSizeRef.current,
    // Medium body text, SemiBold on a light pane — see TERMINAL_FONT_WEIGHT
    // and TERMINAL_FONT_WEIGHT_LIGHT for why Regular reads thin and grey
    // under the WebGL renderer next to a native terminal.
    fontWeight: terminalFontWeights(appearanceRef.current).body,
    fontWeightBold: terminalFontWeights(appearanceRef.current).bold,
    // The font's own line height, like a standalone terminal. JetBrains Mono
    // already carries 1.32em of leading; at 1.2 on top a row was ~1.6em tall,
    // so a pane showed large text gaps between small glyphs. At 1.0 the larger
    // default size (./paneFont) fits the same number of rows as before.
    lineHeight: 1.0,
    // Zero, not 0.2: extra tracking is added per cell, so a box-drawing frame
    // and the text under it accumulate different sub-pixel offsets and the
    // frame visibly bends. Monospace legibility comes from the line height.
    letterSpacing: 0,
    // Only the focused pane blinks — see the `focused` effect above.
    cursorBlink: focusedRef.current,
    cursorStyle: "bar",
    // xterm's default for a terminal without keyboard focus is a hollow box.
    // On a wall of panes that box sat in every idle prompt and read as a
    // stray glyph; the agent's own prompt already marks where input goes.
    cursorInactiveStyle: "none",
    // How far back a pane can be scrolled. The server keeps the same number
    // of rows for a pane that is joined again (`HISTORY_LIMIT_ROWS` in
    // dodaios/agentic_ide/scrollback.py; a backend test holds the two equal).
    scrollback: 10000,
    // Required by the Unicode 11 width provider below.
    allowProposedApi: true,
    // Instant scrolling: an agent that redraws a live status line while
    // animating a scroll leaves visible tearing.
    smoothScrollDuration: 0,
    // Our own activator decides what a click opens (./../../lib/terminalLinks).
    // xterm otherwise treats an ordinary click on an OSC-8 link as
    // navigation and shows a native warning dialog inside the desktop WebView.
    linkHandler: createTerminalOscLinkHandler(linkOptions),
    // Lets Option force a selection on macOS while a CLI has mouse tracking
    // on — the chord ./terminalMouseSelection marks every plain press with.
    macOptionClickForcesSelection: true,
    // Windows only. ConPTY re-emits and re-wraps lines in a way a POSIX pty
    // never does; without telling xterm which backend it is talking to, those
    // re-emitted lines pile up as duplicated, half-overwritten rows. Harmless
    // to declare on other platforms — the pty there simply never triggers it,
    // and the value is derived from the browser rather than assumed.
    windowsPty: /windows/i.test(navigator.userAgent)
      ? { backend: "conpty" as const }
      : undefined,
    theme: themeFor(appearanceRef.current),
  });
  // Before anything is written to this terminal: the agent's CLI asks what
  // its terminal is and which colours it draws on within milliseconds of
  // starting, and an answer produced HERE has to cross the socket twice
  // before reaching it — too late, and then visible as junk in its prompt.
  // The backend answers those instead. See ./terminalQueries.
  const disposeQuerySuppression = installQuerySuppression(term.parser);
  const fit = new FitAddon();
  term.loadAddon(fit);
  term.loadAddon(new WebLinksAddon(activateLink));
  if (workspaceId) {
    term.loadAddon(new TerminalPathLinksAddon(activateLink));
  }
  // Character WIDTH, not appearance: without this xterm measures emoji and
  // many box/symbol glyphs as one cell while the agent on the other side
  // counted two, and every such glyph shifts the rest of the line one column
  // left. That is the "the frames are broken" symptom.
  try {
    const unicode = new Unicode11Addon();
    term.loadAddon(unicode);
    term.unicode.activeVersion = "11";
  } catch {
    /* proposed API unavailable in this build — widths stay at Unicode 6 */
  }
  // Align before the renderer joins the shared glyph atlas and before the
  // first fit/handshake. Correcting spacing afterwards changes the grid and
  // invalidates every existing pane's cache just to open an empty terminal.
  alignTerminalCells(term);
  term.open(container);
  // The ship's monitors draw this pane from the same buffer; see lib/liveTerminals.
  const unregisterLive = registerLiveTerminal(workspaceId ?? "", name, term);
  // The wheel always moves xterm's own history, even while a normal-buffer
  // CLI has negotiated mouse tracking — otherwise scrolling only "works"
  // when the CLI feels like it, which is the per-provider inconsistency the
  // scroll rebuild removed. See captureWheelForTerminalHistory.
  term.attachCustomWheelEventHandler(captureWheelForTerminalHistory(term));
  // WebGL where the page can afford it, the 2D canvas otherwise, and the DOM
  // renderer as the last resort — never the DOM renderer by choice: a coding
  // agent's TUI redraws its prompt box on every keystroke, and per-cell DOM
  // elements both lag and land on fractional pixel offsets. Loaded AFTER
  // open() because it needs the mounted element. See ./terminalRenderer for
  // why the canvas renderer alone froze a wall of streaming panes.
  const renderer = attachTerminalRenderer(term, () => {
    if (s.disposed) return;
    // The fallback renderer starts on an empty surface.
    term.refresh(0, term.rows - 1);
  });
  const synchronizedOutput = installSynchronizedOutput(term);
  termRef.current = term;
  fitRef.current = fit;
  setTerminalEpoch((current) => current + 1);
  // Let the app-wide right-click menu reach this terminal. It cannot use the
  // browser selection here — the canvas renderer above paints the text, so
  // there is no selectable DOM to read — and it must paste through xterm so
  // the sequence is bracketed rather than typed key by key.
  attachTerminalBridge(container, {
    getSelection: () => term.getSelection(),
    paste: (text) => term.paste(text),
    focus: () => term.focus(),
    selectAll: () => term.selectAll(),
  });
  // The keyboard bridges below claim keystrokes, and xterm holds exactly ONE
  // custom key handler — attaching them directly would leave only the last
  // one working, silently. See ./terminalKeyChain.
  const keys = createKeyEventChain(term);
  const isMac = /mac|iphone|ipad/i.test(navigator.userAgent);
  // A plain left-button drag selects text even while the agent's CLI has
  // mouse tracking on, which every coding agent negotiates at start-up.
  const disposeMouseSelection = installMouseSelection(container, term, isMac);
  const disposePromptSelection = installPromptSelectionBridge(term, keys.add, isMac);
  const disposeBrowseExit = installBrowseExit(container, term);
  // The desktop IDE reserves its platform copy chord for copying. In
  // particular, an unselected Ctrl+C on Windows/Linux must not reach Codex
  // as `^C`, where it cancels the current turn or exits the pane.
  const disposeCopyBridge = installCopyBridge(
    {
      attachCustomKeyEventHandler: keys.add,
      getSelection: () => term.getSelection(),
      focus: () => term.focus(),
    },
    {
      copy: robustCopy,
      isMac,
      onUnavailable: () =>
        onAttachErrorRef.current?.(
          translate("agentic_grid.pane.copy_unavailable"),
        ),
    },
  );
  // Make Ctrl+V / Cmd+V paste. Left to itself xterm reads the chord as the
  // terminal control code ^V and CANCELS the keystroke, so the browser never
  // runs its own paste and nothing arrives at all — see ./terminalPaste.
  const disposePasteBridge = installPasteBridge(
    {
      attachCustomKeyEventHandler: keys.add,
      paste: (text) => term.paste(text),
    },
    container,
    {
      readClipboard: robustPaste,
      isMac,
      onUnavailable: () =>
        onAttachErrorRef.current?.(
          translate("agentic_grid.pane.paste_unavailable"),
        ),
    },
  );
  // Make Shift+Enter (and Option/Cmd+Enter) break the line instead of sending
  // the half-written instruction — see ./terminalNewline.
  const disposeNewlineBridge = installNewlineBridge({
    attachCustomKeyEventHandler: keys.add,
    input: (data) => term.input(data),
  });
  /**
   * Set while the Verse window is showing this xterm. Fit then measures that
   * window, and the hidden IDE tile must not park the pane or resize it to 0.
   */
  s.presentedHost = null;
  /** Is this pane's tile something that can honestly be measured right now? */
  const measurable = () => {
    const box = s.presentedHost ?? container;
    return !windowCollapsed() && box.clientWidth >= 8 && box.clientHeight >= 8;
  };
  /** Did the grid below come from the tile, or is it still the constructed default? */
  s.mountMeasured = false;

  try {
    // Taken BEFORE the handshake below reads the terminal's geometry — so
    // the grid this pane draws on and the size its agent is spawned at are
    // the same thing from the very first byte.
    //
    // Only from a tile that HAS a size. A pane that mounts hidden — the
    // chat stage hides every cell and draws the staged pane's transcript
    // over the canvas — is a display:none box, and the fit addon answers
    // that with its own minimum rather than with nothing. Clamped to the
    // floors below, that became a 10x4 terminal, and the handshake then
    // spawned the agent at exactly that (T11, 2026-08-27): a CLI drawing
    // its input line ten columns wide, where a prompt written into it
    // could never be seen arriving and every message was reported as
    // unconfirmed. Unmeasured, the terminal keeps its constructed 80x24
    // and the agent starts at a size it can draw in; the first real
    // measurement follows from `sendResize` the moment the tile is shown.
    const proposed = measurable() ? fit.proposeDimensions() : undefined;
    if (
      proposed &&
      Number.isFinite(proposed.cols) &&
      Number.isFinite(proposed.rows)
    ) {
      // The tile's own measurement, and only the absurd is refused (see
      // MIN_REAL_COLS). `fit()` rather than a resize to the same numbers:
      // it is what xterm offers and it keeps the renderer's own bookkeeping
      // in step.
      if (proposed.cols >= MIN_REAL_COLS && proposed.rows >= MIN_REAL_ROWS) {
        fit.fit();
      } else {
        term.resize(
          Math.max(proposed.cols, MIN_REAL_COLS),
          Math.max(proposed.rows, MIN_REAL_ROWS),
        );
      }
      s.mountMeasured = true;
    }
  } catch {
    /* not measured yet — the ResizeObserver below will fit */
  }
  /*
   * Did this socket's handshake go out without a size (`UNMEASURED_SIZE`),
   * with the server's report of the agent's real size still to come?
   *
   * The server replays the agent's screen BEFORE it sends that report, and
   * the screen is addressed by row at the agent's size. Parsed into this
   * grid first — xterm's constructed 80x24 when the pane mounted hidden or
   * in a minimized window — every row below the 24th landed on the last one
   * (the status line written over the prompt box), and the report then grew
   * the grid with blank rows underneath. Nothing repaired it: the PTY
   * already had the size the pane went on to ask for, so the agent was never
   * asked to paint again (reported 2026-10-06, the window reloading while
   * the IDE showed the thread layout). So output is held until the report
   * arrives and drawn after the grid has taken it (see `onGeometry`).
   */
  s.awaitingSizeReport = false;
  return { term, disposeQuerySuppression, fit, unregisterLive, renderer, synchronizedOutput, isMac, disposeMouseSelection, disposePromptSelection, disposeBrowseExit, disposeCopyBridge, disposePasteBridge, disposeNewlineBridge, measurable };
}
