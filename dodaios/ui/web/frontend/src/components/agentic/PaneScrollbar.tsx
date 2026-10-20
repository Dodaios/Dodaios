/**
 * The scrollbar of an Agentic IDE terminal pane.
 *
 * Hidden until the reader scrolls (or points at the pane's right edge), then it
 * fades in and can be used to scroll up and down; it fades out again after a
 * short pause. It works in the two shapes a coding CLI's history takes:
 *
 * - `history`: the terminal itself holds the scrollback (a shell, Codex with
 *   `--no-alt-screen`, Claude Code without its full-screen renderer). The thumb
 *   is exact: it is xterm's own viewport, dragging seeks, the track pages.
 * - `app`: a full-screen CLI on the alternate screen (Claude Code with
 *   `CLAUDE_CODE_NO_FLICKER`, Codex by default) keeps its history inside its own
 *   UI, and the terminal has nothing to scroll. Measured 2026-10-19: both
 *   negotiate mouse reporting (?1003/?1006). The bar then drives the CLI with
 *   real wheel notches through xterm's own mouse encoder, exactly as the
 *   physical wheel would. No position is shown there, because none is knowable
 *   from outside the CLI: there is no thumb at all, only the arrows and the
 *   track halves, which step and page. (A centred "jog" grip shipped first and
 *   was read as "you are in the middle" while the pane sat at its end.)
 *
 * The panes start Claude Code and Codex in their classic renderers (see
 * `pane_sessions.settings_file` and the Codex `launch_args`), so they normally
 * run in `history` mode; `app` mode remains for other full-screen CLIs.
 *
 * Wheel notches are only ever sent while the CLI reports the mouse. On an
 * alternate screen WITHOUT mouse reporting xterm turns a wheel into arrow keys,
 * which a coding CLI reads as "recall the previous prompt"; there the bar stays
 * hidden instead.
 */
import { ChevronDown, ChevronUp } from "lucide-react";
import {
  useCallback,
  useEffect,
  useRef,
  useState,
  type MutableRefObject,
  type PointerEvent as ReactPointerEvent,
} from "react";
import type { Terminal } from "@xterm/xterm";
import { cn } from "@/lib/utils";

export type PaneScrollMode = "history" | "app" | "none";

export type PaneScrollState = {
  mode: PaneScrollMode;
  /** First line in view (history mode). */
  viewportY: number;
  /** Lines above the live screen (history mode). */
  baseY: number;
  rows: number;
};

/** How long the bar stays after the last scroll or hover, in ms. */
export const SCROLLBAR_LINGER_MS = 1800;
/** Width of the right-edge strip that reveals the bar on hover, in px. */
const EDGE_REVEAL_PX = 28;
/** Auto-repeat of a held arrow or track press. */
const REPEAT_DELAY_MS = 320;
const REPEAT_INTERVAL_MS = 60;
/** Smallest thumb in history mode, so a long history keeps a grabbable thumb. */
const MIN_THUMB_PX = 28;

/** What the pane can be scrolled by, read fresh from the terminal. */
export function readPaneScrollState(term: Terminal | null): PaneScrollState {
  const none: PaneScrollState = { mode: "none", viewportY: 0, baseY: 0, rows: 0 };
  if (!term) return none;
  const buffer = term.buffer?.active;
  if (!buffer) return none;
  const rows = Math.max(1, term.rows || 1);
  if (buffer.type === "normal") {
    if (buffer.baseY > 0) {
      return { mode: "history", viewportY: buffer.viewportY, baseY: buffer.baseY, rows };
    }
    return { ...none, rows };
  }
  const tracking = term.modes?.mouseTrackingMode ?? "none";
  return { mode: tracking === "none" ? "none" : "app", viewportY: 0, baseY: 0, rows };
}

