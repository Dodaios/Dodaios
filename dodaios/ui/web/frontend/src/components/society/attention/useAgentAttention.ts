import { useEffect, useMemo } from "react";

import type { AttentionItem } from "./attentionApi";
import { refreshAttention, useAttentionStore } from "./attentionStore";

/** Items of one agent, oldest first, with the agent's own oldest wait. */
export interface AttentionGroup {
  agentId: string;
  items: AttentionItem[];
  sinceMs: number;
}

/** A read younger than this is fresh enough for a newly mounted view. */
const FRESH_MS = 10_000;
/**
 * The slow safety read. The socket refreshes the list on every change; this
 * only catches society items decided without a chat event.
 */
const POLL_MS = 60_000;

/** The live "needs you" list, read on mount, on window focus and every minute. */
export function useAgentAttention() {
  const list = useAttentionStore((s) => s.list);
  const status = useAttentionStore((s) => s.status);
  const count = useAttentionStore((s) => s.count);

  useEffect(() => {
    const refresh = () => {
      if (typeof document !== "undefined" && document.visibilityState === "hidden") return;
      void refreshAttention();
    };
    if (Date.now() - useAttentionStore.getState().readAt > FRESH_MS) refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    window.addEventListener("focus", refresh);
    return () => {
      window.clearInterval(timer);
      window.removeEventListener("focus", refresh);
    };
  }, []);

  const items = useMemo(() => list?.items ?? [], [list]);
  const groups = useMemo(() => groupByAgent(items), [items]);
  return {
    items,
    groups,
    count: list ? list.count : count,
    isLoading: status === "loading" || (status === "idle" && !list),
    isError: status === "error",
  };
}

/** Agents ordered by who has waited longest; each agent's items oldest first. */
export function groupByAgent(items: readonly AttentionItem[]): AttentionGroup[] {
  const byAgent = new Map<string, AttentionItem[]>();
  for (const item of items) {
    const list = byAgent.get(item.agentId) ?? [];
    list.push(item);
    byAgent.set(item.agentId, list);
  }
  return [...byAgent.entries()]
    .map(([agentId, list]) => {
      const sorted = [...list].sort((a, b) => a.sinceMs - b.sinceMs);
      return { agentId, items: sorted, sinceMs: sorted[0]?.sinceMs ?? 0 };
    })
    .sort((a, b) => a.sinceMs - b.sinceMs);
}
