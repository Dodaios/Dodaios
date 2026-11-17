/**
 * Watching the assistant draw.
 *
 * The assistant's `whiteboard` tool writes a whole diagram in one call, so
 * its work reaches the open board as one change. Shown at once it would just
 * appear. Instead the new elements are put on the board one piece at a time
 * (a frame, then each box with its label, then the arrows), and the
 * assistant's cursor, with its name, moves to each piece as it lands, the
 * way a colleague's cursor moves on a shared canvas.
 *
 * Only what is new to this editor is played this way; a change to something
 * already on the board is drawn at once. The person can keep drawing while it
 * plays: every step starts from what the editor holds at that moment, so
 * nothing the person does in between is lost. The pieces carry the server's
 * versions, so the board's sync sees nothing to save in them.
 */
import { CaptureUpdateAction, getCommonBounds } from "@excalidraw/excalidraw";
import type { ExcalidrawImperativeAPI } from "@excalidraw/excalidraw/types";

import type { BoardElement } from "../boardApi";

/**
 * The id the assistant's cursor is kept under among the editor's
 * collaborators. The editor colours a cursor by a hash of its id (hue =
 * hash % 37 * 10), not by the colour handed in; this id lands on hue 40, the
 * brand's gold.
 */
export const ASSISTANT_CURSOR_ID = "dodaios-assistant-14";
/** How long the whole play may take, however many pieces there are. */
const PLAY_MS = 2_600;
const STEP_MIN_MS = 45;
const STEP_MAX_MS = 260;
/** How long the cursor stays once the last piece landed. */
const LINGER_MS = 1_400;
/** A new element counts as the assistant's fresh work on opening for this long. */
export const FRESH_MS = 90_000;

/** The room the board's own controls take at the edges, kept free when fitting. */
export const CANVAS_OFFSETS = { top: 64, right: 24, bottom: 88, left: 24 };

/** The assistant's colour on the board: the brand's gold. */
const CURSOR_COLOR = { background: "#D4A72C", stroke: "#8A6A12" };

type Element = BoardElement & {
  containerId?: string | null;
  frameId?: string | null;
  boundElements?: readonly { id: string; type: string }[] | null;
  customData?: Record<string, unknown> | null;
  updated?: number;
};

/** One piece of the play: elements that land together. */
export interface Piece {
  ids: string[];
}

/** Did the assistant draw this element (its tool marks what it makes)? */
export function isAssistantElement(element: BoardElement): boolean {
  const custom = (element as Element).customData;
  return Boolean(custom && typeof custom === "object" && custom.by === "assistant");
}

/** Elements the assistant drew in the last `FRESH_MS` (played when the board opens). */
export function freshAssistantIds(elements: readonly BoardElement[], now = Date.now()): Set<string> {
  const fresh = new Set<string>();
  for (const element of elements) {
    const updated = (element as Element).updated ?? 0;
    if (!element.isDeleted && isAssistantElement(element) && now - updated < FRESH_MS && updated <= now + 5_000) {
      fresh.add(element.id);
    }
  }
  // A label goes with its box, so a fresh box brings its label even when the
  // label alone was not marked.
  for (const element of elements) {
    const container = (element as Element).containerId;
    if (container && fresh.has(container)) fresh.add(element.id);
  }
  return fresh;
}

const LINEAR = new Set(["arrow", "line"]);

/**
 * The order the new elements land in: frames first (the regions), then the
 * things in them in the board's own order, each with its label, and the
 * arrows last, once both their ends are there.
 */
export function planPieces(order: readonly BoardElement[], fresh: ReadonlySet<string>): Piece[] {
  const byId = new Map(order.map((element) => [element.id, element as Element]));
  const labels = new Map<string, string[]>();
  for (const element of order) {
    const container = (element as Element).containerId;
    if (container && fresh.has(element.id) && fresh.has(container)) {
      labels.set(container, [...(labels.get(container) ?? []), element.id]);
    }
  }
  const inLabel = new Set([...labels.values()].flat());
  const frames: Piece[] = [];
  const things: Piece[] = [];
  const links: Piece[] = [];
  for (const element of order) {
    if (!fresh.has(element.id) || element.isDeleted || inLabel.has(element.id)) continue;
    if (!byId.has(element.id)) continue;
    const piece = { ids: [element.id, ...(labels.get(element.id) ?? [])] };
    if (element.type === "frame" || element.type === "magicframe") frames.push(piece);
    else if (LINEAR.has(element.type)) links.push(piece);
    else things.push(piece);
  }
  return [...frames, ...things, ...links];
}

