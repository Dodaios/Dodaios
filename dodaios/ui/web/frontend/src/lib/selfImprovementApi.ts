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
  /**
   * A coding policy's trial only (dodaios/rsi/trainer.py): the metric it claimed
   * (`pass`, `cost` or `p`). Then `diff` and `low` are that metric's difference and
   * its lower bound, oriented so that positive is better, `high` is null (the
   * selector bounds from below only), and `n` counts requests, not tasks.
   */
  metric?: string;
  /** Requests in the other half, without the policy. */
  n_reference?: number;
  /** Each half's plain means per request. */
  arms?: { candidate: ArmMeans; reference: ArmMeans } | null;
}

/** One half of a coding policy's trial: plain means per request. */
export interface ArmMeans {
  n: number;
  /** Share of requests that passed (0 to 1). */
  pass: number | null;
  one: number | null;
  /** Fix orders per request. */
  p: number | null;
  /** USD per request, plus 0.001 USD per second of turn time. */
  cost: number | null;
  churn: number | null;
}

/** How Dodaios steers coding runs in one cell (dodaios/rsi/policy.py). */
export const POLICY_SURFACE = "coding_policy";

/** A coding policy as the page reads it (`_policy_value` in overview.py). */
export interface PolicyValue {
  /** Its answer waits for the checks, and a failed check brings the agent a fix order. */
  hold: boolean;
  /** Fix orders a run may get. */
  p_max: number;
  evidence_wait_s: number;
  /** Fixed lines the first brief carries (English: agents read them). */
  lines: string[];
}

/** What a coding policy row is about (`_policy` in overview.py). */
export interface PolicyFacts {
  cell: string;
  /** `active` (in effect) or `candidate` (on trial for half of the requests). */
  slot: string;
  /** The area of the work: backend, frontend, testing, database, infra_ci, docs, other. */
  domain: string;
  /** The requested model; `(default)` when none was named. */
  model: string;
  /** The coding CLI and its version line, e.g. `claude-cli 2.1`. */
  harness: string;
  /** What changed: hold, release, fewer_fixes, shorter_wait, brief_line. */
  kinds: string[];
  /** Lines the change adds to the first brief. */
  lines: string[];
  /** What it has to show, fixed before its data: branch A on `pass`, branch B on `cost` or `p`. */
  claim: { branch: string; target: string } | null;
}

export type ChangeState = "proposed" | "trial" | "live" | "reverted" | "blocked";

/** A how-to note the assistant wrote for itself after a tool failed and a later call worked. */
export const NOTE_SURFACE = "lesson";

export interface LearnedChange {
  id: string;
  surface: string;
  /** The parameter name, e.g. `recall.min_score`. */
  target: string;
  state: ChangeState | string;
  author: string;
  reason: string;
  /**
   * A note's own words (`surface: "lesson"`), read live from the memory; "" for a
   * parameter, and "" for a note the person has just forgotten.
   */
  text?: string;
  /** False when nothing can tell yet whether the change helps (a note it wrote for itself). */
  measured?: boolean;
  since_ms: number;
  /** The value before the change; null means the shipped default was in effect. */
  before: unknown;
  after: unknown;
  default: unknown;
  /** The catalog's one-line English description; the page words it from its own strings first. */
  doc: string;
  admitted: Measurement | null;
  last_check: Measurement | null;
  /**
   * A coding policy only (`surface: "coding_policy"`): its cell and what it
   * changes. Then `before` and `after` are {@link PolicyValue}s.
   */
  policy?: PolicyFacts;
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
  /** The same two states per part of the area, e.g. memory needed or not (absent on older points). */
  parts?: Record<string, AdvantagePart>;
}

/** One part of an area on the same sealed tasks: plain means, no range. */
export interface AdvantagePart {
  n: number;
  now_score: number;
  factory_score: number;
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

/** What a night built before measuring: tasks from the person's own memory, messages and past coding work. */
export interface NightMade {
  questions?: number;
  messages?: number;
  /** Tasks erased because the memory they name is gone. */
  forgotten?: number;
  /** Model calls the building used. */
  calls?: number;
  /** No model could be asked (no subscription or local model), so nothing was built. */
  deferred?: boolean;
  /** New tasks stored from the person's past coding work (no model asked). */
  past_work?: number;
  /** Percent points of one usage window the building used. */
  share?: number;
  /** Whether the plan's usage could be read (false: the fixed caps held). */
  usage_read?: boolean | null;
  /** Why building stopped: enough, material, budget, no_model, dry. */
  until?: string;
}

/** The replays' spending in one round, per group of domains sharing one budget. */
export interface NightCalls {
  calls: number;
  cap?: number;
  stopped?: string;
  share?: number;
  usage_read?: boolean | null;
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
  /** May be `{}`, or missing on nights recorded before tasks were built at night. */
  made?: NightMade;
  /** Replays of the lead's turns, keyed by the domains that shared a budget. */
  calls?: Record<string, NightCalls>;
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
  /** What the newest round spent (absent on an older backend, null before the first round). */
  last_round?: LastRound | null;
}

/** The newest learning round's model calls, and the most of one usage window it used. */
export interface LastRound {
  ts_ms: number;
  calls: number;
  /** Percent points of one window; null when no window could be read in that round. */
  share: number | null;
}

export interface SelfImprovementLimits {
  idle_after_s: number;
  every_s: number;
  /** The most of one usage window a round may use (0..1). */
  budget_share: number;
  /** No call starts while a usage window is this full, in percent (absent on an older backend). */
  full_percent?: number;
  /** Calls of one kind a round never goes past (absent on an older backend). */
  ceiling_calls?: number;
  /** The fixed cap of building tasks while the plan's usage cannot be read. */
  max_model_calls: number;
  /** The same while too few tasks exist to decide on (absent on an older backend). */
  ramp_model_calls?: number;
  /** The fixed cap of replaying the lead's turns while the usage cannot be read. */
  first_move_calls?: number;
}

/** One week of the person's own requests (`daily_use` in dodaios/rsi/overview.py). */
export interface DailyUseWeek {
  start_ms: number;
  turns: number;
  /** False when the week holds too little to say anything. */
  rated: boolean;
  /** Share of requests that went through without a correction, a repeat, a stop or an error (0..1); null when not rated. */
  score: number | null;
}

/** How daily use went. What happened, not a measurement of cause: the requests of one week are not those of the next. */
export interface DailyUse {
  weeks: DailyUseWeek[];
  turns: number;
  score: number | null;
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
  /** Null when there is no chat record. */
  daily_use?: DailyUse | null;
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
