import { create } from "zustand";

/**
 * A pane asking the Git tab to show only what its agent session changed.
 *
 * The button sits in the pane's header, the list lives in the side panel's
 * Git tab, and neither reaches the other by props; the ask travels through
 * here. The `nonce` lets the same pane be asked for twice in a row.
 */
export interface GitSessionRequest {
  workspaceId: string;
  /** The pane's call-sign (T1, or the name it was given). */
  pane: string;
  nonce: number;
}

interface GitSessionStore {
  request: GitSessionRequest | null;
  show: (workspaceId: string, pane: string) => void;
  /** The Git tab took the request: a tab opened later starts unfiltered. */
  consume: (nonce: number) => void;
}

let nonce = 0;

export const useGitSessionStore = create<GitSessionStore>((set) => ({
  request: null,
  show: (workspaceId, pane) => set({ request: { workspaceId, pane, nonce: ++nonce } }),
  consume: (taken) => set((state) => (state.request?.nonce === taken ? { request: null } : {})),
}));