/** The pause between two pieces, so the whole play takes about `PLAY_MS`. */
export function stepDelay(pieces: number): number {
  if (pieces <= 1) return STEP_MIN_MS;
  return Math.round(Math.min(STEP_MAX_MS, Math.max(STEP_MIN_MS, PLAY_MS / pieces)));
}

interface Play {
  order: BoardElement[];
  byId: Map<string, BoardElement>;
  pieces: Piece[];
  shown: Set<string>;
  next: number;
  timer: ReturnType<typeof setTimeout> | null;
}

export interface LiveBuildOptions {
  api: () => ExcalidrawImperativeAPI | null;
  /** The assistant's name, on its cursor. */
  name: () => string;
  /** The person moved or drew in the last moments: the view is theirs then. */
  personBusy: () => boolean;
  /** The assistant is drawing (true) or done (false). */
  onActive?: (active: boolean) => void;
}

export class LiveBuild {
  private play: Play | null = null;
  private cursor = { x: 0, y: 0, tx: 0, ty: 0, shown: false };
  private cursorFrame = 0;
  private lingerTimer: ReturnType<typeof setTimeout> | null = null;
  private disposed = false;

  constructor(private readonly options: LiveBuildOptions) {}

  get playing(): boolean {
    return this.play !== null;
  }

  /**
   * Put `order` (the merged scene) on the board, holding back `fresh` and
   * letting it land piece by piece. A play still running lands at once first.
   */
  start(order: readonly BoardElement[], fresh: ReadonlySet<string>, opts: { follow?: boolean } = {}): void {
    const editor = this.options.api();
    if (!editor || this.disposed) return;
    this.finish();
    const pieces = planPieces(order, fresh);
    if (pieces.length === 0) {
      editor.updateScene({ elements: order as never, captureUpdate: CaptureUpdateAction.NEVER });
      return;
    }
    const held = new Set(pieces.flatMap((piece) => piece.ids));
    this.play = {
      order: [...order],
      byId: new Map(order.map((element) => [element.id, element])),
      pieces,
      shown: new Set(),
      next: 0,
      timer: null,
    };
    editor.updateScene({
      elements: order.filter((element) => !held.has(element.id)) as never,
      captureUpdate: CaptureUpdateAction.NEVER,
    });
    this.options.onActive?.(true);
    if (opts.follow !== false) this.follow(order.filter((element) => held.has(element.id)));
    const first = this.centerOf(pieces[0].ids);
    if (first && !this.cursor.shown) {
      // The cursor enters from a little up and left of the first piece.
      this.cursor = { x: first.x - 80, y: first.y - 60, tx: first.x, ty: first.y, shown: true };
    }
    this.step();
  }

  /** Land whatever is still held back at once (a new change arrived, the board closes). */
  finish(): void {
    const play = this.play;
    if (!play) return;
    if (play.timer) clearTimeout(play.timer);
    for (const piece of play.pieces.slice(play.next)) for (const id of piece.ids) play.shown.add(id);
    play.next = play.pieces.length;
    this.render(play);
    this.play = null;
    this.options.onActive?.(false);
  }

  /** Work again after `dispose` (an effect that runs twice in development). */
  revive(): void {
    this.disposed = false;
  }

  dispose(): void {
    this.finish();
    this.disposed = true;
    if (this.cursorFrame) cancelAnimationFrame(this.cursorFrame);
    if (this.lingerTimer) clearTimeout(this.lingerTimer);
  }

  private step = () => {
    const play = this.play;
    if (!play || this.disposed) return;
    play.timer = null;
    const piece = play.pieces[play.next];
    if (!piece) {
      this.play = null;
      this.options.onActive?.(false);
      this.lingerTimer = setTimeout(() => this.hideCursor(), LINGER_MS);
      return;
    }
    for (const id of piece.ids) play.shown.add(id);
    play.next += 1;
    this.render(play);
    const at = this.centerOf(piece.ids);
    if (at) this.moveCursor(at.x, at.y, piece.ids[0]);
    play.timer = setTimeout(this.step, stepDelay(play.pieces.length));
  };

