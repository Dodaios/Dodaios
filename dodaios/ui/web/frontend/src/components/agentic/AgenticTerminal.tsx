/**
 * One named pane of the Agentic IDE: xterm.js wired to
 * `/api/agentic-ide/pty/{name}`, running one coding agent in the chosen folder.
 *
 * Two conventions matter here and both are load-bearing:
 *
 * 1. The xterm instance lives in a ref, never in state — putting it in state
 *    re-renders the component on every output chunk and the pane stutters.
 * 2. Appearance and font size are applied to the LIVE instance in their own
 *    effects. Rebuilding the terminal when the user flips to dark mode would
 *    tear down the WebSocket, which kills the agent running behind it and
 *    loses the whole session. So the connect effect depends on pane identity,
 *    restart intent and one-way initial geometry readiness — never live
 *    appearance state.
 *
 * ## Why this pane is configured the way it is
 *
 * A coding agent's TUI is the hardest thing you can ask a web terminal to
 * draw: box-drawing frames, emoji status markers, live-rewritten spinner lines,
 * and a prompt box that redraws on every keystroke. Rendered with xterm's
 * defaults it came out visibly broken (reported 2026-07-25): text wrapped in
 * the wrong places, the frame characters drifted out of their columns, and
 * typing left artefacts behind. Four causes, all fixed here:
 *
 * * **Character width.** Without the Unicode 11 provider, xterm measures emoji
 *   and many box/symbol characters as one cell when the terminal on the other
 *   side counts them as two. Every such glyph then shifts the rest of the line
 *   by a column — which is exactly what "the frames look wrong" means.
 * * **ConPTY line semantics.** On Windows the agent runs behind ConPTY, which
 *   re-wraps and re-emits lines differently from a POSIX pty. xterm has a
 *   dedicated compatibility mode for it; without `windowsPty` the re-emitted
 *   lines stack up as duplicated, half-overwritten rows.
 * * **Measuring before the font is ready.** FitAddon derives the column count
 *   from one measured character. Run before the web font loads, it measures
 *   the fallback font, computes the wrong column count, and the agent then
 *   formats for a width the pane does not have. Worse, xterm keeps drawing the
 *   real font's wider glyphs into that too-narrow grid, so the text smears
 *   across its own columns. Neither `document.fonts.ready` nor a re-fit fixes
 *   this — see `@/lib/terminalFont`, which does.
 * * **Renderer.** The DOM renderer draws each cell as an element; with a TUI
 *   redrawing on every keystroke that is both slow and subtly misaligned. The
 *   canvas renderer draws on a grid, which is what a terminal actually is.
 */
import "@xterm/xterm/css/xterm.css";
import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { Terminal } from "@xterm/xterm";
import { FitAddon } from "@xterm/addon-fit";
import { Loader2, Paperclip } from "lucide-react";
import { cn } from "@/lib/utils";
import { PANE_CHROME, PANE_TILE } from "./terminalThemes";
import { SkillDropCard } from "./sidePanel/skills/SkillDropCard";
import { terminalFontSettled, whenTerminalFontReady } from "@/lib/terminalFont";
import { PANE_INPUT_EVENT, type PaneInputDetail } from "./ideHotkeys";
import { useIdeChatStore } from "@/store/ideChat";
import { bindTerminalScrollRegion } from "./terminalScrollSurface";
import { type PromptDelivery } from "./paneSocket";
import { PromptReceipt } from "./PromptReceipt";
import { PaneConversationDialog } from "./PaneConversationDialog";
import { PaneChangesDialog } from "./PaneChangesDialog";
import { useGitSessionStore } from "@/store/gitSession";
import { useIdeSidePanelStore } from "@/store/ideSidePanel";
import { prefetchPaneChanges } from "./paneChangesApi";
import { WorkspaceTerminalHeader } from "./WorkspaceTerminalHeader";
import { usePaneContextMenu } from "./usePaneContextMenu";
import { fill, loadLocaleChunk, useT } from "@/i18n";
import { PreservedTerminalViewport, CURTAIN_MAX_MS, PaneStatus, SplitDirection, AgenticTerminalProps } from "./terminal/paneShared";
import { PaneHeader } from "./terminal/PaneHeader";
import { PaneStatusNotice } from "./terminal/PaneStatusNotice";
import { useTerminalConnection } from "./terminal/connect/useTerminalConnection";
import { usePaneAttachments } from "./terminal/usePaneAttachments";
import { usePaneLiveRestyle } from "./terminal/usePaneLiveRestyle";
import { usePaneStageSwitch } from "./terminal/usePaneStageSwitch";

