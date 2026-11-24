/**
 * React Query hooks for the Self-improvement page.
 *
 * Nothing here polls fast: the backend publishes `SelfChangeChanged` whenever
 * a learned change is recorded or moves, and the WebSocket invalidates
 * `selfImprovementKeys.all` (hooks/useWebSocket.ts). A night that only
 * measures moves no change, so the slow interval also brings its new point.
 */
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { selfImprovementApi, type SelfImprovementOverview } from "@/lib/selfImprovementApi";

export const selfImprovementKeys = {
  all: ["self-improvement"] as const,
  overview: () => ["self-improvement", "overview"] as const,
};

const SAFETY_POLL_MS = 5 * 60_000;

export function useSelfImprovement() {
  return useQuery({
    queryKey: selfImprovementKeys.overview(),
    queryFn: ({ signal }) => selfImprovementApi.overview(signal),
    refetchInterval: SAFETY_POLL_MS,
    retry: false,
  });
}

/** The person's stop. The answer is written into the cache, so the head repaints at once. */
export function useSelfImprovementPause() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (paused: boolean) => selfImprovementApi.pause(paused),
    onSuccess: ({ paused }) => {
      client.setQueryData<SelfImprovementOverview>(selfImprovementKeys.overview(), (old) =>
        old ? { ...old, status: { ...old.status, paused } } : old,
      );
      void client.invalidateQueries({ queryKey: selfImprovementKeys.all });
    },
  });
}

/** Take one learned change back. The row leaves the list at once; the refetch confirms it. */
export function useSelfImprovementUndo() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (id: string) => selfImprovementApi.undo(id),
    onSuccess: ({ reverted }) => {
      const gone = new Set(reverted);
      client.setQueryData<SelfImprovementOverview>(selfImprovementKeys.overview(), (old) =>
        old ? { ...old, stack: old.stack.filter((change) => !gone.has(change.id)) } : old,
      );
      void client.invalidateQueries({ queryKey: selfImprovementKeys.all });
    },
  });
}
