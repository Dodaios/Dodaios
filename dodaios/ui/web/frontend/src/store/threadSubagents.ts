import { create } from "zustand";
import type { SubagentStatus } from "@/components/agentchat/reduce";

/**
 * The open thread's sub-agents, shared between the thread view and the
 * sidebar.
 *
 * Only the thread view reads a thread's conversation, so only it knows which
 * sub-agents the coding agent spawned. It publishes them here; the sidebar
 * lists them under the thread as threads of their own, and opening one from
 * either place shows its conversation. Nothing here is persisted: the list is
 * rebuilt from the conversation every time a thread opens.
 */

/** One sub-agent as the sidebar lists it. */
export interface SubagentRow {
  /** The spawning call's id: what opens it. */
  id: string;
  parentId: string | null;
  depth: number;
  title: string;
  agentType: string;
  status: SubagentStatus;
  waiting: boolean;
}

interface ThreadSubagentsState {
  /** The thread the rows belong to; null while no thread is open. */
  sessionId: string | null;
  rows: SubagentRow[];
  /** The sub-agent whose conversation shows instead of its thread's. */
  open: { sessionId: string; id: string } | null;
  publish: (sessionId: string | null, rows: SubagentRow[]) => void;
  /** Shows sub-agent `id` of thread `sessionId`; null shows the thread itself. */
  openAgent: (sessionId: string, id: string | null) => void;
}

function sameRows(a: readonly SubagentRow[], b: readonly SubagentRow[]): boolean {
  return a.length === b.length && a.every((row, index) => {
    const other = b[index];
    return row.id === other.id && row.parentId === other.parentId && row.depth === other.depth
      && row.title === other.title && row.agentType === other.agentType
      && row.status === other.status && row.waiting === other.waiting;
  });
}

export const useThreadSubagentsStore = create<ThreadSubagentsState>((set, get) => ({
  sessionId: null,
  rows: [],
  open: null,
  publish: (sessionId, rows) => {
    const state = get();
    // A streaming thread republishes on every event; only a real change re-renders the sidebar.
    if (state.sessionId === sessionId && sameRows(state.rows, rows)) return;
    set({ sessionId, rows });
  },
  openAgent: (sessionId, id) => {
    const current = get().open;
    if (id === null) {
      if (current) set({ open: null });
      return;
    }
    if (current?.sessionId === sessionId && current.id === id) return;
    set({ open: { sessionId, id } });
  },
}));

/** The sub-agent open in thread `sessionId`, else null. */
export function openSubagentOf(open: ThreadSubagentsState["open"], sessionId: string | null): string | null {
  return open && sessionId && open.sessionId === sessionId ? open.id : null;
}
