/**
 * The node window: a node opened over the conversation it was made in.
 *
 * A click on a page card in a chat does not leave the chat for the Nodes
 * section. It opens the node in a window over the app, with a margin all
 * round: the node on the left, the conversation on the right
 * (components/nodes/peek). This store holds which node that is and which
 * chat stands beside it; the window itself is drawn by `NodePeekHost`.
 *
 * `chat` is the agent-chat store the click came from (the front page's, an
 * IDE pane's, an agent's), so the conversation beside the node is the one the
 * person was reading. Null means the lead conversation.
 */
import { create } from "zustand";

import type { AgentChatStoreHook } from "@/store/agentChat";
import { useEventStore } from "@/store/events";

const CHAT_OPEN_KEY = "jarvis.nodes.peek.chat";

export interface NodePeekRequest {
  /** `slug::path`, the address a page card carries. */
  ref: string;
  slug: string;
  path: string;
  /** The name the card showed, until the library answers with the node's own. */
  title: string;
  chat: AgentChatStoreHook | null;
  /** Goes up with every request, so the same node asked twice is still news. */
  seq: number;
}

export interface NodePeekOptions {
  /** The chat the click came from. Left out, an open window keeps its chat. */
  chat?: AgentChatStoreHook | null;
  title?: string;
}

/**
 * A conversation that is drawn on the page behind the window and can be
 * moved into it: whose it is, the element it is drawn in, and the place on
 * its own page it goes back to.
 */
export interface LentConversation {
  chat: AgentChatStoreHook;
  element: HTMLElement;
  home: HTMLElement;
}

interface NodePeekState {
  peek: NodePeekRequest | null;
  /** The conversation column is shown. Remembered across restarts. */
  chatOpen: boolean;
  /**
   * When each node's window was last closed. A card in the chat draws its
   * preview again after that, so it shows what was edited in the window.
   */
  touched: Record<string, number>;
  /**
   * The conversation on the page behind the window, offered to it, or null
   * when there is none. The window shows that conversation by moving its
   * element beside the node, never by drawing it a second time: see
   * `components/nodes/peek/moveKeepingPlace`.
   */
  lender: LentConversation | null;
  open: (ref: string, options?: NodePeekOptions) => void;
  close: () => void;
  setChatOpen: (open: boolean) => void;
  setLender: (lent: LentConversation | null) => void;
}

function readChatOpen(): boolean {
  try {
    return window.localStorage.getItem(CHAT_OPEN_KEY) !== "0";
  } catch {
    // Storage can be unavailable: the conversation shows then.
    return true;
  }
}

/** `slug` and `path` of a `slug::path` address, or null. */
export function splitNodeRef(ref: string): { slug: string; path: string } | null {
  const at = ref.indexOf("::");
  if (at <= 0 || at + 2 >= ref.length) return null;
  return { slug: ref.slice(0, at), path: ref.slice(at + 2) };
}

export const useNodePeek = create<NodePeekState>((set, get) => ({
  peek: null,
  chatOpen: readChatOpen(),
  touched: {},
  lender: null,
  setLender: (lent) => {
    if (get().lender !== lent) set({ lender: lent });
  },
  open: (ref, options = {}) => {
    const parts = splitNodeRef(ref);
    if (parts === null) {
      // Not the address of one file: the Nodes section knows what to do with it.
      useEventStore.getState().requestVisual(ref);
      return;
    }
    const current = get().peek;
    set({
      peek: {
        ref,
        ...parts,
        title: options.title?.trim() ?? "",
        chat: options.chat !== undefined ? options.chat : (current?.chat ?? null),
        seq: (current?.seq ?? 0) + 1,
      },
    });
  },
  close: () => {
    const current = get().peek;
    if (current === null) return;
    set((state) => ({ peek: null, touched: { ...state.touched, [current.ref]: Date.now() } }));
  },
  setChatOpen: (open) => {
    set({ chatOpen: open });
    try {
      window.localStorage.setItem(CHAT_OPEN_KEY, open ? "1" : "0");
    } catch {
      // A remembered layout is a convenience, never a requirement.
    }
  },
}));

/** Open `ref` in the node window. Store-level, so a click handler can call it directly. */
export function openNodePeek(ref: string, options?: NodePeekOptions): void {
  useNodePeek.getState().open(ref, options);
}
