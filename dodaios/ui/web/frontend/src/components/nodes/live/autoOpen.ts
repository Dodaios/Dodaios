/**
 * The chat card's side of the live build: "being built", the end of the
 * agent's turn, and the node window opening by itself.
 *
 * The card of a node is posted the moment the agent creates it, into the very
 * conversation the agent works in. That makes the card the right place to
 * decide what the person sees:
 *
 * - while the agent's turn runs, the card is "being built" (the type's
 *   skeleton, a short live status line), and settles when the turn ends;
 * - when the card's conversation is on screen, the node window opens by itself
 *   beside it on the agent's create. Never while the person is elsewhere in
 *   the app (the card is not on screen then), never twice for one node, never
 *   over a node the person opened themselves, and not again in a turn whose
 *   auto-opened window the person closed. A second node of the same turn
 *   swaps into the one window. Settings > Behavior turns it off.
 */
import { useEffect, useRef, type RefObject } from "react";

import { runningTurn } from "@/components/agentchat/reduce";
import { isNodeAutoOpenEnabled } from "@/lib/nodeAutoOpen";
import { useAgentChatStore, type AgentChatStoreHook } from "@/store/agentChat";
import { useNodePeek } from "@/store/nodePeek";
import { liveNodeOfRef, useNodeLive, type LiveNode } from "./liveStore";

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

export interface LiveCardState {
  node: LiveNode | null;
  /** The card shows "being built". */
  building: boolean;
}

/**
 * The card's live state; opens the window by itself when it should, and ends
 * the node's build when the agent's turn in this conversation ends.
 */
export function useLiveCard(
  ref: string | null,
  title: string,
  chat: AgentChatStoreHook,
  card: RefObject<Element | null>,
): LiveCardState {
  const node = useNodeLive((s) => (ref ? liveNodeOfRef(s, ref) : null));
  const running = chat((s) => runningTurn(s.timeline) !== null);
  const building = node !== null && node.building && node.author !== null && running;

  /* The turn ended: the build is over (presence lingers a moment, then fades). */
  const wasRunning = useRef(running);
  useEffect(() => {
    if (wasRunning.current && !running && node?.building) {
      useNodeLive.getState().turnEnded(node.sessionId);
      if (useNodeLive.getState().nodes[node.nodeId]?.building) useNodeLive.getState().settle(node.nodeId);
    }
    wasRunning.current = running;
  }, [running, node]);

  /* The agent just made this node and its card is on screen: open it beside the conversation. */
  useEffect(() => {
    if (!ref || !node || !running) return;
    if (!shouldAutoOpen(node, chat) || !onScreen(card.current)) return;
    if (!useNodeLive.getState().claimAutoOpen(ref)) return;
    useNodePeek.getState().open(ref, {
      chat,
      title: node.title || title,
      auto: true,
      live: { nodeId: node.nodeId, nodeType: node.nodeType },
    });
  }, [ref, node, running, chat, title, card]);

  return { node, building };
}
