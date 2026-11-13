/**
 * The app's side of the talk with a node's page: comments left on the page,
 * and values the reader types into it.
 *
 * A node's page runs in a sandboxed frame. The app cannot see where the
 * reader clicks in it, so the page itself drops a comment's pin, or makes its
 * marked texts typeable (`dodaios/nodes/bridge.py`), and tells the app what
 * was written and where. This module switches the page's mode, takes a
 * comment in (it waits, with the others, for the toolbar's "Send"), hears a
 * comment taken back, tells the page where each comment stands, and saves an
 * edit. It also remembers where the page was, so a page drawn again opens
 * there.
 *
 * Only messages from this very frame count, and everything is taken as plain,
 * bounded data: the page's script runs in an opaque origin and gets nothing
 * else from the app.
 */
import { useCallback, useEffect, useRef, type RefObject } from "react";

/** The message names (`dodaios/nodes/bridge.py`; a parity test keeps both sides equal). */
export const NODE_READY_MESSAGE = "dodaios-node-ready";
export const NODE_MODE_MESSAGE = "dodaios-node-mode";
export const NODE_COMMENT_MESSAGE = "dodaios-node-comment";
export const NODE_COMMENT_STATE_MESSAGE = "dodaios-node-comment-state";
export const NODE_COMMENT_REMOVE_MESSAGE = "dodaios-node-comment-remove";
export const NODE_EDIT_MESSAGE = "dodaios-node-edit";
export const NODE_EDIT_STATE_MESSAGE = "dodaios-node-edit-state";
export const NODE_SCROLL_MESSAGE = "dodaios-node-scroll";

/** What the page is doing with a click: nothing, a comment's pin, or editing. */
export type NodePageMode = "view" | "comment" | "edit";

const MAX_COMMENT_CHARS = 2000;
const MAX_QUOTE_CHARS = 240;
const MAX_WHERE_CHARS = 300;
const MAX_EDIT_CHARS = 200000;
const MAX_PATH_CHARS = 400;

/** A comment the reader left on the page. */
export interface NodeComment {
  /** The pin's number on the page. */
  n: number;
  text: string;
  /** The text under the pin; "" when it was put on a picture or on nothing. */
  quote: string;
  /** The place in the node's own terms ("/slides/2", "Price × Netflix", "§ Costs"); may be "". */
  where: string;
}

/** A value the reader typed into the page. */
export interface NodeEdit {
  /** The page's own number for this edit, echoed in the answer. */
  id: number;
  /** The place in the spec (a JSON Pointer), or "@title". */
  path: string;
  value: string | boolean;
  as: "text" | "number" | "toggle";
  /** The page must be drawn again once it is saved. */
  refresh: boolean;
}

/** The few words the page shows, in the reader's language. */
export interface NodeBridgeLabels {
  placeholder: string;
  /** The pin's button that adds the comment to the ones waiting. */
  add: string;
  /** Under a comment that waits for "Send". */
  pending: string;
  sent: string;
  failed: string;
  /** The button that takes a waiting comment back. */
  remove: string;
}

/** Where a comment stands, as the page shows it. */
export type NodeCommentState = "pending" | "sent" | "failed";

function clipped(value: unknown, limit: number): string {
  return typeof value === "string" ? value.slice(0, limit) : "";
}

/** The comment a page sent, or null for anything else. */
export function parseNodeComment(data: unknown): NodeComment | null {
  if (!data || typeof data !== "object") return null;
  const message = data as { type?: unknown; n?: unknown; text?: unknown; quote?: unknown; where?: unknown };
  if (message.type !== NODE_COMMENT_MESSAGE) return null;
  const n = typeof message.n === "number" && Number.isInteger(message.n) && message.n > 0 ? message.n : null;
  const text = clipped(message.text, MAX_COMMENT_CHARS).trim();
  if (n === null || text === "") return null;
  return {
    n,
    text,
    quote: clipped(message.quote, MAX_QUOTE_CHARS).trim(),
    where: clipped(message.where, MAX_WHERE_CHARS).trim(),
  };
}

/** The value a page typed, or null for anything else. */
export function parseNodeEdit(data: unknown): NodeEdit | null {
  if (!data || typeof data !== "object") return null;
  const message = data as Record<string, unknown>;
  if (message.type !== NODE_EDIT_MESSAGE) return null;
  const id = typeof message.id === "number" && Number.isInteger(message.id) && message.id > 0 ? message.id : null;
  const path = typeof message.path === "string" ? message.path : "";
  const kind = message.as === "number" || message.as === "toggle" ? message.as : "text";
  if (id === null || path === "" || path.length > MAX_PATH_CHARS) return null;
  if (!path.startsWith("/") && path !== "@title") return null;
  let value: string | boolean;
  if (kind === "toggle") {
    if (typeof message.value !== "boolean") return null;
    value = message.value;
  } else {
    if (typeof message.value !== "string" || message.value.length > MAX_EDIT_CHARS) return null;
    value = message.value;
  }
  return { id, path, value, as: kind, refresh: message.refresh === true };
}