export {
  CURTAIN_MAX_MS,
  DRAG_REFIT_MS,
  GESTURE_RECLAIM_MS,
  NARROW_SETTLE_MS,
  REBUILD_QUIET_MS,
  REBUILD_SETTLE_MAX_MS,
  REPAINT_WAIT_MAX_MS,
  RESIZE_PARSE_WAIT_MS,
  RETURN_REPAINT_NUDGE_MS,
  UNMEASURED_SIZE,
  windowCollapsed,
} from "./terminal/paneShared";
export type {
  PaneRecapActions,
  PaneRecapMeta,
  PaneStatus,
  SplitAgentChoice,
  SplitDirection,
} from "./terminal/paneShared";

export function AgenticTerminal({
  onSwapWithFocused,
  name,
  workspaceId,
  displayName,
  headerMode = "legacy",
  markFocus = true,
  onFork,
  branch,
  folder,
  computerName,
  placementItems,
  workspaceItems,
  agent,
  agentLogoUrl,
  recap,
  recapDetail,
  recapMeta,
  recapActions,
  accountLabel,
  promptCount = 0,
  appearance,
  fontSize,
  geometryReady = true,
  focused = false,
  active = true,
  onFocus,
  onStatus,
  maximized = false,
  onToggleMaximize,
  onSplit,
  agents,
  onAgentsChanged,
  onRename,
  onClose,
  splitDisabled = false,
  onAttachError,
  onRestart,
  onOpenChat,
  onOpenThread,
  restartToken = 0,
  onArrangeStart,
  showArrangeHandle = false,
  arranging = false,
  layoutBusy = false,
  sizeLead = false,
}: AgenticTerminalProps) {
  const paneMenu = usePaneContextMenu(headerMode === "compact" || headerMode === "minimal");
  const containerRef = useRef<HTMLDivElement | null>(null);
  const terminalRegionRef = useRef<HTMLDivElement | null>(null);
  const terminalRegionId = useId();
  const termRef = useRef<Terminal | null>(null);
  const fitRef = useRef<FitAddon | null>(null);
  // Lets the font-size effect trigger a REAL resize (xterm + the terminal
  // process together) without reaching into the connect effect's socket.
  const resizeRef = useRef<(() => void) | null>(null);
  const claimResizeRef = useRef<(() => void) | null>(null);
  /** The refit a pane makes on coming back on stage — see `returnResize`. */
  const returnResizeRef = useRef<(() => void) | null>(null);
  /** Asks the agent to paint its whole screen again — see RETURN_REPAINT_NUDGE_MS. */
  const repaintOnReturnRef = useRef<(() => void) | null>(null);
  /** Was this pane parked off the stage since it last took it? */
  const parkedRef = useRef(false);
  /** The claim a gesture inside the pane makes — see `takeOwnership`. */
  const takeOwnershipRef = useRef<(() => void) | null>(null);
  /**
   * This viewer's identity in the window's size-lead registry (./paneSizeLead),
   * and whether it held the lead when its terminal was last torn down. Both
   * outlive the connect effect: a rebuild (a restart, the font arriving, the
   * grid settling) is the same viewer, and must come back holding the lead it
   * had rather than leaving the pane leaderless for another viewer to claim.
   */
  const leadTokenRef = useRef<object>({});
  const heldLeadRef = useRef(false);
  const visibilityRef = useRef<{
    show: (afterFlush?: () => void) => void;
    park: () => void;
  } | null>(null);
  const statusRef = useRef<PaneStatus>("connecting");
  // Mirrored into state purely so the header can show/hide the restart button;
  // it transitions a handful of times per pane, never per output chunk.
  const t = useT();
  const [visibleStatus, setVisibleStatus] = useState<PaneStatus>("connecting");
  /*
   * What the socket said ABOUT that status, in the user's words.
   *
   * Kept here as well as handed to `onStatus` because the two readers need it
   * at different times. The grid shows it once, in a tooltip; the pane has to
   * keep saying it — an exit reason written into the terminal scrolls away the
   * moment anything else is drawn, and the trouble line is written at most once
   * per KIND of trouble (see `troubleShown`), so a user who looked away has no
   * way back to it at all. The notice below is that way back.
   */
  const [statusDetail, setStatusDetail] = useState<string>("");
  /*
   * Has this pane's agent drawn anything yet?
   *
   * A pane opened by voice is an EMPTY BLACK RECTANGLE for several seconds: the
   * grid renders it the moment the workspace state arrives, and the CLI inside
   * it only paints once the socket is up, a cold-start slot is free and the
   * process has booted — measured at 2.6-2.8 s on a healthy machine, longer
   * while the grid is busy relaying itself out. Nothing said so, so "open two
   * more terminals" looked like it had silently failed and the panes were
   * closed and asked for again (maintainer report 2026-07-28).
   *
   * Flipped by the first byte the agent writes, never back — a pane that has
   * painted once is a pane the user can read, whatever its socket does later.
   * Reconnects therefore stay quiet: the replayed screen is already there.
   */
  const [painted, setPainted] = useState(false);
  // A parked chat pane may have a large asynchronous xterm write to parse when
  // it takes the stage again. Keep its terminal surface out of the paint until
  // that write and the final viewport restoration have both landed; otherwise xterm
  // briefly shows the pane's old viewport (often its first prompt) and visibly
  // jumps to the live prompt one frame later.
  const [tailReady, setTailReady] = useState(active);
  // The terminal itself stays in a ref. This small epoch tells appearance and
  // font effects that the ref now points at a new instance after a restart.
  const [terminalEpoch, setTerminalEpoch] = useState(0);
  /*
   * Is a replay currently rebuilding this pane behind the curtain?
   *
   * The replay path and the chat-stage switch both hide the surface until the
   * viewport restoration has landed, and they can interleave: a replay arriving within
   * a frame of a stage switch (or of the mount) would otherwise have the
   * OTHER sequence's settle step lift the curtain while the replay is still
   * printing its history — which is exactly the top-to-bottom scroll the
   * curtain exists to hide. While this is true, only the replay's own
   * completion may reveal the pane.
   */
  const replayCurtainRef = useRef(false);
  // A stage switch must preserve a reader who deliberately scrolled back.
  // Kept through replay parsing because reset() temporarily destroys xterm's
  // own viewport, making it impossible to recover afterwards.
  const preservedViewportRef = useRef<PreservedTerminalViewport | null>(null);
  // Every replay and active-stage transition invalidates callbacks/frames from
  // the one before it. A boolean alone cannot distinguish "A finished" from
  // "B is still rebuilding", so an old callback could otherwise reveal B.
  const replayGenerationRef = useRef(0);
  const replayRevealFrameRef = useRef<number | undefined>(undefined);
  const curtainWatchdogRef = useRef<number | undefined>(undefined);
  /**
   * Promise that the curtain just raised comes down — see {@link CURTAIN_MAX_MS}.
   *
   * Re-armed by every raise, so it measures the newest curtain, and touching
   * refs and a state setter only, so the closure the connect effect keeps from
   * its first render stays correct. An inactive pane is hidden on purpose and
   * is left alone; taking the stage raises (and arms) a fresh curtain.
   */
  const armCurtainWatchdog = () => {
    if (curtainWatchdogRef.current !== undefined) {
      window.clearTimeout(curtainWatchdogRef.current);
    }
    curtainWatchdogRef.current = window.setTimeout(() => {
      curtainWatchdogRef.current = undefined;
      if (!activeRef.current) return;
      replayCurtainRef.current = false;
      containerRef.current?.style.removeProperty("visibility");
      setTailReady(true);
    }, CURTAIN_MAX_MS);
  };
  useEffect(
    () => () => {
      if (curtainWatchdogRef.current !== undefined) {
        window.clearTimeout(curtainWatchdogRef.current);
      }
    },
    [],
  );
  /**
   * Hold a finished rebuild back until the pane has stopped being redrawn.
   *
   * Owned by the connect effect, because only that scope sees every byte this
   * pane draws. Reached from the stage-switch effect below as well: taking the
   * stage also announces a new size, and an agent answers a size the same way
   * it answers the server's nudge — by painting its whole screen again.
   *
   * Null before the terminal exists; the caller then reveals straight away,
   * which is right for a pane that has nothing to rebuild yet.
   */
  const settleRebuildRef = useRef<
    ((generation: number, reveal: () => void) => void) | null
  >(null);
  /**
   * The delivery this pane is currently showing a receipt for, if any.
   *
   * Held here rather than derived from the terminal's contents because the
   * terminal is precisely what cannot be trusted to show it — see
   * ./PromptReceipt for the four ways a delivered prompt fails to reach the
   * screen. Fed from two independent sources so that neither being unavailable
   * loses the proof: the socket's `prompt` frame (instant, lossy) and the
   * pane's `last_prompt_at` in the workspace state (durable, one poll late).
   */
  const [receipt, setReceipt] = useState<PromptDelivery | null>(null);
  /** The delivery the user has already waved away; never shown again. */
  const [dismissedAt, setDismissedAt] = useState<number | null>(null);
  /** Briefly true right after a delivery — draws the eye to the right pane. */
  const [justDelivered, setJustDelivered] = useState(false);
  const deliveredTimer = useRef<number | undefined>(undefined);
  // One flash at a time, and none left running once the pane is gone.
  const flashDelivered = useCallback((ms: number) => {
    setJustDelivered(true);
    window.clearTimeout(deliveredTimer.current);
    deliveredTimer.current = window.setTimeout(() => setJustDelivered(false), ms);
  }, []);
  useEffect(() => () => window.clearTimeout(deliveredTimer.current), []);
  /** The pane's recorded conversation, opened from the header book button. */
  const [historyOpen, setHistoryOpen] = useState(false);
  const [changesOpen, setChangesOpen] = useState(false);
  const paneRequest = useIdeChatStore((state) => state.paneRequest);
  useEffect(() => {
    if (!workspaceId || paneRequest?.open !== "changes") return;
    if (paneRequest.workspaceId !== workspaceId || paneRequest.pane !== name) return;
    setChangesOpen(true);
    useIdeChatStore.getState().settlePaneOpen(paneRequest.nonce);
  }, [paneRequest, workspaceId, name]);
  // Latest callbacks/appearance without re-running the connect effect.
  const onStatusRef = useRef(onStatus);
  const onAttachErrorRef = useRef(onAttachError);
  /*
   * The text size this pane draws at, as of NOW.
   *
   * A ref because the connect effect must not re-run when the user changes the
   * size — rebuilding the terminal would drop the agent's screen and reconnect
   * its socket for what is a one-line restyle. But it is written on EVERY
   * render, never frozen at mount: the effect below rebuilds the terminal for
   * reasons of its own (`geometryReady` flipping when the grid is re-measured,
   * a pane restart, a rename), and a frozen value hands every one of those
   * rebuilds the size this pane opened with rather than the size the user is
   * looking at. That is the reported bug — the toolbar reads 20, the pane the
   * user last touched is 20, and every pane rebuilt since the change is back
   * at the 13 the grid started with, with no further size change coming to
   * correct it (see the `fontSize` effect: it fires on CHANGES).
   */
  const fontSizeRef = useRef(fontSize);
  // The ground this pane draws on, as of NOW — the socket tells the backend, so
  // that the agent's CLI is answered with the colours it is actually drawing on
  // when it asks. Read at connect time, hence a ref rather than the prop: the
  // connect effect must not re-run when the user flips the theme. Same rule as
  // the size above: current on every render, so a rebuild cannot resurrect the
  // theme this pane happened to open with.
  const appearanceRef = useRef(appearance);
  const activeRef = useRef(active);
  const focusedRef = useRef(focused);
  // Read by the connect effect's resize scheduler, which is built once and
  // therefore cannot see the prop change.
  const layoutBusyRef = useRef(layoutBusy);
  onStatusRef.current = onStatus;
  onAttachErrorRef.current = onAttachError;
  fontSizeRef.current = fontSize;
  appearanceRef.current = appearance;
  activeRef.current = active;
  focusedRef.current = focused;
  layoutBusyRef.current = layoutBusy;

  // Only the focused pane's cursor blinks. A blinking cursor repaints its pane
  // twice a second forever, and on a wall of a dozen idle terminals that was
  // the renderer's biggest standing cost (CPU diet, 2026-08-22). Unfocused
  // panes draw no cursor at all — see `cursorInactiveStyle` below.
  useEffect(() => {
    const term = termRef.current;
    if (term) term.options.cursorBlink = focused;
  }, [focused]);

  useEffect(() => {
    const region = terminalRegionRef.current;
    if (!region) return;
    return bindTerminalScrollRegion(region);
  }, []);

  /*
   * Is the font this pane will draw with here to be measured?
   *
   * The connect effect below builds the grid from ONE measured glyph and hands
   * the agent that grid's column count in its first message. Measured before
   * the display font has arrived — it comes through a stylesheet the app
   * `@import`s from the network, so after a restart it is routinely a moment
   * late — that glyph is the fallback's, the count is wrong, and a RUNNING
   * agent is re-wrapped for it and then re-wrapped again when the real font
   * lands (see `whenTerminalFontReady` for what that did to every pane of a
   * workspace on 2026-08-27). So the pane does not build until the font is
   * measurable, or until the bounded wait says it is not coming. Settled
   * synchronously where it can be, so a pane whose font is already here
   * mounts exactly as it always did.
   */
  const [fontReady, setFontReady] = useState(() =>
    terminalFontSettled(fontSizeRef.current),
  );
  useEffect(() => {
    if (fontReady) return;
    let cancelled = false;
    void whenTerminalFontReady(fontSizeRef.current).then(() => {
      if (!cancelled) setFontReady(true);
    });
    return () => {
      cancelled = true;
    };
  }, [fontReady]);

  useTerminalConnection({
    name,
    workspaceId,
    displayName,
    sizeLead,
    containerRef,
    onStatusRef,
    onAttachErrorRef,
    fontSizeRef,
    appearanceRef,
    activeRef,
    focusedRef,
    layoutBusyRef,
    termRef,
    fitRef,
    resizeRef,
    claimResizeRef,
    returnResizeRef,
    repaintOnReturnRef,
    takeOwnershipRef,
    leadTokenRef,
    heldLeadRef,
    visibilityRef,
    statusRef,
    setVisibleStatus,
    setStatusDetail,
    setPainted,
    setTailReady,
    setTerminalEpoch,
    setReceipt,
    flashDelivered,
    replayCurtainRef,
    preservedViewportRef,
    replayGenerationRef,
    replayRevealFrameRef,
    settleRebuildRef,
    armCurtainWatchdog,
    restartToken,
    geometryReady,
    fontReady,
  });
  usePaneStageSwitch({ active, containerRef, termRef, parkedRef, replayCurtainRef, preservedViewportRef, replayGenerationRef, replayRevealFrameRef, visibilityRef, resizeRef, returnResizeRef, claimResizeRef, repaintOnReturnRef, settleRebuildRef, activeRef, setTailReady, armCurtainWatchdog });

  usePaneLiveRestyle({ appearance, fontSize, terminalEpoch, termRef, resizeRef, claimResizeRef });

  /*
   * Refit when the pane is maximized, and again when it is restored.
   *
   * Maximizing is by far the largest size change a pane ever makes — a cell in
   * a grid of ten becomes the whole window — and until now the terminal inside
   * it only found out through its ResizeObserver. That is a single debounced
   * notification, competing with everything else the grid re-lays out in the
   * same breath, and delivered when the browser gets round to it. Usually it
   * arrives and the pane fills. Occasionally it did not, and the result was the
   * reported bug: a pane visibly maximized with its agent still drawing at the
   * old cell's width, the rest of the window left blank.
   *
   * So the one size change the pane genuinely KNOWS about is driven from that
   * knowledge instead of waited for. Three passes because the grid settles over
   * a frame or two — and they are nearly free: a fit that lands on the size the
   * terminal already has sends nothing at all.
   *
   * Claimed, not merely requested (see `claimResize`): maximizing is the user
   * opening a pane up to READ it, and a request from a window that had lost
   * the pane to another viewer was being answered with that viewer's size —
   * the pane filled the window and its agent kept drawing into the top-left
   * corner of it (2026-08-25).
   */
  useLayoutEffect(() => {
    const refit = () => (claimResizeRef.current ?? resizeRef.current)?.();
    // The office preview may still lead this same PTY. Maximizing explicitly
    // hands its size to the grid, before paint, without moving keyboard focus.
    // Later settling passes only refit: they must not undo a newer pane click.
    if (maximized && document.hasFocus()) takeOwnershipRef.current?.();
    else refit();
    const frame = requestAnimationFrame(refit);
    const timers = [
      window.setTimeout(refit, 120),
      window.setTimeout(refit, 400),
    ];
    return () => {
      cancelAnimationFrame(frame);
      for (const timer of timers) window.clearTimeout(timer);
    };
  }, [maximized]);

  /*
   * Maximizing or restoring a pane from its header leaves the keyboard IN it.
   *
   * The button click took focus away from the terminal, so the user had to
   * click the pane a second time before typing reached the agent. Toggling is
   * an explicit "I want to work in this pane" — it becomes the focused pane and
   * its terminal takes the keyboard once the new layout has settled (a frame
   * for the size change, a short timer for the grid re-laying out around it).
   * Only on the user's own toggle, never from the `maximized` prop, so a pane
   * maximized by a cross-pane request does not steal the keyboard.
   */
  const toggleMaximizeAndFocusPane = useCallback(() => {
    onToggleMaximize?.();
    onFocus?.();
    takeOwnershipRef.current?.();
    const focusTerminal = () => termRef.current?.focus();
    requestAnimationFrame(focusTerminal);
    window.setTimeout(focusTerminal, 120);
  }, [onToggleMaximize, onFocus]);
  const toggleMaximizeAndFocus = onToggleMaximize ? toggleMaximizeAndFocusPane : undefined;

  // Keys the IDE's key menu sends on to this pane: Ctrl+B twice types one
  // Ctrl+B, the way tmux passes its own prefix through (see ./ideHotkeys).
  useEffect(() => {
    const onInput = (event: Event) => {
      const detail = (event as CustomEvent<PaneInputDetail>).detail;
      if (detail?.pane !== name || (workspaceId && detail.workspaceId !== workspaceId)) return;
      termRef.current?.input(detail.data);
      if (detail.focus !== false) termRef.current?.focus();
    };
    window.addEventListener(PANE_INPUT_EVENT, onInput);
    return () => window.removeEventListener(PANE_INPUT_EVENT, onInput);
  }, [name, workspaceId]);

  /*
   * Catch up the instant a drag lets go.
   *
   * While `layoutBusy` is true the pane deliberately ignores its own
   * ResizeObserver (see the prop), so this is where the size it ended up with
   * is finally taken. Immediately rather than through the observer's 80 ms
   * coalescing window: this is exactly the moment where the terminal's contents
   * still occupy the shape the pane had BEFORE the drag — the strip of empty
   * ground under the agent's last line — and every millisecond of it is
   * visible. The second pass one frame later is for the layout that settles
   * after the release (a scrollbar appearing, the prompt bar reflowing); a fit
   * that lands on the size the terminal already has sends nothing at all.
   */
  useEffect(() => {
    if (layoutBusy) return;
    // A seam was dragged in this window: the size it lands on is claimed, so
    // a pane another viewer had taken cannot snap back the moment it is let
    // go of (see `claimResize`).
    const refit = () => (claimResizeRef.current ?? resizeRef.current)?.();
    refit();
    const frame = requestAnimationFrame(refit);
    return () => cancelAnimationFrame(frame);
  }, [layoutBusy]);

  const { dragging, carrying, dragHandlers, attaching, skillInFlight } = usePaneAttachments({ containerRef, termRef, name, workspaceId, onAttachError, onFocus, takeOwnershipRef, flashDelivered });

  /*
   * A primary press anywhere on the pane makes it the pane in use.
   *
   * The frame's own bubbling handler never saw presses INTO a coding agent's
   * output: while the CLI tracks the mouse, ./terminalMouseSelection turns a
   * plain press into a selection press, and xterm's selection service then
   * stops it from propagating (so the CLI does not get it). The pane stayed
   * unselected — no highlight, prompts aimed at the previous pane. The
   * terminal region therefore also listens in the capture phase, which runs
   * before any of xterm's listeners; the event identity keeps the two
   * handlers from doing the work twice for one press.
   */
  const handledPress = useRef<Event | null>(null);
  const pressPane = (event: React.MouseEvent) => {
    if (event.button !== 0 || handledPress.current === event.nativeEvent) return;
    handledPress.current = event.nativeEvent;
    onFocus?.();
    takeOwnershipRef.current?.();
  };
  const chrome = PANE_CHROME[appearance];
  const minimal = headerMode === "minimal";
  const tile = PANE_TILE[appearance];
  // A pane whose agent runs on another computer changes files THERE, which
  // this machine's git cannot read — so only a local pane offers the review.
  const reviewChanges = workspaceId && !computerName ? () => setChangesOpen(true) : undefined;
  // The Git tab, narrowed to what this pane's agent session changed.
  const showInGit =
    workspaceId && !computerName
      ? () => {
          useGitSessionStore.getState().show(workspaceId, name);
          useIdeSidePanelStore.getState().openTab("git");
        }
      : undefined;
  const prefetchReview = workspaceId && !computerName
    ? () => {
      void loadLocaleChunk("pane_review");
      prefetchPaneChanges({ workspaceId, pane: name, folder });
    }
    : undefined;
  const headerProps = {
    githubStatusEnabled: active,
    contextMenuRequest: paneMenu.request,
    sendRightClicks: paneMenu.sendRightClicks,
    onToggleSendRightClicks: paneMenu.toggleSendRightClicks,
    onSwapWithFocused,
    name,
    workspaceId,
    promptCount,
    agent: agent ?? "",
    agentLogoUrl,
    displayName,
    status: visibleStatus,
    appearance,
    arranging,
    maximized,
    addDisabled: splitDisabled,
    onArrangeStart,
    onActivate: () => { onFocus?.(); takeOwnershipRef.current?.(); },
    onToggleMaximize: toggleMaximizeAndFocus,
    onAdd: onSplit ? (direction: SplitDirection) => onSplit(direction) : undefined,
    onClose,
    onRename,
    onOpenConversation: () => setHistoryOpen(true),
    onOpenChat,
    onOpenThread,
    onReviewChanges: reviewChanges,
    onReviewChangesPrefetch: prefetchReview,
    onShowInGit: showInGit,
    onRestart,
    onFork,
    branch,
    computerName,
    placementItems,
    workspaceItems,
  };

  return (
    <div
      onMouseDown={pressPane}
      {...dragHandlers}
      className={cn(
        // One quiet border per pane; the focused one carries the workspace's
        // only standing accent. The old per-pane drop shadows made a grid of
        // twelve read as twelve floating cards — a tiling terminal is a wall,
        // and a wall needs edges, not elevation.
        //
        // The border colour is part of the transition, not just the shadow.
        // Every state below changes BOTH, and animating only one made the
        // change arrive twice: the edge snapped to yellow on the frame the
        // click landed, and the ring around it faded in over the next 150 ms.
        // On a grid where the focused pane is the one standing accent, that
        // read as a flicker rather than as a pane taking focus.
        "relative flex h-full w-full flex-col overflow-hidden backdrop-blur-[4px]",
        headerMode === "none" ? "border-0" : "border",
        headerMode === "compact" ? "rounded-2xl" : headerMode === "none" || minimal ? "rounded-none" : "rounded-lg",
        "transition-[box-shadow,border-color,opacity] duration-150 ease-out motion-reduce:transition-none",
        // Focus steps the RIM one notch, from the structural hairline to
        // `--border-strong`, and stops there. It used to add a translucent
        // white edge and a shadow ring on top, which put three marks on a
        // state the header already announces three other ways (the filled
        // call-sign plate, the accent hairline under it, the visible action
        // cluster). A rim is the second separation device, never the first,
        // and a shadow belongs only to something that floats.
        focused && !minimal && "border-border-strong",
        // Being carried, and "a prompt just landed here", are the two states
        // that must be findable across a wall of twelve. They get the fill —
        // a solid `--primary` edge plus the sanctioned focus ring — because
        // that is the loudest neutral mark the system has. The old version
        // added a 28px bloom around it; a glow is additive light standing in
        // for a fill, and the fill is right here.
        dragging && "border-primary ring-2 ring-primary",
        justDelivered && "border-primary ring-2 ring-primary",
        // Lifted out of the grid while it is being carried: the pane stays where
        // it is (moving it under the cursor would tear down nothing but would
        // reflow every other pane on every mouse move) and says so by fading.
        arranging && "opacity-45",
      )}
      style={{
        background: chrome.shell,
        /*
         * The edge, and WHO is allowed to paint it.
         *
         * An inline colour beats every class, so this property decides whether
         * the three accent states above are drawn at all. It used to yield to
         * `focused` alone — which meant a pane being dragged, or one that had
         * just been handed a prompt, kept its plain grey edge and showed only
         * the shadow half of its own highlight. All three yield now.
         *
         * What is left is the resting pane, and its edge is where the pane's
         * lifecycle can be read from across the workspace rather than by
         * landing on it: dimmer once the agent has exited, the terminal's own
         * red when it failed, unchanged while it is connecting or live. See
         * `PANE_CHROME.edge` for why only those two states are marked.
         */
        //
        // A minimal tile paints its focused edge here too: the signal hue is a
        // per-appearance literal (`PANE_TILE`), not a class, for the same
        // reason the resting edge is. The pane the reader clicked into must be
        // findable at a glance across a full grid, so its edge is doubled by an
        // inner line of the same hue — see the focus ring at the end of the
        // frame for why that line is its own layer.
        borderColor:
          dragging || justDelivered
            ? undefined
            : minimal
              ? focused && markFocus ? tile.focus : tile.edge[visibleStatus]
              : focused
                ? undefined
                : chrome.edge[visibleStatus],
      }}
      data-pane-style={minimal ? "minimal" : undefined}
      data-testid={`agentic-pane-${name}`}
    >
      {headerMode === "compact" ? <WorkspaceTerminalHeader {...headerProps} />
      : minimal ? <WorkspaceTerminalHeader {...headerProps} variant="tile" focused={focused && markFocus} />
      : headerMode === "none" ? null : <PaneHeader
        workspaceId={workspaceId}
        githubStatusEnabled={active}
        status={visibleStatus}
        statusDetail={statusDetail}
        onArrangeStart={onArrangeStart}
        showArrangeHandle={showArrangeHandle}
        arranging={arranging}
        name={name}
        displayName={displayName}
        recap={recap}
        recapDetail={recapDetail}
        recapMeta={recapMeta}
        recapActions={recapActions}
        accountLabel={accountLabel}
        promptCount={promptCount}
        appearance={appearance}
        focused={focused}
        maximized={maximized}
        onToggleMaximize={toggleMaximizeAndFocus}
        onSplit={onSplit}
        agents={agents}
        onAgentsChanged={onAgentsChanged}
        onRename={onRename}
        onClose={onClose}
        splitDisabled={splitDisabled}
        onOpenConversation={() => setHistoryOpen(true)}
        onOpenChat={onOpenChat}
        onReviewChanges={reviewChanges}
        onReviewChangesPrefetch={prefetchReview}
      />}
      {/*
        What went wrong, kept on screen for as long as it is true — and the one
        way out of it. See PaneStatusNotice for why this is a row of its own
        rather than a second button in the header.
      */}
      <PaneStatusNotice
        name={name}
        displayName={displayName}
        status={visibleStatus}
        detail={statusDetail}
        light={appearance === "light"}
        onRestart={onRestart}
      />
      {/* Outside the terminal region on purpose: that region claims every
          press in its capture phase to select the pane, and a click inside
          the review must stay a click inside the review. */}
      {workspaceId && (
        <PaneChangesDialog
          open={changesOpen}
          onOpenChange={setChangesOpen}
          workspaceId={workspaceId}
          pane={name}
          folder={folder}
          branch={branch}
        />
      )}
      {/*
        Keep the visual inset OUTSIDE xterm's measured host. FitAddon reads the
        host's border-box but does not subtract padding on that host, so putting
        the inset there made it report one row more than the pane could show.
        The last terminal line was consequently clipped after a vertical resize.

        `min-h-0` is equally load-bearing: this is a shrinking flex child, and
        xterm's canvas must not become its implicit minimum height.
      */}
      <div
        ref={terminalRegionRef}
        onMouseDownCapture={pressPane}
        id={terminalRegionId}
        className={cn(
          "relative min-h-0 flex-1 overflow-hidden px-1.5 pb-0.5 pt-0.5",
          active && !tailReady && "invisible",
        )}
      >
        <div
          ref={containerRef}
          {...paneMenu.handlers}
          data-testid={`agentic-terminal-host-${name}`}
          // Read by ./index.css, which anchors the contents to the bottom for
          // the length of a drag — see the rule there for why that is the side
          // the unused ground belongs on.
          data-layout-busy={layoutBusy ? "true" : "false"}
          /*
           * Nothing sideways, ever. The terminal is fitted to this element (see
           * MIN_REAL_COLS), so there is no wider surface to scroll to — and a
           * pane that could scroll sideways is a pane drawing past its own
           * edge, which is the thing that read as terminals standing on one
           * another.
           */
          className="agentic-terminal-host h-full min-h-0 w-full overflow-hidden"
        />
        <PaneConversationDialog
          terminal={name}
          open={historyOpen}
          onOpenChange={setHistoryOpen}
        />
        {/*
          The pane says it is starting, instead of being a black rectangle.

          Only until the agent's first byte, and only while nothing has gone
          wrong: an exited or unreachable pane has its own, more specific
          answer in the header and must not be covered by a hopeful spinner.
          `pointer-events-none` throughout — the terminal underneath keeps
          every click and keystroke, so typing into a pane that is still
          booting behaves exactly as it did before.
        */}
        {/*
          Proof that this pane was handed a prompt, drawn by the app rather
          than read out of the agent's screen.

          Sits INSIDE the terminal region so it points at the pane it is
          talking about, and above the scrollbar overlay so a fleet of panes
          cannot bury it. It is the answer to the failure this whole file keeps
          circling: a delivery that really happened, on a pane that showed
          nothing, told to a user who then had every reason to believe Jarvis
          had invented it. See ./PromptReceipt.
        */}
        {receipt && receipt.at !== null && receipt.at !== dismissedAt && (
          <PromptReceipt
            key={receipt.at}
            terminal={name}
            workspaceId={workspaceId}
            at={receipt.at}
            preview={receipt.text}
            chars={receipt.chars}
            submitted={receipt.submitted}
            onDismiss={() => setDismissedAt(receipt.at)}
          />
        )}
        {!painted && visibleStatus === "connecting" && (
          <div
            data-testid={`agentic-pane-starting-${name}`}
            className="pointer-events-none absolute inset-0 flex items-center justify-center"
          >
            <div
              // `rounded-lg` is the radius every card-shaped thing in the
              // product takes; `rounded-xl` was a fourth step nothing else
              // used. The spinner is decoration beside the sentence, so it
              // wears the same meta ink — `--primary` is a fill, and an icon
              // brighter than the words it sits next to is a bug.
              className="flex items-center gap-2 rounded-lg border px-4 py-2.5 text-sm text-muted-foreground"
              style={{ background: chrome.shell, borderColor: chrome.border }}
            >
              <Loader2 className="h-4 w-4 animate-spin" />
              <span>{fill(t("agentic_grid.pane.starting"), { agent: displayName })}</span>
            </div>
          </div>
        )}
      </div>
      {dragging && carrying === "skill" && !attaching && (
        <SkillDropCard skill={skillInFlight} target={name}
          blocked={Boolean(skillInFlight?.multiline) && !termRef.current?.modes.bracketedPasteMode} />
      )}
      {((dragging && carrying !== "skill") || attaching) && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center bg-background backdrop-blur-[2px]">
          {/* A real card fill separates this from the pane behind it, so it
              needs no rim of its own — and the two glyphs are decoration
              beside their sentence, not marks, so they take the meta ink. */}
          <div className="flex items-center gap-2 rounded-lg bg-card px-4 py-2.5 text-sm text-foreground">
            {attaching ? (
              <>
                <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                <span>{fill(t("agentic_grid.pane.attaching"), { pane: name })}</span>
              </>
            ) : (
              <>
                <Paperclip className="h-4 w-4 text-muted-foreground" />
                <span>
                  {t("agentic_grid.pane.drop_hint_before")}<strong>{name}</strong>
                  {t("agentic_grid.pane.drop_hint_after")}
                </span>
              </>
            )}
          </div>
        </div>
      )}
      {/*
        The focused tile's inner edge line, drawn ABOVE everything in the pane.
        As an inset shadow on the frame it sat underneath the title row, whose
        own translucent ground dimmed it: the blue read darker along the top
        than down the terminal (maintainer, 2026-09-30). One layer on top keeps
        the line the same brightness all the way round.
      */}
      {minimal && focused && markFocus && !dragging && !justDelivered && (
        <div
          aria-hidden="true"
          data-testid={`pane-focus-ring-${name}`}
          className="pointer-events-none absolute inset-0 z-[45]"
          style={{ boxShadow: `inset 0 0 0 1px ${tile.focus}` }}
        />
      )}
    </div>
  );
}