/**
 * Send `count` wheel notches to a full-screen CLI, the way the real wheel does.
 *
 * Dispatched on xterm's screen element so xterm encodes them in whatever mouse
 * protocol the CLI negotiated. Re-checked per notch: should the CLI drop mouse
 * reporting mid-gesture, nothing else may be sent (see the module comment).
 */
export function sendWheelNotches(term: Terminal, direction: -1 | 1, count: number): number {
  const screen = term.element?.querySelector<HTMLElement>(".xterm-screen");
  if (!screen) return 0;
  const rect = screen.getBoundingClientRect();
  let sent = 0;
  for (let i = 0; i < count; i++) {
    if (readPaneScrollState(term).mode !== "app") break;
    screen.dispatchEvent(
      new WheelEvent("wheel", {
        deltaY: direction,
        deltaMode: WheelEvent.DOM_DELTA_LINE,
        clientX: rect.left + rect.width / 2,
        clientY: rect.top + rect.height / 2,
        bubbles: true,
        cancelable: true,
      }),
    );
    sent += 1;
  }
  return sent;
}

type Props = {
  termRef: MutableRefObject<Terminal | null>;
  /** Bumped whenever the pane builds a new Terminal. */
  epoch: number;
  /** The pane's terminal region: scrolling or hovering there reveals the bar. */
  regionRef: MutableRefObject<HTMLElement | null>;
  labels: { bar: string; up: string; down: string };
  testId?: string;
};

