/**
 * A routine's runs from its task steps, the same way the backend reads them
 * (`dodaios/society/routine_history.py`). The detail panel already polls the
 * task with its steps, so this is always available; the run-history route
 * adds what only the run's chat knows (cost and summary of older runs).
 */
import type { TaskStep } from "@/lib/tasksApi";
import type { RoutineRunRow } from "./routinesApi";

export interface Run {
  id: string;
  taskId: string;
  /** Start in epoch ms (or the record's time for runs without a start). */
  timestamp: number;
  status: string;
  /** The saved result text (or the skip / failure message). */
  text: string;
  sessionId?: string;
  startedMs?: number;
  finishedMs?: number;
  /** A skipped run's reason code and seat (`skipped` step), worded by `routineSkipReason`. */
  skipCode?: string;
  skipProvider?: string;
  origin: "manual" | "automatic";
  durationMs?: number;
  costUsd?: number | null;
  billedViaKey?: boolean | null;
  provider?: string;
  model?: string;
  summary?: string;
  error?: string;
}

const firstLine = (text: string) => text.split(/\r?\n/).map((line) => line.replace(/^\s*(?:#{1,6}\s+|[-*+>]\s+|\d+[.)]\s+)/, "").replace(/(\*\*|__|`+|~~)/g, "").trim())
  .find((line) => line && !/^[-=*_|:]+$/.test(line)) ?? "";

const asNumber = (value: unknown) => (typeof value === "number" && Number.isFinite(value) ? value : undefined);

/** New runs have explicit boundaries; retain older result/error records too. */
export function routineRuns(taskId: string, steps: TaskStep[]): Run[] {
  const runs: Run[] = [];
  let current: Run | undefined;
  let manualNext = false;
  for (const step of steps) {
    const event = step.payload.event;
    const at = step.timestamp_ns / 1e6;
    const text = String(step.payload.message ?? step.payload.text ?? "");
    if (event === "run_now") {
      manualNext = true;
    } else if (event === "run_started") {
      if (current?.status === "running") current.status = "interrupted";
      current = { id: `${taskId}:${step.seq}`, taskId, timestamp: at, startedMs: at, status: "running", text: "", origin: manualNext ? "manual" : "automatic" };
      manualNext = false;
      runs.push(current);
    } else if (event === "routine_chat" && current && typeof step.payload.session_id === "string") {
      current.sessionId = step.payload.session_id;
    } else if (event === "routine_summary" && current) {
      current.durationMs = asNumber(step.payload.duration_ms) || undefined;
      current.costUsd = asNumber(step.payload.cost_usd) ?? null;
      current.billedViaKey = typeof step.payload.billed_via_key === "boolean" ? step.payload.billed_via_key : null;
      current.provider = String(step.payload.provider ?? "");
      current.model = String(step.payload.model ?? "");
    } else if (event === "agent_result" && current) {
      current.text = text;
    } else if (event === "skipped") {
      // Unattended work that may not bill its seat: no turn started. The skip
      // ends the run; an older history also logged an "error" right after it.
      const skip = { status: "skipped", text, finishedMs: at,
        skipCode: String(step.payload.code ?? ""), skipProvider: String(step.payload.provider ?? "") };
      if (current) Object.assign(current, skip);
      else { current = { id: `${taskId}:${step.seq}`, taskId, timestamp: at, origin: "automatic", ...skip }; runs.push(current); }
    } else if (["run_completed", "run_cancelled", "error", "deferred", "waiting"].includes(String(event))) {
      const status = event === "run_completed" ? "completed" : event === "run_cancelled" ? "cancelled"
        : event === "deferred" ? "pending" : event === "waiting" ? "waiting" : "failed";
      if (current?.status === "skipped") current = undefined;
      else if (current) {
        current.status = status; current.finishedMs = at;
        if (text) current.text = text;
        if (status !== "completed") current.error = text || String(step.payload.reason ?? "");
        else if (current.durationMs === undefined) current.durationMs = asNumber(step.payload.duration_ms) || undefined;
        current = undefined;
      } else runs.push({ id: `${taskId}:${step.seq}`, taskId, timestamp: at, finishedMs: at, status, text, origin: "automatic", error: status !== "completed" ? text : undefined });
    } else if (event === "agent_result") {
      // Legacy runners persisted the result before the final state transition.
      runs.push({ id: `${taskId}:${step.seq}`, taskId, timestamp: at, finishedMs: at, status: "legacy", text, origin: "automatic" });
    }
  }
  for (const run of runs) {
    if (run.durationMs === undefined && run.startedMs !== undefined && run.finishedMs !== undefined && run.finishedMs > run.startedMs) {
      run.durationMs = run.finishedMs - run.startedMs;
    }
    if (run.status !== "failed" && run.status !== "skipped") run.summary = firstLine(run.text);
  }
  return runs;
}

/** Add what the run-history route knows (cost and summary of older runs). */
export function mergeRunDetails(runs: Run[], rows: RoutineRunRow[]): Run[] {
  if (!rows.length) return runs;
  const byId = new Map(rows.map((row) => [row.id, row]));
  return runs.map((run) => {
    const row = byId.get(run.id);
    if (!row) return run;
    return {
      ...run,
      costUsd: run.costUsd ?? row.cost_usd,
      billedViaKey: run.billedViaKey ?? row.billed_via_key,
      durationMs: run.durationMs ?? row.duration_ms ?? undefined,
      summary: run.summary || row.summary || undefined,
      error: run.error || row.error || undefined,
      provider: run.provider || row.provider || undefined,
      model: run.model || row.model || undefined,
    };
  });
}
