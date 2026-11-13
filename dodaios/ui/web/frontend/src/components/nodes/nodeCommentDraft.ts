/**
 * The comments the reader has left on the open node and not sent yet.
 *
 * A comment does not go out on its own: the reader leaves as many as they
 * like (pins 1, 2, 3 …), and the toolbar's "Send" hands them all to the
 * assistant as one request (`sendNodeComments`), in the background. The page
 * draws the pins (`dodaios/nodes/bridge.py`); this store keeps their words,
 * so the toolbar can count them and send them, and tells the page how the
 * sending went through `outcome`.
 *
 * One node at a time: the stage shows one, and opening another starts empty.
 */
import { create } from "zustand";

import { sendNodeComments } from "./askDodaios";
import type { NodeComment, NodeCommentState } from "./nodeBridge";
import type { NodeCard } from "./nodeModel";

export interface NodeCommentOutcome {
  /** Goes up with every outcome, so the same pins can be told twice. */
  seq: number;
  ns: number[];
  state: Exclude<NodeCommentState, "pending">;
}

interface NodeCommentDraftState {
  /** The node the comments are on (its id, or its key). */
  nodeKey: string | null;
  pending: NodeComment[];
  sending: boolean;
  /** Comments sent and not yet worked in; the node's next revision clears it. */
  working: number;
  outcome: NodeCommentOutcome | null;
  /** Start over for `nodeKey` (a no-op when it is the node already open). */
  open: (nodeKey: string | null) => void;
  add: (comment: NodeComment) => void;
  remove: (n: number) => void;
  /** Send every waiting comment on `card` at once. Resolves false when that failed. */
  sendAll: (card: NodeCard) => Promise<boolean>;
  /** The node was revised: what was sent is worked in. */
  settle: () => void;
}

export const useNodeCommentDraft = create<NodeCommentDraftState>((set, get) => ({
  nodeKey: null,
  pending: [],
  sending: false,
  working: 0,
  outcome: null,
  open: (nodeKey) => {
    if (get().nodeKey === nodeKey) return;
    set({ nodeKey, pending: [], sending: false, working: 0, outcome: null });
  },
  add: (comment) =>
    set((state) => ({ pending: [...state.pending.filter((c) => c.n !== comment.n), comment] })),
  remove: (n) => set((state) => ({ pending: state.pending.filter((c) => c.n !== n) })),
  sendAll: async (card) => {
    const { pending, sending, nodeKey } = get();
    if (sending || pending.length === 0) return false;
    const batch = [...pending].sort((a, b) => a.n - b.n);
    const ns = batch.map((c) => c.n);
    const seq = (get().outcome?.seq ?? 0) + 1;
    set({ sending: true });
    try {
      await sendNodeComments(card, batch);
    } catch {
      if (get().nodeKey === nodeKey) set({ sending: false, outcome: { seq, ns, state: "failed" } });
      return false;
    }
    if (get().nodeKey !== nodeKey) return true;
    set((state) => ({
      sending: false,
      // Comments added while these went out keep waiting.
      pending: state.pending.filter((c) => !ns.includes(c.n)),
      working: state.working + batch.length,
      outcome: { seq, ns, state: "sent" },
    }));
    return true;
  },
  settle: () => set({ working: 0 }),
}));
