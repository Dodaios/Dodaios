/**
 * Keep a borrowed xterm painting while the Verse window shows it.
 *
 * xterm's RenderService pauses itself when its own IntersectionObserver says
 * the screen element is off screen, and `refresh` then draws nothing. The
 * IDE tile is off screen for the whole time the office covers it, and moving
 * the element into the window does not reliably deliver a new "intersecting"
 * entry in the desktop WebView. The buffer still takes the bytes — including
 * the echo of a key the user just typed — and the canvas keeps the previous
 * frame. Waking it, and ignoring that observer until the window gives the
 * element back, is what makes the window update on the same frame as the IDE.
 */
import type { Terminal } from "@xterm/xterm";

interface PausableRenderService {
  _isPaused?: boolean;
  _needsFullRefresh?: boolean;
  _rowCount?: number;
  _pausedResizeTask?: { flush?: () => void };
  _handleIntersectionChange?: (entry: IntersectionObserverEntry) => void;
  refreshRows?: (start: number, end: number, isRedrawOnly?: boolean) => void;
}

function renderService(term: Terminal): PausableRenderService | undefined {
  return (term as unknown as { _core?: { _renderService?: PausableRenderService } })._core
    ?._renderService;
}

function paintNow(term: Terminal, service: PausableRenderService): void {
  const rows = service._rowCount ?? term.rows;
  service._needsFullRefresh = false;
  try {
    if (typeof service.refreshRows === "function" && rows > 0) {
      service.refreshRows(0, rows - 1);
      return;
    }
  } catch {
    /* the renderer is being torn down — nothing left to paint */
  }
  if (rows > 0) {
    try {
      term.refresh(0, rows - 1);
    } catch {
      /* same teardown */
    }
  }
}

/** Unpause a renderer that still believes it is off screen. A no-op while it is already drawing. */
export function wakePresentedRenderer(term: Terminal): void {
  const service = renderService(term);
  if (!service || service._isPaused !== true) return;
  service._isPaused = false;
  try {
    service._pausedResizeTask?.flush?.();
  } catch {
    /* a resize queued while paused belongs to a renderer that is going away */
  }
  paintNow(term, service);
}

/**
 * Hold the renderer awake for the life of a presentation.
 *
 * The observer stays attached to the screen element. A late "not intersecting"
 * entry — queued while the element still sat in the hidden tile — would pause
 * it again between keystrokes. Returns the restore, which the release of the
 * window calls so the tile can park normally once the element is back.
 */
export function keepPresentedRendererAwake(term: Terminal): () => void {
  const service = renderService(term);
  if (!service || typeof service._handleIntersectionChange !== "function") {
    wakePresentedRenderer(term);
    if (term.rows > 0) {
      try {
        term.refresh(0, term.rows - 1);
      } catch {
        /* tearing down */
      }
    }
    return () => {};
  }
  const original = service._handleIntersectionChange;
  const ignore = function (this: PausableRenderService) {
    this._isPaused = false;
  };
  service._handleIntersectionChange = ignore;
  service._isPaused = false;
  try {
    service._pausedResizeTask?.flush?.();
  } catch {
    /* see wakePresentedRenderer */
  }
  paintNow(term, service);
  return () => {
    if (service._handleIntersectionChange === ignore) {
      service._handleIntersectionChange = original;
    }
  };
}