export function PaneScrollbar({ termRef, epoch, regionRef, labels, testId }: Props) {
  const [state, setState] = useState<PaneScrollState>(() => readPaneScrollState(termRef.current));
  const [shown, setShown] = useState(false);
  const [hovered, setHovered] = useState(false);
  const [dragging, setDragging] = useState(false);
  const trackRef = useRef<HTMLDivElement | null>(null);
  const hideTimer = useRef<number | null>(null);
  const repeatTimer = useRef<number | null>(null);
  const stateRef = useRef(state);
  stateRef.current = state;

  const refresh = useCallback(() => {
    const next = readPaneScrollState(termRef.current);
    setState((prev) =>
      prev.mode === next.mode &&
      prev.viewportY === next.viewportY &&
      prev.baseY === next.baseY &&
      prev.rows === next.rows
        ? prev
        : next,
    );
    return next;
  }, [termRef]);

  const reveal = useCallback(() => {
    if (refresh().mode === "none") return;
    setShown(true);
    if (hideTimer.current !== null) window.clearTimeout(hideTimer.current);
    hideTimer.current = window.setTimeout(() => {
      hideTimer.current = null;
      setShown(false);
    }, SCROLLBAR_LINGER_MS);
  }, [refresh]);

  // Follow the terminal: its scroll, its writes, its buffer switches.
  useEffect(() => {
    const term = termRef.current;
    refresh();
    if (!term) return;
    let frame: number | null = null;
    const soon = () => {
      if (frame !== null) return;
      frame = window.requestAnimationFrame(() => {
        frame = null;
        refresh();
      });
    };
    const subs = [
      term.onScroll?.(soon),
      term.onWriteParsed?.(soon),
      term.onResize?.(soon),
      term.buffer?.onBufferChange?.(soon),
    ];
    return () => {
      if (frame !== null) window.cancelAnimationFrame(frame);
      for (const sub of subs) sub?.dispose();
    };
  }, [termRef, epoch, refresh]);

  // While the bar is on screen, re-read the position a few times a second. A
  // wheel scroll on an idle pane writes nothing, and the 2026-08 rail showed
  // stale positions for exactly that reason.
  useEffect(() => {
    if (!shown && !hovered && !dragging) return;
    const timer = window.setInterval(refresh, 200);
    return () => window.clearInterval(timer);
  }, [shown, hovered, dragging, refresh]);

  // Scrolling inside the pane, or pointing at its right edge, shows the bar.
  useEffect(() => {
    const region = regionRef.current;
    if (!region) return;
    const onWheel = (event: WheelEvent) => {
      if (event.ctrlKey || event.metaKey) return;
      if (Math.abs(event.deltaY) <= Math.abs(event.deltaX)) return;
      reveal();
    };
    const onMove = (event: MouseEvent) => {
      const rect = region.getBoundingClientRect();
      if (rect.right - event.clientX <= EDGE_REVEAL_PX) reveal();
    };
    region.addEventListener("wheel", onWheel, { capture: true, passive: true });
    region.addEventListener("mousemove", onMove, { capture: true, passive: true });
    return () => {
      region.removeEventListener("wheel", onWheel, { capture: true });
      region.removeEventListener("mousemove", onMove, { capture: true });
    };
  }, [regionRef, reveal]);

  const stopRepeat = useCallback(() => {
    if (repeatTimer.current !== null) {
      window.clearTimeout(repeatTimer.current);
      repeatTimer.current = null;
    }
  }, []);

  useEffect(
    () => () => {
      stopRepeat();
      if (hideTimer.current !== null) window.clearTimeout(hideTimer.current);
    },
    [stopRepeat],
  );

  /** One step: lines in history mode, notches in app mode. */
  const step = useCallback(
    (direction: -1 | 1, size: "line" | "page") => {
      const term = termRef.current;
      if (!term) return;
      const current = readPaneScrollState(term);
      if (current.mode === "history") {
        if (size === "page") term.scrollPages(direction);
        else term.scrollLines(direction * 3);
      } else if (current.mode === "app") {
        const notches = size === "page" ? Math.max(3, Math.round(current.rows / 3)) : 1;
        sendWheelNotches(term, direction, notches);
      }
      reveal();
    },
    [termRef, reveal],
  );

  /** Press-and-hold: step now, then keep stepping until the pointer lets go. */
  const holdStep = useCallback(
    (event: ReactPointerEvent, direction: -1 | 1, size: "line" | "page") => {
      if (event.button > 0) return;
      event.preventDefault();
      event.stopPropagation();
      stopRepeat();
      step(direction, size);
      const again = (delay: number) => {
        repeatTimer.current = window.setTimeout(() => {
          step(direction, size);
          again(REPEAT_INTERVAL_MS);
        }, delay);
      };
      again(REPEAT_DELAY_MS);
      const release = () => {
        stopRepeat();
        window.removeEventListener("pointerup", release);
        window.removeEventListener("pointercancel", release);
      };
      window.addEventListener("pointerup", release);
      window.addEventListener("pointercancel", release);
    },
    [step, stopRepeat],
  );

  const trackHeight = () => trackRef.current?.clientHeight ?? 0;

  const historyThumb = () => {
    const h = trackHeight();
    const total = state.baseY + state.rows;
    const size = Math.min(h, Math.max(MIN_THUMB_PX, (h * state.rows) / Math.max(1, total)));
    const travel = Math.max(0, h - size);
    const top = state.baseY > 0 ? (travel * state.viewportY) / state.baseY : travel;
    return { size, top, travel };
  };

  /** Drag the thumb. The mode is fixed at the press: a flip mid-drag ends it. */
  const startDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button > 0) return;
    const term = termRef.current;
    if (!term) return;
    event.preventDefault();
    event.stopPropagation();
    const mode = readPaneScrollState(term).mode;
    if (mode !== "history") return;
    const target = event.currentTarget;
    target.setPointerCapture?.(event.pointerId);
    const startY = event.clientY;
    const startLine = term.buffer.active.viewportY;
    const { travel } = historyThumb();
    const baseY = Math.max(1, term.buffer.active.baseY);
    setDragging(true);

    const move = (ev: PointerEvent) => {
      const dy = ev.clientY - startY;
      if (readPaneScrollState(term).mode !== mode) return;
      if (travel <= 0) return;
      const line = Math.round(startLine + (dy * baseY) / travel);
      term.scrollToLine(Math.max(0, Math.min(term.buffer.active.baseY, line)));
      reveal();
    };
    const end = () => {
      target.removeEventListener("pointermove", move);
      target.removeEventListener("pointerup", end);
      target.removeEventListener("pointercancel", end);
      setDragging(false);
      reveal();
    };
    target.addEventListener("pointermove", move);
    target.addEventListener("pointerup", end);
    target.addEventListener("pointercancel", end);
  };

  /** A press on the track (not the thumb) pages towards the press. */
  const pressTrack = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.target !== event.currentTarget) return;
    const rect = event.currentTarget.getBoundingClientRect();
    const y = event.clientY - rect.top;
    let direction: -1 | 1;
    if (state.mode === "history") {
      const { size, top } = historyThumb();
      direction = y < top ? -1 : 1;
      if (y >= top && y <= top + size) return;
    } else {
      direction = y < rect.height / 2 ? -1 : 1;
    }
    holdStep(event, direction, "page");
  };

  // Nothing to scroll: no bar at all, not even an invisible one in the way.
  if (state.mode === "none") return null;

  const visible = shown || hovered || dragging;
  const thumb = state.mode === "history" ? historyThumb() : null;
  const atTop = state.mode === "history" && state.viewportY <= 0;
  const atBottom = state.mode === "history" && state.viewportY >= state.baseY;

  return (
    <div
      data-testid={testId}
      data-mode={state.mode}
      data-visible={visible ? "true" : "false"}
      role="scrollbar"
      aria-label={labels.bar}
      aria-orientation="vertical"
      aria-valuemin={0}
      aria-valuemax={state.mode === "history" ? state.baseY : undefined}
      aria-valuenow={state.mode === "history" ? state.viewportY : undefined}
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => {
        setHovered(false);
        reveal();
      }}
      onMouseDown={(e) => e.stopPropagation()}
      onWheel={(e) => {
        // A wheel over the bar itself scrolls the pane like a wheel anywhere else.
        if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return;
        step(e.deltaY < 0 ? -1 : 1, "line");
      }}
      className={cn(
        "absolute bottom-1 right-0.5 top-1 z-20 flex w-3.5 select-none flex-col items-center gap-0.5 rounded-full",
        "transition-opacity duration-200",
        visible ? "pointer-events-auto opacity-100" : "pointer-events-none opacity-0",
        (hovered || dragging) && "bg-[hsl(var(--muted)/0.55)]",
      )}
    >
      <button
        type="button"
        tabIndex={-1}
        aria-label={labels.up}
        data-testid={testId ? `${testId}-up` : undefined}
        disabled={atTop}
        onPointerDown={(e) => holdStep(e, -1, "line")}
        className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:text-foreground disabled:opacity-30"
      >
        <ChevronUp className="h-3 w-3" strokeWidth={2.5} />
      </button>
      <div
        ref={trackRef}
        data-testid={testId ? `${testId}-track` : undefined}
        onPointerDown={pressTrack}
        className="relative w-full min-h-0 flex-1 cursor-default"
      >
        {thumb && (
          <div
            data-testid={testId ? `${testId}-thumb` : undefined}
            onPointerDown={startDrag}
            className={cn(
              "absolute left-1/2 w-1.5 -translate-x-1/2 rounded-full",
              "bg-[hsl(var(--muted-foreground)/0.6)] hover:w-2 hover:bg-[hsl(var(--muted-foreground))]",
              dragging && "w-2 bg-[hsl(var(--foreground)/0.75)]",
            )}
            style={{ top: thumb.top, height: thumb.size }}
          />
        )}
      </div>
      <button
        type="button"
        tabIndex={-1}
        aria-label={labels.down}
        data-testid={testId ? `${testId}-down` : undefined}
        disabled={atBottom}
        onPointerDown={(e) => holdStep(e, 1, "line")}
        className="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full text-muted-foreground hover:text-foreground disabled:opacity-30"
      >
        <ChevronDown className="h-3 w-3" strokeWidth={2.5} />
      </button>
    </div>
  );
}
