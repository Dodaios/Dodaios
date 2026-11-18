/**
 * Watching the assistant draw.
 *
 * The assistant's `whiteboard` tool writes a whole diagram in one call, so
 * its work reaches the open board as one change. Shown at once it would just
 * appear. Instead the new elements are put on the board one piece at a time
 * (a frame, then each box with its label, then the arrows), on the shared
 * live-build timing (`revealDelays`), while the shared presence (the cursor,
 * the name tag and the frame, `BoardPresence`) glides to each piece as it
 * lands. This class only places the pieces; it tells a listener where each
 * piece is so the presence can follow.
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
import { LIVE_TIMING, prefersReducedMotion, revealDelays } from "../../live/playback";

/** A new element counts as the assistant's fresh work on opening for this long. */
export const FRESH_MS = 90_000;

/** The room the board's own controls take at the edges, kept free when fitting. */
export const CANVAS_OFFSETS = { top: 64, right: 24, bottom: 88, left: 24 };

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

/** A piece as the presence sees it: where it sits on the canvas, in scene units. */
export interface PieceBox {
  /** The piece's first element: what its marker is named after. */
  id: string;
  x: number;
  y: number;
  w: number;
  h: number;
}

/** Who follows the play: the shared presence (`BoardPresence`). */
export interface BuildListener {
  /** A play began: one box per piece, in the order they land. */
  begin: (boxes: PieceBox[]) => void;
  /** The play was cut short and landed at once. */
  finished: () => void;
  /** The last piece landed on time. */
  done: () => void;
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
  return groupPieces([...frames, ...things, ...links]);
}

/** At most `LIVE_TIMING.maxUnits` pieces: consecutive ones land together when there are more. */
export function groupPieces(pieces: Piece[], max: number = LIVE_TIMING.maxUnits): Piece[] {
  if (pieces.length <= max) return pieces;
  const size = Math.ceil(pieces.length / max);
  const out: Piece[] = [];
  for (let i = 0; i < pieces.length; i += size) out.push({ ids: pieces.slice(i, i + size).flatMap((piece) => piece.ids) });
  return out;
}

interface Play {
  order: BoardElement[];
  byId: Map<string, BoardElement>;
  pieces: Piece[];
  shown: Set<string>;
  next: number;
  timers: ReturnType<typeof setTimeout>[];
}

export interface LiveBuildOptions {
  api: () => ExcalidrawImperativeAPI | null;
  /** The person moved or drew in the last moments: the view is theirs then. */
  personBusy: () => boolean;
  /** The assistant is drawing (true) or done (false). */
  onActive?: (active: boolean) => void;
}

export class LiveBuild {
  private play: Play | null = null;
  private listener: BuildListener | null = null;
  private disposed = false;

  constructor(private readonly options: LiveBuildOptions) {}

  get playing(): boolean {
    return this.play !== null;
  }

  /** The presence that follows the play; null to detach it. */
  attach(listener: BuildListener | null): void {
    this.listener = listener;
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
    const play: Play = {
      order: [...order],
      byId: new Map(order.map((element) => [element.id, element])),
      pieces,
      shown: new Set(),
      next: 0,
      timers: [],
    };
    this.play = play;
    editor.updateScene({
      elements: order.filter((element) => !held.has(element.id)) as never,
      captureUpdate: CaptureUpdateAction.NEVER,
    });
    this.options.onActive?.(true);
    if (opts.follow !== false) this.follow(order.filter((element) => held.has(element.id)));
    this.listener?.begin(pieces.map((piece) => this.boxOf(play, piece.ids)));
    if (prefersReducedMotion()) {
      // The result at once; only the presence moves.
      this.finish();
      this.listener?.done();
      return;
    }
    revealDelays(pieces.length).forEach((delay, i) => {
      play.timers.push(setTimeout(() => this.land(play, i), delay));
    });
  }

  /** Land whatever is still held back at once (a new change arrived, the person acted, the board closes). */
  finish(): void {
    const play = this.play;
    if (!play) return;
    for (const timer of play.timers) clearTimeout(timer);
    for (const piece of play.pieces.slice(play.next)) for (const id of piece.ids) play.shown.add(id);
    play.next = play.pieces.length;
    this.render(play);
    this.play = null;
    this.options.onActive?.(false);
    this.listener?.finished();
  }

  /** Work again after `dispose` (an effect that runs twice in development). */
  revive(): void {
    this.disposed = false;
  }

  dispose(): void {
    this.finish();
    this.disposed = true;
  }

  private land(play: Play, index: number): void {
    if (this.play !== play || this.disposed) return;
    for (const id of play.pieces[index].ids) play.shown.add(id);
    play.next = index + 1;
    this.render(play);
    if (play.next >= play.pieces.length) {
      this.play = null;
      this.options.onActive?.(false);
      this.listener?.done();
    }
  }

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

  private boxOf(play: Play, ids: readonly string[]): PieceBox {
    const elements = ids.map((id) => play.byId.get(id)).filter((element): element is BoardElement => Boolean(element));
    if (elements.length === 0) return { id: ids[0], x: 0, y: 0, w: 0, h: 0 };
    const [x1, y1, x2, y2] = getCommonBounds(elements as never);
    return { id: ids[0], x: x1, y: y1, w: x2 - x1, h: y2 - y1 };
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
}
