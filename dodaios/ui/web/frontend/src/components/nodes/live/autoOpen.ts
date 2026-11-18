/**
 * The node window opening by itself as an agent makes a node.
 *
 * The card of a node is posted the moment the agent creates it, into the very
 * conversation the agent works in (`liveCard.ts`). That makes the card the
 * right place to decide: when the card's conversation is on screen, the node
 * window opens beside it on the agent's create. Never while the person is
 * elsewhere in the app (the card is not on screen then), never twice for one
 * node, never over a node the person opened themselves, and not again in a
 * turn whose auto-opened window the person closed. A second node of the same
 * turn swaps into the one window. Settings > Behavior turns it off.
 *
 * Fetched the first time an agent makes a node, so the app's start stays light.
 */
import { isNodeAutoOpenEnabled } from "@/lib/nodeAutoOpen";
import { useAgentChatStore, type AgentChatStoreHook } from "@/store/agentChat";
import { useNodePeek } from "@/store/nodePeek";
import { useNodeLive, type LiveNode } from "./liveStore";

/** An agent's create this recent still opens the window. */
export const AUTO_OPEN_WITHIN_MS = 30_000;

/** Is `element` on screen in a visible window (not in a hidden section or tab)? */
export function onScreen(element: Element | null): boolean {
  if (!element || !element.isConnected) return false;
  if (typeof document !== "undefined" && document.visibilityState === "hidden") return false;
  const check = (element as Element & { checkVisibility?: (options?: object) => boolean }).checkVisibility;
  if (typeof check === "function") return check.call(element, { visibilityProperty: true });
  const box = element.getBoundingClientRect();
  return box.width > 0 && box.height > 0;
}

/** Whether the window should open by itself for `node` now, from a card drawn in `chat`. */
export function shouldAutoOpen(node: LiveNode | null, chat: AgentChatStoreHook, now = Date.now()): boolean {
  if (!node || !node.created || !node.building || node.author === null) return false;
  if (now - (node.changes.find((c) => c.action === "create")?.receivedAt ?? 0) > AUTO_OPEN_WITHIN_MS) return false;
  const live = useNodeLive.getState();
  if (live.autoOpened[node.ref] || (node.sessionId && live.suppressed[node.sessionId])) return false;
  if (!isNodeAutoOpenEnabled()) return false;
  // One window: it swaps only a window that opened by itself, from this conversation.
  const peek = useNodePeek.getState().peek;
  if (peek !== null && (!peek.auto || (peek.chat ?? useAgentChatStore) !== chat)) return false;
  return true;
}

/** Open `node` beside the conversation of the card `element`, when it should. */
export function openIfDue(
  ref: string,
  node: LiveNode,
  title: string,
  chat: AgentChatStoreHook,
  element: Element | null,
): boolean {
  if (!shouldAutoOpen(node, chat) || !onScreen(element)) return false;
  if (!useNodeLive.getState().claimAutoOpen(ref)) return false;
  useNodePeek.getState().open(ref, {
    chat,
    title: node.title || title,
    auto: true,
    live: { nodeId: node.nodeId, nodeType: node.nodeType },
  });
  return true;
}
