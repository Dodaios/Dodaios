/**
 * Typed client for the Self-improvement page (dodaios/ui/web/self_improvement_routes.py).
 *
 * The shapes mirror `overview.build()` in dodaios/rsi/overview.py, pinned by
 * tests/unit/ui/web/test_self_improvement_routes.py; the backend stays the
 * authority. The person has exactly two controls here: stop (and resume), and
 * take one learned change back. Errors arrive as `{detail: "..."}` and are
 * rethrown with the HTTP status, so the page can tell "the loop is not
 * running" (503) from "this change is no longer in effect" (409).
 */

/** One stored measurement of a change, flattened (`_measurement` in overview.py). */
export interface Measurement {
  ts_ms: number;
  /** `admit` (letting it in, on the select tasks) or `settle` (keeping it, on the guard tasks). */
  step: string;
  verdict: string;
  split: string;
  /** The kernel's own English reason, shown as it is, only in the details. */
  reason: string;
  domain: string;
  /** Mean per-task difference of the scores (-1 to 1); null when nothing was measured. */
  diff: number | null;
  low: number | null;
  high: number | null;
  n: number;
  /** Mean cost per task, change minus without it. For the recall it is prompt tokens. */
  cost_diff: number | null;
}

export type ChangeState = "proposed" | "trial" | "live" | "reverted" | "blocked";

export interface LearnedChange {
  id: string;
  surface: string;
  /** The parameter name, e.g. `recall.min_score`. */
  target: string;
  state: ChangeState | string;
  author: string;
  reason: string;
  since_ms: number;
  /** The value before the change; null means the shipped default was in effect. */
  before: unknown;
  after: unknown;
  default: unknown;
  /** The catalog's one-line English description; the page words it from its own strings first. */
  doc: string;
  admitted: Measurement | null;
  last_check: Measurement | null;
}

/** One measured point of the learned advantage (a row of `series` in bench.db). */
export interface AdvantagePoint {
  ts_ms: number;
  /** The app version that measured it: a change between two points is an update. */
  app: string;
  domain: string;
  split: string;
  source: string;
  now_score: number;
  factory_score: number;
  diff: number;
  low: number;
  high: number;
  n: number;
  now_tokens: number;
  factory_tokens: number;
}

export interface DomainSummary {
  domain: string;
  /** The person's own tasks per split (practice, select, guard, sealed). */
  tasks: Record<string, number>;
  tasks_total: number;
  all_tasks: Record<string, number>;
  measured: boolean;
  point: AdvantagePoint | null;
}

export interface Effect {
  domain: string;
  diff: number;
  low: number;
  high: number;
  n: number;
  cost_diff: number;
}

export interface NightDecision {
  change_id: string;
  target: string;
  /** admitted / declined / waiting (decided), kept / taken back / waiting (settled). */
  outcome: string;
  was: string;
  evidence: {
    verdict: string;
    target: Effect | null;
    split: string;
    reason: string;
  };
}

export interface NightProposal {
  target: string;
  value: unknown;
  current: unknown;
  reason: string;
  learner: string;
}

export interface Night {
  ts_ms: number;
  app: string;
  paused: boolean;
  /** The app version of the night before, when it differs: an update happened. */
  updated_from: string;
  tasks?: Record<string, Record<string, number>>;
  settled: NightDecision[];
  proposed: NightProposal[];
  decided: NightDecision[];
  measured: AdvantagePoint[];
}

export interface RestingValue {
  name: string;
  stored_as: string;
  value: unknown;
  base: unknown;
  status: string;
  why: string;
}

export interface SelfImprovementStatus {
  app: string;
  paused: boolean;
  readonly: boolean;
  last_night_ms: number;
  next_night_ms: number;
  decides_on: string[];
  own_tasks: boolean;
}

export interface SelfImprovementLimits {
  idle_after_s: number;
  every_s: number;
  budget_share: number;
}

export interface SelfImprovementOverview {
  status: SelfImprovementStatus;
  limits: SelfImprovementLimits;
  domains: DomainSummary[];
  series: AdvantagePoint[];
  stack: LearnedChange[];
  candidates: LearnedChange[];
  nights: Night[];
  resting: RestingValue[];
  now_ms: number;
}

export class SelfImprovementApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "SelfImprovementApiError";
  }
}

const BASE = "/api/self-improvement";

async function call<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    ...init,
    headers: init?.body ? { "Content-Type": "application/json", ...init.headers } : init?.headers,
  });
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const body = (await res.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      /* not JSON */
    }
    throw new SelfImprovementApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

export const selfImprovementApi = {
  overview: (signal?: AbortSignal) => call<SelfImprovementOverview>("", { signal }),
  pause: (paused: boolean) =>
    call<{ ok: boolean; paused: boolean }>("/pause", { method: "POST", body: JSON.stringify({ paused }) }),
  undo: (id: string) =>
    call<{ ok: boolean; reverted: string[] }>(`/changes/${encodeURIComponent(id)}/undo`, { method: "POST" }),
};
