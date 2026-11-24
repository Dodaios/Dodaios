import { Terminal } from "@xterm/xterm";
import { type TerminalAppearance } from "../terminalThemes";
import { type SplitAgentChoice } from "../AgentPicker";
import type { RecapReason, RecapSource } from "@/lib/agenticIdeApi";


/**
 * How old a delivery may be and still raise its receipt on a fresh connection.
 *
 * Only applies to the receipt recovered from the HANDSHAKE — a prompt arriving
 * live always shows one. Half an hour comfortably covers "I looked away and
 * came back" while keeping a reopened workspace from re-announcing deliveries
 * the user long since watched play out.
 */
export const RECEIPT_MAX_AGE_MS = 30 * 60 * 1000;

export type PreservedTerminalViewport = {
  line: number;
  followsTail: boolean;
};

/** Remember what the reader was looking at before a pane is rebuilt or hidden. */
export function captureTerminalViewport(
  term: Terminal | null,
): PreservedTerminalViewport | null {
  if (!term) return null;
  const buffer = term.buffer.active;
  return {
    line: buffer.viewportY,
    // Alternate-screen applications do not own scrollback. Their only honest
    // position is the live screen, just like a normal buffer already at its end.
    followsTail: buffer.type !== "normal" || buffer.viewportY >= buffer.baseY,
  };
}

/** Put a pane back where the reader left it, without following new output. */
export function restoreTerminalViewport(
  term: Terminal | null,
  viewport: PreservedTerminalViewport | null,
) {
  if (!term) return;
  const buffer = term.buffer.active;
  if (!viewport || viewport.followsTail || buffer.type !== "normal") {
    term.scrollToBottom();
    return;
  }
  term.scrollToLine(Math.min(viewport.line, buffer.baseY));
}

/**
 * How long a rebuilding pane must see NO further output before it is revealed.
 *
 * A replay is only HALF of a rebuild. Handing the recorded bytes over cannot
 * repair a tail that lost its opening frame, nor one whose cursor moves belong
 * to another geometry — so the server follows it by asking the agent to paint
 * its interface again, with a one-row window-size change held for 80 ms and put
 * back (`SessionRegistry._nudge_repaint`). That answer is a SECOND full screen
 * and it lands AFTER the replay has parsed, which is where the pane used to be
 * revealed: the repaint then played out in front of the reader (reported
 * 2026-08-09 — every switch onto a Codex pane opened on the top of its history
 * and raced down, with the replay curtain already in place and working).
 *
 * Only a normal-buffer CLI shows it. An alternate-screen agent (Claude Code)
 * repaints over itself, so nothing travels and nothing is there to hide.
 *
 * So the reveal waits for the pane's output to go QUIET rather than for one
 * write to finish. Comfortably past the nudge's own 80 ms plus a loopback round
 * trip, and short enough that nobody can time it.
 */
export const REBUILD_QUIET_MS = 140;

/**
 * The longest a pane may stay hidden while it rebuilds, however talkative.
 *
 * The quiet window assumes the redraw ENDS. An agent midway through streaming
 * an answer never goes quiet at all, and waiting on it would trade a visible
 * scroll for a pane that simply does not come back. Past this the pane is shown
 * mid-stream — which is what every other terminal in the app looks like while
 * an agent is talking.
 */
export const REBUILD_SETTLE_MAX_MS = 450;

/**
 * How long a pane coming back on screen holds its agent one row short before
 * giving the height back — the same window the server's own repaint nudge uses
 * (`REPAINT_NUDGE_S` in dodaios/agentic_ide/session.py).
 *
 * A pane in a workspace the IDE keeps warm (./RetainedWorkspaceGrid) is never
 * rebuilt when the user switches back to it, so it never gets the replay and
 * repaint a freshly mounted pane gets. Whatever went wrong while it was hidden
 * stayed on screen: the agent drawing for fewer rows than the tile, its prompt
 * and status line halfway up the pane with empty rows below (reported
 * 2026-10-03), or a band of blank rows through the middle of its output. The
 * nudge asks the agent for one whole new screen at the size the pane really
 * has, behind the same curtain a stage switch already raises.
 */