  /** The editor's elements plus the pieces landed so far, in the scene's order. */
  private render(play: Play): void {
    const editor = this.options.api();
    if (!editor) return;
    const current = editor.getSceneElementsIncludingDeleted() as unknown as BoardElement[];
    const now = new Map(current.map((element) => [element.id, element]));
    const placed = new Set<string>();
    const next: BoardElement[] = [];
    for (const element of play.order) {
      const held = now.get(element.id);
      if (held) {
        next.push(held);
        placed.add(element.id);
      } else if (play.shown.has(element.id)) {
        next.push(play.byId.get(element.id) as BoardElement);
        placed.add(element.id);
      }
    }
    // What the person drew meanwhile stays, on top.
    for (const element of current) if (!placed.has(element.id)) next.push(element);
    editor.updateScene({ elements: next as never, captureUpdate: CaptureUpdateAction.NEVER });
  }

  private centerOf(ids: readonly string[]): { x: number; y: number } | null {
    const play = this.play;
    const elements = ids
      .map((id) => play?.byId.get(id))
      .filter((element): element is BoardElement => Boolean(element));
    if (elements.length === 0) return null;
    const [x1, y1, x2, y2] = getCommonBounds(elements as never);
    return { x: (x1 + x2) / 2, y: (y1 + y2) / 2 };
  }

  /** Bring the new work into view, unless the person is busy with the view. */
  private follow(elements: BoardElement[]): void {
    const editor = this.options.api();
    if (!editor || elements.length === 0 || this.options.personBusy()) return;
    const state = editor.getAppState();
    const [x1, y1, x2, y2] = getCommonBounds(elements as never);
    const zoom = state.zoom.value;
    const left = -state.scrollX;
    const top = -state.scrollY;
    const right = left + state.width / zoom;
    const bottom = top + state.height / zoom;
    const inView = x1 >= left && y1 >= top && x2 <= right && y2 <= bottom;
    if (inView) return;
    const all = editor.getSceneElements();
    editor.scrollToContent([...all, ...(elements as never[])], {
      fitToViewport: true,
      viewportZoomFactor: 0.85,
      animate: true,
      duration: 450,
      maxZoom: 1,
      canvasOffsets: CANVAS_OFFSETS,
    });
  }

  private moveCursor(x: number, y: number, selected: string): void {
    this.cursor.tx = x;
    this.cursor.ty = y;
    this.cursor.shown = true;
    this.selected = selected;
    if (this.lingerTimer) {
      clearTimeout(this.lingerTimer);
      this.lingerTimer = null;
    }
    if (!this.cursorFrame) this.cursorFrame = requestAnimationFrame(this.glideCursor);
  }

  private selected = "";

  private glideCursor = () => {
    this.cursorFrame = 0;
    const c = this.cursor;
    if (!c.shown || this.disposed) return;
    c.x += (c.tx - c.x) * 0.3;
    c.y += (c.ty - c.y) * 0.3;
    this.drawCursor();
    if (Math.abs(c.tx - c.x) > 0.5 || Math.abs(c.ty - c.y) > 0.5) {
      this.cursorFrame = requestAnimationFrame(this.glideCursor);
    }
  };

  private drawCursor(): void {
    const editor = this.options.api();
    if (!editor) return;
    const collaborators = new Map();
    collaborators.set(ASSISTANT_CURSOR_ID, {
      id: ASSISTANT_CURSOR_ID,
      socketId: ASSISTANT_CURSOR_ID,
      username: this.options.name(),
      color: CURSOR_COLOR,
      pointer: { x: this.cursor.x, y: this.cursor.y, tool: "pointer" },
      button: "up",
      selectedElementIds: this.selected ? { [this.selected]: true } : {},
    });
    editor.updateScene({ collaborators } as never);
  }

  private hideCursor(): void {
    this.lingerTimer = null;
    this.cursor.shown = false;
    this.selected = "";
    this.options.api()?.updateScene({ collaborators: new Map() } as never);
  }
}
