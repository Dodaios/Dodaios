import { sideThreadOf, waitsInBackground, type NoticeItem, type TextBlock, type TimelineItem, type TurnItem } from "./reduce";

/**
 * The conversation as a messenger shows it: strictly top to bottom in time.
 *
 * The timeline keeps one item per turn, standing where the turn began. With
 * several things answered at once that puts a turn's later messages ABOVE a
 * message the person sent meanwhile, and the person has to scroll up to find
 * what just arrived. Here every message stands at the moment it was written:
 *
 * - a turn's messages written before the person's next message stay above
 *   it, the ones written after it stand below it;
 * - the rest of a turn (the dots while it works, a card that waits for the
 *   person, its closing line) stands with its last message, and at the very
 *   bottom while the turn still works;
 * - a message answered beside a turn (a side thread) is the person's bubble
 *   where they sent it, and its answer where it arrived.
 *
 * Nothing but a turn's messages and a side thread's answer ever moves, and
 * they only move down: every other item keeps the order the timeline has.
 */

/** A turn's earlier messages, standing above something that came in between. */
export interface TurnPart {
  type: "turn_part";
  id: string;
  turn: TurnItem;
  blocks: TextBlock[];
}

export type ChatRow =
  /** An item drawn as it always was; a turn here carries its closing part. */
  | { kind: "item"; id: string; time: number; item: TimelineItem }
  | { kind: "turn_part"; id: string; time: number; part: TurnPart }
  /** A side thread's two halves: the person's message, and what answered it. */
  | { kind: "side_message"; id: string; time: number; item: NoticeItem }
  | { kind: "side_answer"; id: string; time: number; item: NoticeItem };

/** Still being written: below everything that has a time. A working turn is the very last. */
const SIDE_RUNNING = Number.MAX_SAFE_INTEGER - 1;
const TURN_RUNNING = Number.MAX_SAFE_INTEGER;

type Piece =
  | { kind: "fixed"; item: TimelineItem }
  | { kind: "text"; turn: TurnItem; block: TextBlock }
  | { kind: "rest"; turn: TurnItem }
  | { kind: "side_message"; item: NoticeItem }
  | { kind: "side_answer"; item: NoticeItem };

interface Atom {
  /** Where it sorts: its own time, never before the item it belongs to. */
  at: number;
  base: number;
  sub: number;
  piece: Piece;
}

function itemTime(item: TimelineItem): number {
  const ts = item.type === "turn" ? item.startedMs : item.tsMs;
  return Number.isFinite(ts) ? ts : 0;
}

function said(block: TurnItem["blocks"][number]): block is TextBlock {
  return block.kind === "text" && block.text.trim() !== "";
}

/** `items` in the order a messenger shows them. */
export function chronological(items: readonly TimelineItem[]): ChatRow[] {
  const atoms: Atom[] = [];
  // Items keep their order even when their clocks disagree (an imported
  // turn carries an old time): each one counts as no earlier than the last.
  let floor = 0;
  items.forEach((item, base) => {
    const anchor = Math.max(itemTime(item), floor);
    floor = anchor;
    if (item.type === "turn") {
      let last = anchor;
      item.blocks.forEach((block, sub) => {
        if (!said(block)) return;
        last = Math.max(block.tsMs ?? anchor, last);
        atoms.push({ at: last, base, sub, piece: { kind: "text", turn: item, block } });
      });
      const at = item.status === "running" ? TURN_RUNNING : last;
      atoms.push({ at, base, sub: item.blocks.length, piece: { kind: "rest", turn: item } });
      return;
    }
    const side = sideThreadOf(item);
    if (side) {
      const finished = Number(side.item.data.finished_ms);
      const at = side.running ? SIDE_RUNNING : Math.max(Number.isFinite(finished) ? finished : anchor, anchor);
      atoms.push({ at: anchor, base, sub: 0, piece: { kind: "side_message", item: side.item } });
      atoms.push({ at, base, sub: 1, piece: { kind: "side_answer", item: side.item } });
      return;
    }
    atoms.push({ at: anchor, base, sub: 0, piece: { kind: "fixed", item } });
  });
  atoms.sort((a, b) => a.at - b.at || a.base - b.base || a.sub - b.sub);

  const rows: ChatRow[] = [];
  for (let i = 0; i < atoms.length; ) {
    const atom = atoms[i];
    const piece = atom.piece;
    const time = atom.at >= SIDE_RUNNING ? 0 : atom.at;
    if (piece.kind === "fixed") {
      rows.push({ kind: "item", id: piece.item.id, time, item: piece.item });
      i++;
    } else if (piece.kind === "side_message" || piece.kind === "side_answer") {
      const id = piece.kind === "side_answer" ? `${piece.item.id}~answer` : piece.item.id;
      rows.push({ kind: piece.kind, id, time, item: piece.item });
      i++;
    } else {
      // A run of one turn's pieces that nothing came between.
      const turn = piece.turn;
      const texts: TextBlock[] = [];
      let closing = false;
      let j = i;
      for (; j < atoms.length; j++) {
        const next = atoms[j].piece;
        if ((next.kind !== "text" && next.kind !== "rest") || next.turn !== turn) break;
        if (next.kind === "text") texts.push(next.block);
        else closing = true;
      }
      i = j;
      if (!closing) {
        rows.push({ kind: "turn_part", id: `${turn.id}~${texts[0].id}`, time, part: { type: "turn_part", id: `${turn.id}~${texts[0].id}`, turn, blocks: texts } });
      } else {
        const whole = texts.length === turn.blocks.filter(said).length;
        // The closing part keeps the turn's id, its steps and its cards, and
        // of its messages the ones that were not placed further up.
        const kept = new Set(texts.map((block) => block.id));
        const item = whole ? turn : { ...turn, blocks: turn.blocks.filter((block) => !said(block) || kept.has(block.id)) };
        rows.push({ kind: "item", id: turn.id, time, item });
      }
    }
  }
  return rows;
}

/**
 * The one place that shows the assistant typing: the lowest row still being
 * written (a working turn's closing part, else a side thread's answer). A
 * turn that only waits for an agent it sent out writes nothing: an answer
 * being written beside it types instead.
 */
export function typingRow(rows: readonly ChatRow[]): string | null {
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i];
    if (row.kind === "item" && row.item.type === "turn" && row.item.status === "running" && !waitsInBackground(row.item)) return row.id;
    if (row.kind === "side_answer" && row.item.resolved === "") return row.id;
  }
  return null;
}