export const RETURN_REPAINT_NUDGE_MS = 80;

/**
 * How long a rebuild may wait for a repaint the server has promised.
 *
 * A replay whose front was cut (or that belongs to another geometry) cannot
 * rebuild a full-screen agent's interface; the server says so on the replay
 * frame and asks the agent to repaint, and that repaint opens with a
 * whole-screen erase. Revealing on quiet alone showed the broken tail
 * whenever the agent answered late — a busy Claude Code lets a repaint request
 * pass and the server repeats it half a second later — which after a bundle
 * reload, with every pane rebuilding at once, read as terminals badly
 * formatted for about a second (reported 2026-09-29). So such a rebuild waits
 * for the erase, bounded by this, and still under {@link CURTAIN_MAX_MS}.
 */
export const REPAINT_WAIT_MAX_MS = 1_400;

/**
 * The longest an active pane's surface may stay behind a curtain, full stop.
 *
 * Every curtain in this file is lifted by a chain — a write callback, a
 * generation check, a settle timer, then an animation frame — and every link
 * can be dropped: a newer generation supersedes the reveal without taking the
 * curtain down itself, and a WebView that believes its window is hidden stops
 * delivering animation frames altogether (see `viewerMayOwn` for how long it
 * can believe that). Either way the pane was left an empty black rectangle
 * with a green "live" dot above it until something unrelated rebuilt it
 * (reported 2026-09-28, one of seven panes after a bundle reload). This is
 * the backstop that does not depend on any of those links: well past the
 * slowest honest rebuild (a full replay parse plus {@link REBUILD_SETTLE_MAX_MS}),
 * a pane still hidden is shown as it is. A visible scroll is a cosmetic
 * flaw; a terminal that never comes back is not.
 */
export const CURTAIN_MAX_MS = 2_000;

/**
 * The longest a geometry change waits for the pane's parser to reach a gap.
 *
 * Resizing xterm REFLOWS its buffer, and a reflow that lands between two slices
 * of a write moves the rows the half-parsed escape stream is addressing. An
 * agent's TUI is drawn by relative moves — "up twelve rows, erase from here" —
 * so the erase then lands on rows that hold something else: the frame's rule
 * drawn twice, an answer printed under the copy it was replacing, or, when the
 * miscount runs the other way, a pane wiped down to its status line. That is
 * the whole class of "moving a terminal breaks it" (reported 2026-08-11), and
 * the gate below is the answer: fit at a moment when nothing is mid-parse.
 *
 * The wait is bounded because a pane streaming without pause has no gap to
 * offer, and a terminal that never follows its tile is worse than one frame
 * parsed across a reflow — the agent would go on formatting for a size no
 * window is showing. Comfortably longer than one of xterm's ~12 ms parse
 * slices and than any single chunk a socket delivers, short enough that even a
 * pane talking flat out matches its tile within a quarter of a second.
 */
export const RESIZE_PARSE_WAIT_MS = 250;

/**
 * How often a pane may refit while its boundary is still being dragged.
 *
 * The middle ground between two rejected extremes. Refitting on every observer
 * tick (up to 120/s) was the original slideshow: every fit reflows xterm's
 * buffer and makes the agent repaint its whole screen, on the thread that owes
 * the drag its next frame. Refitting never — holding everything for one pass
 * at release — kept the drag fast but froze the text mid-gesture, and the
 * release then re-wrapped it in one visible, hard snap (maintainer,
 * 2026-08-11: the text does not move smoothly with the drag).
 *
 * At this pace the text follows the seam in a few honest steps — an agent
 * repaint costs tens of milliseconds, so about five per second is work it can
 * absorb without stuttering — while the pointer keeps every frame in between.
 * The exact final size still lands through the `layoutBusy` release effect,
 * so letting go looks the same as before, just from much closer by.
 */
export const DRAG_REFIT_MS = 200;

