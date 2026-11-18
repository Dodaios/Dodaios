/**
 * The chat card's side of the live build: "being built", and the end of the
 * agent's turn. Small on purpose: the chat card is in the app's entry bundle.
 * Whether the node window opens by itself is decided in `autoOpen.ts`,
 * fetched the first time an agent makes a node.
 */
import { useEffect, useRef, type RefObject } from "react";

import { runningTurn } from "@/components/agentchat/reduce";
import type { AgentChatStoreHook } from "@/store/agentChat";
import { liveNodeOfRef, useNodeLive, type LiveNode } from "./liveStore";

export interface LiveCardState {
  node: LiveNode | null;
  /** The card shows "being built". */
  building: boolean;
}

/**
 * The card's live state. Ends the node's build when the agent's turn in this
 * conversation ends, and lets the node window open by itself beside it.
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
      const live = useNodeLive.getState();
      live.turnEnded(node.sessionId);
      if (useNodeLive.getState().nodes[node.nodeId]?.building) live.settle(node.nodeId);
    }
    wasRunning.current = running;
  }, [running, node]);

  /* The agent just made this node: perhaps open it beside the conversation. */
  useEffect(() => {
    if (!ref || !node || !running || !node.created || !node.building) return;
    if (useNodeLive.getState().autoOpened[ref]) return;
    void import("./autoOpen").then((auto) => auto.openIfDue(ref, node, title, chat, card.current));
  }, [ref, node, running, chat, title, card]);

  return { node, building };
}
