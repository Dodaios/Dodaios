/**
 * The app's side of the talk with a node's page: comments left on the page.
 *
 * A node's page runs in a sandboxed frame. The app cannot see where the
 * reader clicks in it, so the page itself drops the pin and the field
 * (`dodaios/nodes/bridge.py`) and tells the app what was written and on what.
 * This module switches the page's mode, takes a comment in, hands it to
 * whoever sends it on, and tells the page how that went.
 *
 * Only messages from this very frame count, and a comment is taken as plain,
 * bounded text: the page's script runs in an opaque origin and gets nothing
 * else from the app.
 */
import { useEffect, useRef, type RefObject } from "react";

/** The message names (`dodaios/nodes/bridge.py`; a parity test keeps both sides equal). */
export const NODE_READY_MESSAGE = "dodaios-node-ready";
export const NODE_MODE_MESSAGE = "dodaios-node-mode";
export const NODE_COMMENT_MESSAGE = "dodaios-node-comment";
export const NODE_COMMENT_STATE_MESSAGE = "dodaios-node-comment-state";

const MAX_COMMENT_CHARS = 2000;
const MAX_QUOTE_CHARS = 240;
const MAX_WHERE_CHARS = 300;

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

/** The few words the page shows, in the reader's language. */
export interface NodeBridgeLabels {
  placeholder: string;
  send: string;
  sent: string;
  failed: string;
}

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

export interface NodeBridgeOptions {
  /** The page takes comments: a click drops a pin instead of doing what it does. */
  commenting: boolean;
  labels: NodeBridgeLabels;
  /** Send the comment on. Resolves when it went out; rejects when it did not. */
  onComment: (comment: NodeComment) => Promise<void>;
}

/**
 * Keep the framed page in the mode the app is in, and take its comments.
 *
 * The page says when it has loaded (also after it was drawn again), and is
 * told the mode then, so a node the assistant just revised comes back still
 * taking comments.
 */
export function useNodeBridge(frame: RefObject<HTMLIFrameElement | null>, options: NodeBridgeOptions): void {
  const latest = useRef(options);
  latest.current = options;

  useEffect(() => {
    const tell = (message: Record<string, unknown>) => {
      // The page's origin is opaque (sandbox without same-origin): "*" is the
      // only target that reaches it, and the message carries nothing secret.
      frame.current?.contentWindow?.postMessage(message, "*");
    };
    const tellMode = () =>
      tell({
        type: NODE_MODE_MESSAGE,
        mode: latest.current.commenting ? "comment" : "view",
        labels: latest.current.labels,
      });

    const onMessage = (event: MessageEvent) => {
      const node = frame.current;
      if (!node || event.source !== node.contentWindow) return;
      const data = event.data as { type?: unknown } | null;
      if (data && typeof data === "object" && data.type === NODE_READY_MESSAGE) {
        tellMode();
        return;
      }
      const comment = parseNodeComment(event.data);
      if (comment === null) return;
      latest.current.onComment(comment).then(
        () => tell({ type: NODE_COMMENT_STATE_MESSAGE, n: comment.n, state: "sent" }),
        () => tell({ type: NODE_COMMENT_STATE_MESSAGE, n: comment.n, state: "failed" }),
      );
    };
    window.addEventListener("message", onMessage);
    tellMode();
    return () => window.removeEventListener("message", onMessage);
    // The mode is told again whenever it changes; the handlers read the rest live.
  }, [frame, options.commenting]);
}