/**
 * How long a NARROWER tile must hold before the pane and its agent take it.
 *
 * Switching a layout passes through widths nobody chose: every pane of a
 * workspace was squeezed to 15-16 columns for about a second and then widened
 * back to 46 (recorded 2026-10-26). Claude Code sizes the live output box of a
 * running command for the width it sees and never shrinks that box while the
 * command runs, so one such second left 36 blank rows in the middle of the pane
 * until the command ended; finished blocks showed the same kind of gap. No
 * resize afterwards brings the space back. A narrowing that is undone within
 * this window therefore never reaches the agent; one that stays is applied
 * after it. Widening is not held, and neither are the deliberate refits (drag
 * release, a pane returning to the stage, a font change).
 */
export const NARROW_SETTLE_MS = 1_500;

/**
 * How long a call-sign may be — the same cap the backend enforces
 * (`MAX_TERMINAL_NAME`), so the field stops where the save would have failed
 * rather than letting somebody type a name that comes back rejected.
 */
export const MAX_TERMINAL_NAME = 40;

/**
 * The floor under a pane's geometry — a CRASH GUARD, not a layout opinion.
 *
 * ## The rule this serves
 *
 * A terminal is exactly as wide as the tile it is shown in, and every
 * character inside that tile is visible. Nothing this pane draws may reach
 * past its own edge. That is the maintainer's rule for this screen
 * (2026-08-11), and it settles a run of attempts that each broke it:
 *
 * * **Clipping** (until 2026-08-11) rendered a fixed 60-column grid whatever
 *   the tile could show and cut the remainder off at the edge. Six terminals
 *   then each showed about two thirds of themselves, and the maintainer read
 *   the result — correctly — as terminals shoved behind one another. Adding a
 *   sideways scrollbar and two scroll shadows did not change what it was.
 * * **Auto-shrinking** (the same day) walked the pane's text size down until
 *   that 60-column grid fitted. It silently overrode the toolbar's size on
 *   every narrow pane — nine columns at ~5 px glyphs while the control read 20
 *   — so the size controls looked dead. Do not reintroduce it.
 *
 * So the fit is honest in both directions: xterm is given what the tile
 * measures, and the agent behind it is told the SAME number. The two must
 * never disagree — an agent laying lines out for 60 columns into an xterm
 * showing 33 re-wraps every one of them, and the TUI's cursor moves then land
 * on rows that no longer hold what they held when it drew them, which came
 * back as shredded one-word fragments (2026-08-10).
 *
 * ## What is left for this floor to do
 *
 * Only the absurd. A tile mid-layout measures 0, a hidden one measures
 * nothing at all, and a PTY resized to zero columns permanently wrecks the
 * agent's drawing. 10x4 is far below any arrangement a person builds on
 * purpose — with a workspace opening two panes deep (`WIZARD_COLUMN_HEIGHT`)
 * even twenty terminals leave roughly twice this — so in practice it is only
 * ever met by a measurement that is not real.
 *
 * It is deliberately NOT a floor on what a coding CLI needs. That question is
 * answered where it belongs: the launcher warns from twenty terminals up
 * (`CROWDED_TERMINAL_COUNT`) and opens as many as the user confirms. How many
 * agents fit on their display is theirs to decide, and a pane too narrow to be
 * useful is a pane they can see is too narrow — which is exactly what clipping
 * hid.
 *
 * The backend holds the same floor (`dodaios/agentic_ide/session.py`), so a
 * stale or older client cannot resize a PTY into nothing either.
 */
export const MIN_REAL_COLS = 10;
export const MIN_REAL_ROWS = 4;

/**
 * The size a pane hands over when it could not measure its tile at mount.
 *
 * Deliberately UNDER the server's viewer floor (`MIN_VIEWER_COLS` /
 * `MIN_VIEWER_ROWS` in `dodaios/agentic_ide/session.py`): that is the wire's
 * spelling of "not measured yet". The server answers it by keeping the
 * geometry the pane already has — a running agent is not re-wrapped for a
 * size no tile ever had, a fresh one is spawned at the transcript's default —
 * and reports that geometry back, so the grid here follows it until the tile
 * is shown and measured. Zero would not do: the server reads it as absent and
 * substitutes 80x24, which is precisely a size no tile had.
 */
