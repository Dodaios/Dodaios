/**
 * The contract between the live-build core and a node type's own reveal.
 *
 * An agent's edit reaches an open editor as one batch: the editor shows the
 * new spec at once, laid out in its final place. The core then plays that
 * batch back in reading order: each unit fades in, the presence frame grows
 * around what has been written so far, and the agent's cursor glides to each
 * unit. WHICH units, in WHICH order, is the type's business: a type adapter
 * receives the previous spec, the next spec and the ops, and returns ordered
 * reveal steps. The core plays them (`playback.ts`) and draws the presence
 * (`LivePresence.tsx`).
 *
 * Every type uses `defaultReveal` until its own adapter lands in
 * `adapters/<type>.ts`. docs/node-live-build.md is the page to read.
 */
import type { NodeType } from "../nodeModel";
import type { LiveOp } from "./liveStore";

/** What an adapter is given for one batch. */
export interface RevealInput<S = unknown> {
  type: NodeType;
  /** The spec before the batch; null when the editor opened mid-build. */
  previous: S | null;
  /** The spec the editor shows now (already drawn in `root`). */
  next: S;
  /** The agent's ops in the order applied; null for a rewrite or an unknown range. */
  ops: LiveOp[] | null;
  /** The editor opened while the agent was building: `next` is all there is to show. */
  initial: boolean;
  /** The editor's body, already showing `next`. Read it; never change it. */
  root: HTMLElement;
}

/**
 * Where a step points. The core resolves it inside the editor's body when the
 * step plays; a step whose target cannot be found is skipped.
 *
 * - `path`: the element marked `data-live-path="<JSON Pointer>"` for that path,
 *   or else for its nearest marked ancestor path (`/rows/3/2` falls back to
 *   `/rows/3`, then `/rows`). Mark the elements that draw spec items this way.
 * - `selector`: the first match of a CSS selector inside the body.
 * - `element`: an element the adapter found itself.
 * - `changed`: what the core saw change in the body's DOM for this batch,
 *   in reading order (one step per changed block). The default.
 * - `blocks`: the body's top-level blocks, in reading order (opening mid-build).
 */
export type RevealTarget =
  | { path: string }
  | { selector: string }
  | { element: Element }
  | { changed: true }
  | { blocks: true };

export interface RevealStep {
  target: RevealTarget;
  /** What the agent is doing in this step, shown as the status ("Adding the totals"). */
  label?: string;
  /**
   * Type-specific motion when the step is revealed, played with the fade
   * (a clip growing to its length, a track sliding in). Called as the unit
   * is revealed, so it can measure the final layout; null plays the fade
   * alone. Skipped with reduced motion.
   */
  enter?: (el: Element) => Keyframe[] | null;
  /** Called with the step's first element as it is revealed (with reduced motion too). */
  onReveal?: (el: Element) => void;
  /**
   * Whether the presence frame grows to include this step (default true).
   * A step outside the written area (a new tab in a tab bar) plays and draws
   * the cursor, but the frame stays on the content.
   */
  framed?: boolean;
}

export interface RevealAdapter<S = unknown> {
  /** The batch's steps in the order they play. Called once the body shows `next`. */
  steps: (input: RevealInput<S>) => RevealStep[];
  /** Which corner of the frame the name tag sits on (default: the top-left). */
  tagCorner?: "top" | "bottom";
}

/**
 * The reveal every type has until its own lands: what changed fades in, block
 * by block in reading order, with the presence. Opened mid-build, the node's
 * top-level blocks fade in once.
 */
export const defaultReveal: RevealAdapter = {
  steps: ({ initial }) => [{ target: initial ? { blocks: true } : { changed: true } }],
};
