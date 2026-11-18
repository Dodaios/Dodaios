/**
 * How a document is revealed while an agent builds it.
 *
 * Block by block in reading order, the way a careful person would write it:
 *
 * - a paragraph is written in word group by word group at the agent's caret;
 * - a heading, a list item, a callout and a table row (one at a time)
 *   arrive whole;
 * - a picture or a chart shows a quiet skeleton, then fades in;
 * - words an edit replaces fade out where the new ones write in.
 *
 * What is new or edited comes from comparing the blocks the editor held
 * before the revision with those it holds now (`editors/docs/liveBlocks.ts`);
 * the text itself is never touched (`../writing.ts`). Without that record
 * (an editor opened mid-build), what changed in the body fades in as usual.
 */
import { blocksBefore, blocksOf, diffBlocks, editedSpan, editorOf, type BlockChange } from "../../editors/docs/liveBlocks";
import { defaultReveal, type RevealAdapter, type RevealInput, type RevealStep } from "../reveal";
import { canWriteText, skeletonReveal, textWriting } from "../writing";

function stepFor(change: BlockChange): RevealStep {
  const { block } = change;
  const target = { element: block.el };
  if (block.kind === "media") return { target, motion: skeletonReveal(block.el) };
  if (block.kind === "text" && canWriteText()) {
    if (change.type === "new") return { target, motion: textWriting(block.el, { from: 0 }) };
    const span = editedSpan(change.before.raw, block.raw);
    return { target, motion: textWriting(block.el, { from: span.from, to: span.to, removed: span.removed }) };
  }
  return { target };
}

export const docsReveal: RevealAdapter = {
  steps(input: RevealInput): RevealStep[] {
    const content = editorOf(input.root);
    if (!content) return defaultReveal.steps(input);
    const blocks = blocksOf(content);
    // Opened while the agent builds: what is there fades in, block by block.
    if (input.initial) return blocks.map((block) => ({ target: { element: block.el } }));
    const before = blocksBefore(content);
    if (!before) return defaultReveal.steps(input);
    return diffBlocks(before, blocks).map(stepFor);
  },
};
