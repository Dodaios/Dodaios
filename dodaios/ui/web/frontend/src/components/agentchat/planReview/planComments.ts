/**
 * Comments on a plan, anchored to its words.
 *
 * A comment keeps the passage it is about (its quote) and where that passage
 * started, never an editor position: the review window closes and opens again,
 * and the plan's text changes under the comments while the person edits it. So
 * the marks in the text are found again from the quotes on every change. A
 * passage the person has edited away leaves its comment standing in the list,
 * with the words it was written about.
 */
import { Extension } from "@tiptap/core";
import type { Node as ProseNode } from "@tiptap/pm/model";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

import type { PlanComment } from "./planDraft";

/** The longest passage a comment keeps (the agent reads a shortened line of it). */
export const MAX_QUOTE_CHARS = 1200;

interface Segment {
  /** Editor position of the text node's first character. */
  pos: number;
  /** Where that character sits in the flat text. */
  start: number;
  length: number;
}

/** The plan as one string, and where each stretch of it sits in the editor. */
export interface PlanText {
  text: string;
  segments: Segment[];
}

/** The document's words in reading order, blocks one line apart. */
export function planText(doc: ProseNode): PlanText {
  const segments: Segment[] = [];
  let text = "";
  let lastBlock: ProseNode | null = null;
  doc.descendants((node, pos, parent) => {
    if (!node.isText || !node.text) return true;
    if (lastBlock !== null && parent !== lastBlock) text += "\n";
    lastBlock = parent;
    segments.push({ pos, start: text.length, length: node.text.length });
    text += node.text;
    return false;
  });
  return { text, segments };
}

/** The flat-text index of an editor position (clamped into the nearest text). */
export function indexAt(map: PlanText, pos: number): number {
  for (const segment of map.segments) {
    if (pos <= segment.pos) return segment.start;
    if (pos <= segment.pos + segment.length) return segment.start + (pos - segment.pos);
  }
  return map.text.length;
}

/** The editor ranges that cover the flat-text span `[from, to)`, one per text node. */
export function rangesOf(map: PlanText, from: number, to: number): { from: number; to: number }[] {
  const out: { from: number; to: number }[] = [];
  for (const segment of map.segments) {
    const a = Math.max(from, segment.start);
    const b = Math.min(to, segment.start + segment.length);
    if (a < b) out.push({ from: segment.pos + (a - segment.start), to: segment.pos + (b - segment.start) });
  }
  return out;
}

/** The passage between two editor positions, as a comment keeps it. */
export function quoteBetween(map: PlanText, from: number, to: number): { quote: string; at: number } {
  const start = indexAt(map, Math.min(from, to));
  const end = indexAt(map, Math.max(from, to));
  const raw = map.text.slice(start, end);
  const lead = raw.length - raw.trimStart().length;
  return { quote: raw.trim().slice(0, MAX_QUOTE_CHARS), at: start + lead };
}

/** Where a comment's passage stands now: the occurrence nearest to where it was marked. */
export function findQuote(map: PlanText, comment: Pick<PlanComment, "quote" | "at">): { from: number; to: number } | null {
  const quote = comment.quote;
  if (!quote) return null;
  let best = -1;
  for (let index = map.text.indexOf(quote); index >= 0; index = map.text.indexOf(quote, index + 1)) {
    if (best < 0 || Math.abs(index - comment.at) < Math.abs(best - comment.at)) best = index;
  }
  return best < 0 ? null : { from: best, to: best + quote.length };
}

/** The comments in the order their passages stand in the plan; lost passages last. */
export function inReadingOrder(map: PlanText, comments: readonly PlanComment[]): PlanComment[] {
  const place = new Map(comments.map((comment) => [comment.id, findQuote(map, comment)?.from ?? Number.MAX_SAFE_INTEGER]));
  return [...comments].sort((a, b) => (place.get(a.id) ?? 0) - (place.get(b.id) ?? 0));
}

export interface PlanCommentsStorage {
  comments: readonly PlanComment[];
  /** The comment being written or looked at: its passage is marked stronger. */
  active: string | null;
}

export const planCommentsKey = new PluginKey<DecorationSet>("planComments");

function decorate(doc: ProseNode, storage: PlanCommentsStorage): DecorationSet {
  if (!storage.comments.length) return DecorationSet.empty;
  const map = planText(doc);
  const marks: Decoration[] = [];
  for (const comment of storage.comments) {
    const found = findQuote(map, comment);
    if (!found) continue;
    const cls = comment.id === storage.active ? "plan-comment-mark is-active" : "plan-comment-mark";
    for (const range of rangesOf(map, found.from, found.to)) {
      marks.push(Decoration.inline(range.from, range.to, { class: cls, "data-plan-comment": comment.id }));
    }
  }
  return DecorationSet.create(doc, marks);
}

/**
 * Marks every commented passage in the plan. The comments are handed in
 * through the extension's storage; `refreshPlanComments` redraws the marks
 * after they changed.
 */
export const PlanComments = Extension.create<{ onComment: (() => void) | null }, PlanCommentsStorage>({
  name: "planComments",
  addOptions: () => ({ onComment: null }),
  addStorage: () => ({ comments: [], active: null }),
  addKeyboardShortcuts() {
    return {
      // The shortcut word processors use for "comment on the selection".
      "Mod-Alt-m": () => {
        if (!this.options.onComment || this.editor.state.selection.empty) return false;
        this.options.onComment();
        return true;
      },
    };
  },
  addProseMirrorPlugins() {
    const storage = this.storage;
    return [
      new Plugin<DecorationSet>({
        key: planCommentsKey,
        state: {
          init: (_config, state) => decorate(state.doc, storage),
          apply: (tr, old, _before, state) => (tr.docChanged || tr.getMeta(planCommentsKey) ? decorate(state.doc, storage) : old),
        },
        props: {
          decorations(state) {
            return planCommentsKey.getState(state);
          },
        },
      }),
    ];
  },
});
