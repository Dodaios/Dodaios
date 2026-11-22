/**
 * How a whiteboard is revealed while an agent builds it.
 *
 * Built by hand, a diagram grows in a fixed order: the frames (the regions)
 * first, then each shape together with its label, then the arrows once both
 * their ends are there. The board plans that order (`whiteboard/canvas/
 * liveBuild.ts`, which also puts the pieces on the canvas); this adapter turns
 * the plan into the steps the shared player plays, so the cursor, the name tag
 * and the frame follow each piece.
 *
 * A canvas has no DOM per element, so the board draws one invisible marker per
 * piece over it (`data-live-path="/elements/<first id>"`, `BoardPresence`).
 * The player measures those markers; it never changes the canvas.
 */
import type { RevealAdapter, RevealInput, RevealStep } from "../reveal";

/** The pieces of one batch, in the order they land; each piece is the ids that land together. */
export interface WhiteboardPlan {
  pieces: string[][];
}

/** The marker path of a piece: its first element's id. */
export function piecePath(ids: readonly string[]): string {
  return `/elements/${ids[0]}`;
}

export const whiteboardReveal: RevealAdapter = {
  steps: (input) => {
    const { next } = input as RevealInput<WhiteboardPlan>;
    return next.pieces.filter((ids) => ids.length > 0).map((ids): RevealStep => ({ target: { path: piecePath(ids) } }));
  },
};