/**
 * The least time between two gesture reclaims of one displaced pane.
 *
 * Long enough that two windows in use at the same moment do not hand the
 * agent's size back and forth on every mouse move (each hand-over is a full
 * repaint of the agent's screen), short enough to feel immediate.
 */
export const GESTURE_RECLAIM_MS = 2_000;

export const UNMEASURED_SIZE = { cols: 1, rows: 1 } as const;

/*
 * A pane never argues about its own width any more.
 *
 * The number a coding CLI is comfortable at (`WORKABLE_COLS` in ./layout) is
 * quoted ONLY by the wizard, as advice before anything opens. In here it has
 * been four things, and every one of them was reported as a bug by the person
 * looking at the screen:
 *
 * * a floor the backend enforced, which drew narrow panes wider than their
 *   window — read as terminals shoved behind one another (2026-08-11);
 * * an auto-shrink of the text until the floor fitted — the size controls
 *   looked dead (2026-08-11);
 * * a notice row saying "N columns — needs about 60" on every narrow pane;
 * * a card that HID the terminal below 60 columns and offered "Show it anyway"
 *   (2026-08-13, against a repaint bug measured at ~13 columns) — which then
 *   covered every pane of an ordinary six-pane workspace at 56 columns and had
 *   to be clicked away six times (2026-08-18).
 *
 * The maintainer's rule now is the simplest one: the terminal is exactly as
 * wide as its tile, always, and it is always SHOWN. How many panes fit a
 * screen is the user's call; the wizard says what they will get, and the pane
 * gets out of the way. Only the absurd (`MIN_REAL_COLS`) is still refused.
 */

export type PaneStatus = "connecting" | "live" | "exited" | "error";

/**
 * Is the whole document out of sight — window behind another, minimized, or in
 * a background tab?
 *
 * Read through a function rather than inlined so a pane behaves the same in a
 * test environment that ships no `document`, and so the two places that must
 * agree about it cannot drift apart.
 */
export function documentHidden(): boolean {
  return typeof document !== "undefined" && document.hidden === true;
}

/**
 * The smallest window a pane will still measure itself in.
 *
 * Far below any window a person reads a terminal in, and far above the stub
 * a minimized desktop window leaves behind: WebView2 on Windows shrinks the
 * page to about 158x26 px while the app sits in the taskbar (measured
 * 2026-09-28). A pane measured in that stub is not a real measurement — the
 * full-width top pane still came out at the 10x4 floor, its agent redrew its
 * whole interface ten columns wide, and restoring the window left that frame
 * shredded over the real one until a click made the agent paint again.
 */
export const MIN_WINDOW_WIDTH_PX = 320;
export const MIN_WINDOW_HEIGHT_PX = 160;

/**
 * Is the window itself collapsed to a size no pane can honestly be fitted to?
 *
 * Deliberately not `document.hidden`: the desktop shell can report a window
 * that is plainly on screen as hidden for minutes (see `viewerMayOwn`), and a
 * pane that refused to fit then could not follow a real resize. The viewport's
 * own size cannot be wrong that way. A window that restores comes back through
 * the ResizeObserver, which measures again.
 */
export function windowCollapsed(
  width: number = typeof window !== "undefined" ? window.innerWidth : Infinity,
  height: number = typeof window !== "undefined" ? window.innerHeight : Infinity,
): boolean {
  return width < MIN_WINDOW_WIDTH_PX || height < MIN_WINDOW_HEIGHT_PX;
}

/**
 * A coding CLI a split may start.
 *
 * Re-exported rather than declared here: the same list is offered by the chat
 * view's rail and by an empty workspace, so it belongs to the picker they all
 * share (see `AgentPicker`). Kept exported from this module because that is
 * where every caller already imports it from.
 */
export type { SplitAgentChoice };

export type SplitDirection = "right" | "down" | "left" | "above";

