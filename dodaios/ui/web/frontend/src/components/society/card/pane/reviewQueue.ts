/**
 * The agent's learning review queue (`GET /api/society/agents/{id}/review-queue`)
 * and its two decisions. A decided item leaves the list at once and comes back
 * with its error if the server refuses.
 */
import { useCallback } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";

import { markAnswered } from "../../attention/attentionStore";
import { requestError } from "../../data";

export type ReviewItemKind = "proposal" | "memory_share" | "memory";

export interface ReviewItem {
  id: string;
  kind: ReviewItemKind;
  /** rule | skill | routine | approval_rule | focus | team | identity, for a proposal. */
  proposal_kind: string;
  summary: string;
  reason: string;
  /** Diff-style lines: "+ " added, "- " removed, "  " unchanged. */
  preview: string[];
  path?: string;
  book?: string;
  created_ms: number;
}

export interface ReviewQueue {
  items: ReviewItem[];
  total: number;
  counts: Record<ReviewItemKind, number>;
}

export const reviewQueueKey = (agentId: string) => ["society", "review-queue", agentId] as const;

export function useReviewQueue(agentId: string, enabled = true) {
  return useQuery({
    queryKey: reviewQueueKey(agentId),
    enabled,
    retry: false,
    staleTime: 10_000,
    refetchInterval: import.meta.env.MODE === "test" ? false : 30_000,
    queryFn: async ({ signal }): Promise<ReviewQueue> => {
      const res = await fetch(`/api/society/agents/${encodeURIComponent(agentId)}/review-queue`, { signal });
      // An app restarted onto this bundle before its backend: an empty queue, not an error.
      if (res.status === 404) return { items: [], total: 0, counts: { proposal: 0, memory_share: 0, memory: 0 } };
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      return (await res.json()) as ReviewQueue;
    },
  });
}

export interface ReviewOutcome {
  id: string;
  outcome: "applied" | "rejected" | "failed" | "not_found";
  detail: string;
}

export function useDecideReviewItem(agentId: string) {
  const client = useQueryClient();
  return useCallback(
    async (item: ReviewItem, approve: boolean): Promise<ReviewOutcome> => {
      const key = reviewQueueKey(agentId);
      const before = client.getQueryData<ReviewQueue>(key);
      if (before) {
        client.setQueryData<ReviewQueue>(key, {
          ...before,
          items: before.items.filter((row) => row.id !== item.id),
          total: Math.max(0, before.total - 1),
          counts: { ...before.counts, [item.kind]: Math.max(0, before.counts[item.kind] - 1) },
        });
      }
      try {
        const res = await fetch(
          `/api/society/agents/${encodeURIComponent(agentId)}/review/${encodeURIComponent(item.id)}/${approve ? "approve" : "reject"}`,
          { method: "POST" },
        );
        if (!res.ok) {
          throw requestError((await res.json().catch(() => null)) as { detail?: unknown } | null, `HTTP ${res.status}`);
        }
        // The roster and the chat header stop asking for it at once.
        markAnswered(item.id);
        // The roster names a proposal by its bare id ("proposal:p1" -> "p1").
        markAnswered(item.id.replace(/^[a-z_]+:/, ""));
        return (await res.json()) as ReviewOutcome;
      } catch (err) {
        if (before) client.setQueryData(key, before);
        throw err;
      } finally {
        void client.invalidateQueries({ queryKey: key });
        // A yes on a proposal changes the agent itself; knowledge counts move too.
        void client.invalidateQueries({ queryKey: ["society", "roster"] });
        void client.invalidateQueries({ queryKey: ["society", "agent-knowledge", agentId] });
      }
    },
    [agentId, client],
  );
}
