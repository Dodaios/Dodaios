/**
 * Unsaved text per file in the File tab. Picking another file in a thread, or
 * flipping to the "Change" view, takes the editor away; the text typed so far
 * waits here and comes back with the file. Only an explicit reload (or a save)
 * lets it go.
 *
 * Kept apart from the editor so the tab can reach it without loading the
 * editor engine.
 */
export interface Draft {
  text: string;
  /** The disk version the unsaved text was written against. */
  version: string;
}

const drafts = new Map<string, Draft>();
const keyOf = (workspaceId: string, path: string) => `${workspaceId}\u0000${path}`;

export const getDraft = (workspaceId: string, path: string): Draft | undefined => drafts.get(keyOf(workspaceId, path));

export const setDraft = (workspaceId: string, path: string, draft: Draft): void => {
  drafts.set(keyOf(workspaceId, path), draft);
};

/** Let go of the unsaved text of a file: it was saved, or the person asked to read the disk's text again. */
export const discardDraft = (workspaceId: string, path: string): void => {
  drafts.delete(keyOf(workspaceId, path));
};