/** Where a page is: its scroll position, and the hash it keeps its place in. */
interface PagePlace {
  x: number;
  y: number;
  hash?: string;
}

/** Where a page reports it is, or null. */
function parseScroll(data: unknown): PagePlace | null {
  if (!data || typeof data !== "object") return null;
  const message = data as Record<string, unknown>;
  if (message.type !== NODE_SCROLL_MESSAGE) return null;
  const x = Number(message.x);
  const y = Number(message.y);
  if (!Number.isFinite(x) || !Number.isFinite(y) || x < 0 || y < 0) return null;
  const hash = typeof message.hash === "string" && /^#[\w-]{1,39}$/.test(message.hash) ? message.hash : "";
  return hash ? { x, y, hash } : { x, y };
}

export interface NodeBridgeOptions {
  /** What a click on the page does. */
  mode: NodePageMode;
  labels: NodeBridgeLabels;
  /** Take the comment in. Resolves when it waits for "Send"; rejects when it was not taken. */
  onComment: (comment: NodeComment) => Promise<void>;
  /** The reader took comment `n` back before it was sent. */
  onRemove?: (n: number) => void;
  /** Save an edit. Resolves when it is saved; rejects when it was not. */
  onEdit?: (edit: NodeEdit) => Promise<void>;
  /**
   * What the page is. When it changes, the remembered scroll position is
   * forgotten: another node opens at its top.
   */
  pageKey?: string;
}

/** What the app can tell the page later: where comments `ns` stand now. */
export type TellCommentState = (ns: readonly number[], state: NodeCommentState) => void;

/**
 * Keep the framed page in the mode the app is in, and take its comments and
 * edits.
 *
 * The page says when it has loaded (also after it was drawn again), and is
 * told the mode then, with the scroll position it last had: a node the
 * assistant or the reader just revised comes back in the same mode, at the
 * same place.
 */
export function useNodeBridge(
  frame: RefObject<HTMLIFrameElement | null>,
  options: NodeBridgeOptions,
): TellCommentState {
  const latest = useRef(options);
  latest.current = options;
  const scroll = useRef<PagePlace | null>(null);
  useEffect(() => {
    scroll.current = null;
  }, [options.pageKey]);

  useEffect(() => {
    const tell = (message: Record<string, unknown>) => {
      // The page's origin is opaque (sandbox without same-origin): "*" is the
      // only target that reaches it, and the message carries nothing secret.
      frame.current?.contentWindow?.postMessage(message, "*");
    };
    const tellMode = (withScroll = false) =>
      tell({
        type: NODE_MODE_MESSAGE,
        mode: latest.current.mode,
        labels: latest.current.labels,
        ...(withScroll && scroll.current ? { scroll: scroll.current } : {}),
      });

    const onMessage = (event: MessageEvent) => {
      const node = frame.current;
      if (!node || event.source !== node.contentWindow) return;
      const data = event.data as { type?: unknown } | null;
      if (data && typeof data === "object" && data.type === NODE_READY_MESSAGE) {
        tellMode(true);
        return;
      }
      const at = parseScroll(event.data);
      if (at !== null) {
        scroll.current = at;
        return;
      }
      const edit = parseNodeEdit(event.data);
      if (edit !== null) {
        // An edit counts only while the reader is editing: a page cannot
        // write into its node on its own.
        const save = latest.current.mode === "edit" ? latest.current.onEdit : undefined;
        const done = save ? save(edit) : Promise.reject(new Error("not editing"));
        done.then(
          () => tell({ type: NODE_EDIT_STATE_MESSAGE, id: edit.id, state: "saved" }),
          () => tell({ type: NODE_EDIT_STATE_MESSAGE, id: edit.id, state: "failed" }),
        );
        return;
      }
      if (data && typeof data === "object" && data.type === NODE_COMMENT_REMOVE_MESSAGE) {
        const n = (data as { n?: unknown }).n;
        if (typeof n === "number" && Number.isInteger(n) && n > 0) latest.current.onRemove?.(n);
        return;
      }
      const comment = parseNodeComment(event.data);
      if (comment === null) return;
      latest.current.onComment(comment).then(
        () => tell({ type: NODE_COMMENT_STATE_MESSAGE, n: comment.n, state: "pending" }),
        () => tell({ type: NODE_COMMENT_STATE_MESSAGE, n: comment.n, state: "failed" }),
      );
    };
    window.addEventListener("message", onMessage);
    tellMode();
    return () => window.removeEventListener("message", onMessage);
    // The mode is told again whenever it changes; the handlers read the rest live.
  }, [frame, options.mode]);

  return useCallback<TellCommentState>(
    (ns, state) => {
      for (const n of ns) {
        frame.current?.contentWindow?.postMessage({ type: NODE_COMMENT_STATE_MESSAGE, n, state }, "*");
      }
    },
    [frame],
  );
}
