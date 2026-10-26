/**
 * Run history, newest runs and away-parking for an agent's routines.
 *
 * Every hook here is enrichment: a backend without these routes (an older
 * build, a test) answers with an error and the panels fall back to what the
 * routine list already shows. Nothing retries loudly.
 */
import { useQueries, useQuery, useQueryClient } from "@tanstack/react-query";

export interface RoutineRunRow {
  id: string;
  task_id: string;
  status: string;
  origin: "manual" | "automatic" | string;
  started_ms: number | null;
  finished_ms: number | null;
  duration_ms: number | null;
  cost_usd: number | null;
  billed_via_key: boolean | null;
  provider: string;
  model: string;
  session_id: string;
  summary: string;
  error: string;
  skip_code: string;
  skip_provider: string;
}

export interface ParkingView {
  enabled: boolean;
  days: number;
  banner: boolean;
  parked_ids: string[];
  parked_ms: number;
  parked_days: number;
  unread: number;
  never_ask: boolean;
}

export interface RoutineActivity {
  lastRuns: Record<string, RoutineRunRow | null>;
  parking: ParkingView | null;
}

export type ParkingChoice = "keep_running" | "keep_paused" | "never_ask" | "ask_again";

const live = import.meta.env.MODE !== "test";
const base = (agentId: string) => `/api/society/agents/${encodeURIComponent(agentId)}`;

async function readJson<T>(response: Response): Promise<T> {
  const body = await response.json().catch(() => null) as (T & { detail?: unknown }) | null;
  if (!response.ok) throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
  return body as T;
}

export const activityKey = (agentId: string) => ["society", "routine-activity", agentId] as const;
export const runsKey = (agentId: string, taskId: string) => ["society", "routine-runs", agentId, taskId] as const;

/** Each routine's newest run plus the agent's parking banner. */
export function useRoutineActivity(agentId: string | null) {
  return useQuery({
    queryKey: activityKey(agentId ?? ""),
    enabled: Boolean(agentId),
    retry: false,
    staleTime: 5_000,
    refetchInterval: live ? 15_000 : false,
    queryFn: async (): Promise<RoutineActivity> => {
      const body = await readJson<{ last_runs?: Record<string, RoutineRunRow | null>; parking?: ParkingView }>(
        await fetch(`${base(agentId ?? "")}/routines-activity`),
      );
      return { lastRuns: body.last_runs ?? {}, parking: body.parking ?? null };
    },
  });
}

/** The runs of every member task of one routine, merged newest first. */
export function useRoutineRuns(agentId: string, taskIds: string[], fast = false) {
  const queries = useQueries({
    queries: taskIds.map((taskId) => ({
      queryKey: runsKey(agentId, taskId),
      retry: false,
      refetchInterval: live ? (fast ? 3_000 : 15_000) : false,
      queryFn: async (): Promise<RoutineRunRow[]> => {
        const body = await readJson<{ runs?: RoutineRunRow[] }>(
          await fetch(`${base(agentId)}/routines/${encodeURIComponent(taskId)}/runs?limit=50`),
        );
        return body.runs ?? [];
      },
    })),
  });
  const runs = queries.flatMap((query) => query.data ?? [])
    .sort((a, b) => (b.started_ms ?? b.finished_ms ?? 0) - (a.started_ms ?? a.finished_ms ?? 0));
  return {
    runs,
    loading: queries.some((query) => query.isPending),
    unavailable: queries.length > 0 && queries.every((query) => query.isError),
  };
}

/** Refresh every routine view of one agent after an action. */
export function useRoutineRefresh(agentId: string) {
  const client = useQueryClient();
  return () => Promise.all([
    client.invalidateQueries({ queryKey: ["tasks"] }),
    client.invalidateQueries({ queryKey: ["society", "agent-routines", agentId] }),
    client.invalidateQueries({ queryKey: ["society", "routine-activity", agentId] }),
    client.invalidateQueries({ queryKey: ["society", "routine-runs", agentId] }),
  ]);
}

const SEEN_EVERY_MS = 60_000;
const lastSeen = new Map<string, number>();

/**
 * The person looked at this agent's routine results. Throttled to one
 * request a minute per agent; failures are ignored (it only feeds parking).
 */
export function markRoutinesSeen(agentId: string, now = Date.now()): void {
  if (!agentId) return;
  const previous = lastSeen.get(agentId) ?? 0;
  if (now - previous < SEEN_EVERY_MS) return;
  lastSeen.set(agentId, now);
  void fetch(`${base(agentId)}/routines-seen`, { method: "POST" }).catch(() => undefined);
}

/** Test helper: forget the throttle. */
export function resetSeenThrottle(): void {
  lastSeen.clear();
}

export async function answerParking(agentId: string, choice: ParkingChoice): Promise<ParkingView> {
  const body = await readJson<{ parking: ParkingView }>(await fetch(`${base(agentId)}/routines-parking`, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ choice }),
  }));
  return body.parking;
}

export function useParkingDays() {
  return useQuery({
    queryKey: ["society", "routine-parking-days"],
    retry: false,
    staleTime: 60_000,
    queryFn: async () => (await readJson<{ days: number }>(await fetch("/api/society/routine-parking"))).days,
  });
}

export async function saveParkingDays(days: number): Promise<number> {
  const body = await readJson<{ days: number }>(await fetch("/api/society/routine-parking", {
    method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ days }),
  }));
  return body.days;
}
