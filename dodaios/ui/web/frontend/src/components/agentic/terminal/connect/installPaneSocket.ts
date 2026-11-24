import { describeExit, explainExit } from "../../paneExit";
import { openPaneSocket } from "../../paneSocket";
import { translate } from "@/i18n";
import { RECEIPT_MAX_AGE_MS, MIN_REAL_COLS, MIN_REAL_ROWS, UNMEASURED_SIZE } from "../paneShared";
import type { PaneState, PanePorts } from "./paneRuntime";
import type { mountTerminal } from "./mountTerminal";
import type { installPaneOutput } from "./installPaneOutput";
import type { installPaneSizing } from "./installPaneSizing";

export function installPaneSocket(p: PanePorts, s: PaneState, a: ReturnType<typeof mountTerminal> & ReturnType<typeof installPaneOutput> & ReturnType<typeof installPaneSizing>) {
  const { name, workspaceId, displayName, appearanceRef, activeRef, focusedRef, setReceipt, flashDelivered } = p;
  const { term, fit, measurable, report, writeToTerminal, flushHeld, showPane, writeToPane, replayToPane, viewerMayOwn, sendResize } = a;
  /*
   * The size this socket connects with. The tile's own measurement when there
   * was one: the mount-time fit above already clamped the grid to the floors,
   * so the terminal's geometry is safe to hand over as-is. When that fit
   * could not run at all — a grid cell still mid-layout, a pane mounted
   * hidden on the chat stage — the terminal still holds what it was
   * constructed with, and THAT must not go out as if a tile had measured it:
   * a running agent would be re-wrapped for 80 columns no tile has, and again
   * for the real ones a moment later (ConPTY re-flows the whole screen on
   * each). `UNMEASURED_SIZE` says so on the wire instead; the real size
   * follows from `onOpen`'s fit as soon as the cell settles.
   *
   * Read on EVERY connect, not once at mount. The socket reconnects on its
   * own (a backend restart, sleep and wake), and a handshake carrying the
   * size the pane had when it mounted resized the agent to a grid the pane
   * had long left — its frame drawn for that width into this one, until the
   * next repaint happened to come (2026-09-29).
   */
  let openedWithClaim = viewerMayOwn();
  const connectSize = () => {
    // Without a size the server answers with the agent's (see
    // `awaitingSizeReport`), and output waits for that answer.
    s.awaitingSizeReport = true;
    if (!s.mountMeasured || !measurable()) return UNMEASURED_SIZE;
    let proposed: { cols: number; rows: number } | undefined;
    try {
      proposed = fit.proposeDimensions();
    } catch {
      proposed = undefined;
    }
    const cols = proposed?.cols ?? term.cols;
    const rows = proposed?.rows ?? term.rows;
    if (!Number.isFinite(cols) || !Number.isFinite(rows)) return UNMEASURED_SIZE;
    s.awaitingSizeReport = false;
    // The same floors `applyResize` puts on the grid.
    return {
      cols: Math.max(cols, MIN_REAL_COLS),
      rows: Math.max(rows, MIN_REAL_ROWS),
    };
  };
  s.socket = openPaneSocket(
    {
      name,
      workspaceId,
      get cols() {
        return connectSize().cols;
      },
      get rows() {
        return connectSize().rows;
      },
      appearance: appearanceRef.current,
      // Decided per connect as well, and remembered: `onOpen` settles
      // ownership from what THIS handshake claimed.
      get claimOwner() {
        openedWithClaim = viewerMayOwn();
        return openedWithClaim;
      },
    },
    {
      onOpen: () => {
        report("connecting");
        // A fresh socket has been told nothing about this pane, whatever the
        // one before it heard — so the size goes out again unconditionally.
        // This is also what hands over a size that was measured while the
        // pane was unreachable.
        s.sentSize = null;
        // Ownership is settled by the handshake: a socket opened with a
        // claim holds the size from its first byte, one opened without is a
        // watcher until something in this window takes the pane.
        s.owned = openedWithClaim;
        // The spawn used a best-effort size (the mount-time fit usually runs
        // before the grid cell is measured), and resizes sent while the socket
        // was connecting were dropped — without this the agent's full-screen
        // TUI keeps drawing at the wrong width and looks clipped.
        sendResize();
        requestAnimationFrame(() => sendResize());
      },
      onOutput: (text) => writeToPane(text),
      onReplay: (text, awaitRepaint) => replayToPane(text, awaitRepaint),
      /**
       * The agent is in a different size than this pane asked for — follow it.
       *
       * `applyResize` reflows xterm the instant it measures the tile, before
       * anything has agreed to that size, and the server is allowed to say no
       * (a tile under the floor keeps the working geometry, a displaced viewer
       * is ignored). Nothing used to reconcile the two afterwards — the wire
       * had no way to say "not granted" — so a refusal left this grid and the
       * agent's permanently different widths, and the agent's relative cursor
       * moves then finished its repaints into rows holding other text. That is
       * the doubled, character-by-character text a narrow pane showed
       * (2026-08-11): not a renderer fault, two screens in one grid.
       *
       * `sentSize` is deliberately NOT updated. It records what was ASKED,
       * and that is what stops this from oscillating: the same tile measured
       * again matches it and is never re-sent, so a pane whose size is refused
       * asks once and then stays quiet — while a tile that really changes
       * still speaks up. Following the agent also repairs what is already on
       * screen, because that content was drawn for this geometry all along.
       */
      onGeometry: ({ cols, rows }) => {
        if (s.disposed) return;
        // Whatever the numbers, the agent is in a size this pane did not
        // ask for — refused, or chosen by another window. The next gesture
        // here claims instead of repeating a request that was turned down.
        s.owned = false;
        const applyGeometry = () => {
          if (s.disposed || (term.cols === cols && term.rows === rows)) return;
          s.displaced = true;
          try {
            term.resize(cols, rows);
          } catch {
            /* the terminal is being torn down — nothing left to reconcile */
          }
        };
        // The report a handshake without a size was waiting for. What this
        // pane holds — the replayed screen and anything after it — was
        // drawn at THIS size, so the grid takes it first (see
        // `awaitingSizeReport`). Something already parsing was flushed
        // early by the hold's deadline; it keeps the ordinary order below.
        if (s.awaitingSizeReport) {
          s.awaitingSizeReport = false;
          if (s.parsing === 0) {
            applyGeometry();
            flushHeld();
            return;
          }
        }
        // A size frame belongs BETWEEN the output before and after it.
        // xterm parses writes asynchronously, and a hidden workspace can
        // still hold older output outside xterm. Resizing immediately made
        // those bytes wrap at the new width, moving status rows and leaving
        // gaps above a bottom-anchored prompt. Drain the old bytes first,
        // then insert a parser barrier before any new-geometry output.
        // Do not coalesce size frames or skip equal sizes here: an earlier
        // queued geometry may still change the grid before this one runs.
        flushHeld();
        if (s.parsing > 0) writeToTerminal("", applyGeometry);
        else applyGeometry();
      },
      /**
       * A prompt just landed in this pane — make that impossible to miss.
       *
       * Two things, and the order matters. The pane is un-parked FIRST:
       * whatever the observer believes, output held back now is output the
       * user will not see while they are looking straight at the receipt
       * telling them it arrived. Only then does it flash, which is the part
       * that is merely nice.
       *
       * It used to scroll the pane into the viewport as well, because a
       * receipt drawn on a pane two screens down is no better than no
       * receipt. There is no such pane any more — the workspace is one
       * screenful by rule (see the header of ./layout) — and the call would
       * now find the app's own scroller instead and move the whole section
       * under the user.
       *
       * None of this depends on the agent echoing anything, which is the
       * whole point: this path is what remains true when the terminal is a
       * black rectangle.
       */
      onPrompt: (delivery) => {
        if (s.disposed) return;
        if (activeRef.current) showPane();
        setReceipt(delivery);
        flashDelivered(2_000);
      },
      onReady: ({ resumed, reattached, lastPrompt }) => {
        s.troubleShown = null;
        s.troubleText = "";
        // What this pane was told BEFORE this socket existed. A reload, a
        // reconnect or a second window opened afterwards would otherwise
        // show no receipt at all for a prompt that really was delivered —
        // and that viewer is exactly the one with reason to doubt it.
        //
        // Bounded by age, because "durable" and "permanent" are different
        // requirements. The receipt answers a question that is asked in the
        // minutes after a delivery ("did that actually go?"); re-raising
        // yesterday's every time a workspace is reopened would train the
        // user to close it unread, which is how the next real one gets
        // missed. Older deliveries stay readable on demand — the pane's
        // state keeps them, and `GET /terminals/{name}/prompt` returns the
        // text in full.
        if (
          lastPrompt?.at !== null &&
          lastPrompt !== null &&
          Date.now() - lastPrompt.at * 1000 < RECEIPT_MAX_AGE_MS
        ) {
          setReceipt(lastPrompt);
        }
        // Say which of THREE things happened. They look identical on screen and
        // only differ when it matters: an agent that never stopped still holds
        // everything, a resumed one re-read its history, and a fresh one will
        // give a blank stare to the first follow-up question.
        report(
          "live",
          reattached
            ? translate("agentic_grid.pane.ready_reattached")
            : resumed
              ? translate("agentic_grid.pane.ready_resumed")
              : translate("agentic_grid.pane.ready_fresh"),
        );
        if (
          activeRef.current &&
          focusedRef.current &&
          (document.activeElement === null ||
            document.activeElement === document.body)
        ) {
          term.focus();
        }
      },
      onExit: (code) => {
        report("exited", explainExit(code));
        writeToPane(
          `\r\n\x1b[?25h\x1b[33m${describeExit(displayName, code)}\x1b[0m\r\n`,
        );
      },
      onTrouble: (message, retrying) => {
        if (s.disposed) return;
        // A scheduled retry means the pane is not dead yet. Calling it "error"
        // there is what left a whole grid painted red over a backend that was
        // merely restarting.
        report(retrying ? "connecting" : "error", message);
        const kind = retrying ? "retrying" : "unreachable";
        const repeats = s.troubleShown === kind || message === s.troubleText;
        s.troubleShown = kind;
        // The status was reported either way — only the terminal write is
        // skipped. The notice row keeps the sentence on screen (see
        // `PaneNotice`), so nothing is lost by not repeating it.
        if (repeats) return;
        s.troubleText = message;
        writeToPane(
          `\r\n\x1b[${retrying ? "33" : "31"}m[${message}]\x1b[0m\r\n`,
        );
      },
    },
  );

  term.onData((data) => {
    s.socket?.send({ t: "i", d: data });
  });
}