/**
 * Where a pane's recap came from, kept together rather than as five more props.
 *
 * None of it changes what the header SAYS — it changes what the card behind the
 * header can explain about it, which is the difference between a thin recap and
 * a thin recap that tells you no model could be reached to write a better one.
 */
export interface PaneRecapMeta {
  source?: RecapSource;
  reason?: RecapReason;
  /** The model that wrote it, when one did. */
  writer?: string;
  /** What went wrong the last time this pane was summarized. */
  note?: string;
  /** Unix seconds; 0 for the recap derived from the pane's own output. */
  generatedAt?: number;
}

/** What the recap card may do about the recap. Absent leaves it read-only. */
export interface PaneRecapActions {
  onSave?: (headline: string, detail: string) => Promise<void>;
  onClear?: () => Promise<void>;
  onRefresh?: () => Promise<void>;
}

export interface AgenticTerminalProps {
  onSwapWithFocused?: () => void;
  /** Terminal call-sign — also the WS path segment. */
  name: string;
  /**
   * Which workspace this pane belongs to.
   *
   * Sent with the socket so the backend can pin it: several workspaces can be
   * open, the front one changes while sockets are alive, and a keystroke must
   * reach the pane it was typed into rather than whichever workspace happens to
   * be showing when it arrives.
   */
  workspaceId?: string;
  /** Agent label shown in the pane header ("Claude Code"). */
  displayName: string;
  /**
   * Compact workspace chrome is opt-in; legacy grids retain their existing
   * header. "none" draws the bare terminal for a host that brings its own
   * title bar (the office's pane panel) — no header, no border of its own.
   * "minimal" is the multiplexer tile: a square 1px frame, a slim square
   * title row with the compact header's controls, and the pane the reader
   * works in outlined in the signal hue.
   */
  headerMode?: "legacy" | "compact" | "minimal" | "none";
  /**
   * Minimal tiles only: may the focused pane wear the blue "you are here"
   * edge right now? Off while the reader works in the IDE's side panel, which
   * then wears it instead. The pane stays the prompt target either way.
   */
  markFocus?: boolean;
  /** Compact header only: opens the fork dialog for this pane. */
  onFork?: () => void;
  /** Compact header only: the worktree branch this pane runs on, if any. */
  branch?: string;
  /** The pane's own git worktree folder, set only for a worktree fork. */
  folder?: string;
  /** Compact header only: the connected computer this pane runs on, if any. */
  computerName?: string;
  /** Compact header only: "Run on …" / "Bring back" menu entries. */
  placementItems?: { label: string; run: () => void }[];
  /** Compact header only: "Move to <workspace>" menu entries. */
  workspaceItems?: { label: string; run: () => void }[];
  /** Registry identity and optional custom logo for the compact header. */
  agent?: string;
  agentLogoUrl?: string;
  /**
   * What this session is doing, in one clause — the header's main label.
   *
   * It REPLACES the agent name there when present, because the agent name is
   * the same for every pane in the grid and this is the part that differs. The
   * CLI is still one hover away (the tooltip names it) and the pane's call-sign
   * badge never moves.
   */
  recap?: string;
  /** The several-sentence version of `recap`, read in the recap card. */
  recapDetail?: string;
  /** Who wrote the recap and why — the card's footer and its explanation. */
  recapMeta?: PaneRecapMeta;
  /** Rewriting, resetting and re-summarizing it. Absent = read-only card. */
  recapActions?: PaneRecapActions;
  /**
   * Which subscription this pane runs on ("Work seat"), when that is worth
   * saying. Undefined for everyone with a single login — the header must not
   * grow a badge that answers a question the user does not have.
   */
  accountLabel?: string | null;
  /** Number shown beside the pane header's prompt-history icon. */
  promptCount?: number;
  appearance: TerminalAppearance;
  fontSize: number;
  /**
   * Has the grid measured the pane's final opening geometry?
   *
   * Area-aware layouts cannot know their band count until the container has a
   * height. Opening the PTY during the width-only first pass attaches it at one
   * size and immediately moves it to another, while its replay is still being
   * parsed. Omitted for standalone uses, which already render at a fixed size.
   */
  geometryReady?: boolean;
  /** Highlight this pane as the prompt target. */
  focused?: boolean;
  /** Is this pane currently visible on the chat stage? */
  active?: boolean;
  onFocus?: () => void;
  onStatus?: (status: PaneStatus, detail?: string) => void;
  /** True while this pane fills the whole grid. */
  maximized?: boolean;
  onToggleMaximize?: () => void;
  /**
   * Open another terminal beside or below this one.
   *
   * `agent` is the coding CLI the user picked from the split menu; omitted, the
   * new pane inherits this pane's agent.
   */
  onSplit?: (direction: SplitDirection, agent?: string) => void;
  /**
   * Coding CLIs the split menu offers. With one (or none) there is nothing to
   * choose, so the split buttons act immediately instead of opening a menu.
   */
  agents?: SplitAgentChoice[];
  /** The split menu installed one of them — the grid re-reads its list. */
  onAgentsChanged?: () => void;
  /**
   * Give this pane another call-sign.
   *
   * Answers whether the name was accepted, so the editor can stay open with the
   * text still in it when the workspace already has a pane by that name.
   * Omitted, the header shows no rename control at all rather than one that
   * would do nothing.
   */
  onRename?: (name: string) => Promise<boolean>;
  /** Close this pane (the caller asks for confirmation first). */
  onClose?: () => void;
  /** Disable the split buttons — the workspace is at its terminal limit. */
  splitDisabled?: boolean;
  /** A drop or a paste could not be completed — the grid surfaces it. */
  onAttachError?: (message: string) => void;
  /** Called when the user asks a dead pane to start a fresh agent. */
  onRestart?: () => void;
  /**
   * Read this pane as a chat: the workspace's chat stage, this pane on it,
   * drawn with the agent chat's timeline (see ./PaneChat). Absent on a plain
   * shell pane, which has no conversation to read.
   */
  onOpenChat?: () => void;
  /** Continue this pane's CLI conversation in a thread. */
  onOpenThread?: () => void;
  /**
   * Press on the pane's header — the grip that picks this pane up.
   *
   * The header rather than the whole pane, because the rest of the pane is a
   * live terminal: a drag started there would be a text selection inside the
   * agent's output, which is a thing people do all day. Omitted, the header is
   * an ordinary header and the pane cannot be dragged (a maximized pane, or one
   * in selection mode, has nowhere to be dropped).
   */
  onArrangeStart?: (event: React.PointerEvent) => void;
  /** Show a dedicated grip when the surrounding layout uses insertion reorder. */
  showArrangeHandle?: boolean;
  /** True while THIS pane is the one being carried — it is drawn as lifted. */
  arranging?: boolean;
  /**
   * True while the workspace's geometry is actively being dragged.
   *
   * The pane then refits itself on a leash instead of freely: a fit reflows
   * xterm's buffer AND tells the agent its new size, and an agent answers that
   * by redrawing its whole screen. Sixty of those a second, across every pane
   * a seam touches, is what turned dragging a boundary into a slideshow — so
   * mid-drag the pane takes at most one fit per DRAG_REFIT_MS, enough for the
   * text to follow the seam in steps instead of freezing until release. The
   * exact final size is still taken in a single pass the moment this goes
   * false, which is what stops the terminal's contents from trailing the frame
   * around them for longer than they must.
   */
  layoutBusy?: boolean;
  /**
   * Bump to reconnect this pane.
   *
   * An exited agent leaves a dead pane with no way back: the connect effect runs
   * on mount only (deliberately — see the file header), and remounting is not an
   * option because it is what kills a LIVE agent. So the token is part of the
   * effect's identity: changing it tears down this one socket and opens a fresh
   * one, and the backend spawns a new agent for it.
   */
  restartToken?: number;
  /**
   * Open as THE view of this pane in this window: while mounted it sizes the
   * pane, and the same pane's other viewers here (the IDE grid behind the
   * office's pane window) follow it instead of taking the size back on every
   * gesture. Read at mount. See ./paneSizeLead.
   */
  sizeLead?: boolean;
}
