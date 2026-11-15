/**
 * Where the caret goes when the document editor was opened by a click into
 * the page.
 *
 * The page cannot hand over a position in the editor's document: it only
 * knows the words it drew around the click (`dodaios/nodes/bridge.py`,
 * `dodaios-node-edit-here`). The editor shows the same words (it reads the
 * same Markdown), so the spot is found by looking for them: the words before
 * and after together first, then the words after, then the words before,
 * each also in a shorter piece.
 */
import type { Node as ProseNode } from "@tiptap/pm/model";

import type { NodeEditorStart } from "../types";

/** A shorter piece of the words still names the spot, and is less likely to cross a mark. */
const SHORT = 12;
/** Fewer characters than this find too many places to mean the one clicked. */
const LEAST = 3;
/** Anything inline that is not text (a picture, a line break) stands as one character. */
const OBJECT = "￼";

interface Block {
  text: string;
  /** The document position of each character of `text`. */
  at: number[];
  /** The position right after the block's last character. */
  end: number;
}

/** The text blocks of a part of the document, each with where its characters are. */
function blocksOf(doc: ProseNode, from: number, to: number): Block[] {
  const blocks: Block[] = [];
  doc.nodesBetween(from, to, (node, pos) => {
    if (!node.isTextblock) return true;
    let text = "";
    const at: number[] = [];
    node.forEach((child, offset) => {
      const start = pos + 1 + offset;
      if (child.isText) {
        const value = child.text ?? "";
        for (let i = 0; i < value.length; i++) {
          // The page squeezes every run of spaces into one; a single space
          // here matches it.
          text += /\s/.test(value[i]) ? " " : value[i];
          at.push(start + i);
        }
      } else {
        text += OBJECT;
        at.push(start);
      }
    });
    blocks.push({ text, at, end: pos + 1 + node.content.size });
    return false;
  });
  return blocks;
}

/** The position `index` characters into the block (its end counts too). */
function positionIn(block: Block, index: number): number {
  return index < block.at.length ? block.at[index] : block.end;
}

/** The first place `needle` is in the blocks, with the caret `shift` characters into it. */
function find(blocks: Block[], needle: string, shift: number): number | null {
  if (needle.trim().length < LEAST) return null;
  for (const block of blocks) {
    const index = block.text.indexOf(needle);
    if (index >= 0) return positionIn(block, index + shift);
  }
  return null;
}

/**
 * The caret position for a click into the page, or null when the words are
 * not in the document (the editor then opens at the start of the part that
 * was clicked).
 */
export function caretFor(doc: ProseNode, start: NodeEditorStart): number | null {
  // The summary is the document's first node; the body is everything after it.
  const summaryEnd = doc.childCount > 0 ? doc.child(0).nodeSize : 0;
  const [from, to] =
    start.path === "/summary"
      ? [0, summaryEnd]
      : start.path === "/markdown"
        ? [summaryEnd, doc.content.size]
        : [0, doc.content.size];
  const blocks = blocksOf(doc, from, to);
  const before = start.before.replace(/\s+/g, " ");
  const after = start.after.replace(/\s+/g, " ");
  const shortBefore = before.slice(-SHORT);
  const shortAfter = after.slice(0, SHORT);
  return (
    (before && after ? find(blocks, before + after, before.length) : null) ??
    (shortBefore && shortAfter ? find(blocks, shortBefore + shortAfter, shortBefore.length) : null) ??
    find(blocks, after, 0) ??
    find(blocks, before, before.length) ??
    find(blocks, shortAfter, 0) ??
    find(blocks, shortBefore, shortBefore.length)
  );
}

/** Where the part that was clicked begins, for a click whose words were not found. */
export function startOf(doc: ProseNode, path: string): number {
  const summaryEnd = doc.childCount > 0 ? doc.child(0).nodeSize : 0;
  if (path === "/markdown" && doc.childCount > 1) return summaryEnd + 1;
  return 1;
}
