/**
 * Typed client for the self-building ledger (dodaios/ui/web/self_build_routes.py).
 *
 * The shapes mirror `BuildRecord.to_json()` in dodaios/self_build/records.py;
 * the backend stays the authority. Errors arrive as `{detail: "..."}` and are
 * rethrown as `SelfBuildApiError` with the HTTP status, so a view can tell
 * "the ledger is not running" (503) from "this move is not allowed" (409).
 */

export type BuildKind = "memory" | "skill" | "routine" | "agent" | "code";
export type BuildState =
  | "proposed"
  | "building"
  | "proving"
  | "trial"
  | "kept"
  | "archived"
  | "undone"
  | "rejected"
  | "failed";
export type Autonomy = "off" | "suggest" | "trial" | "full";
export type BuildOutcome = "used" | "accepted" | "corrected" | "ignored";

export const BUILD_KINDS: readonly BuildKind[] = ["memory", "skill", "routine", "agent", "code"];

export interface BuildProof {
  passed?: boolean;
  judge?: string;
  detail?: string;
  [key: string]: unknown;
}

export interface BuildArtefact {
  type?: string;
  id?: string;
  label?: string;
  url?: string;
  /** Code builds: the repository, branch and pull request. */
  repo?: string;
  branch?: string;
  number?: number;
  draft?: boolean;
  /** Code builds: the agent-chat session id of the coding run (an Agentic IDE thread). */
  thread?: string;
  [key: string]: unknown;
}

export interface Build {
  id: string;
  kind: BuildKind;
  state: BuildState;
  signature: string;
  /** One sentence the person reads: why this build exists. */
  title: string;
  case: string;
  evidence: string[];
  proof: BuildProof;
  artefact: BuildArtefact;
  uses: number;
  outcomes: Partial<Record<BuildOutcome, number>>;
  note: string;
  created_ms: number;
  updated_ms: number;
  trial_started_ms: number;
  last_used_ms: number;
  undoable: boolean;
}

export interface SelfBuildStatus {
  enabled: boolean;
  paused: boolean;
  silent: boolean;
  autonomy: Record<BuildKind, Autonomy>;
  /** Kinds a builder is registered for; a proposal of another kind cannot be built yet. */
  builders: BuildKind[];
}

export interface BuildList {
  builds: Build[];
  status: SelfBuildStatus;
}

export interface BuildHistoryEntry {
  ts_ms: number;
  from: string;
  to: string;
  note: string;
}

export interface BuildDetail {
  build: Build;
  history: BuildHistoryEntry[];
  cost: { tokens: number; usd: number };
}

export interface BuildDigest {
  since_ms: number;
  until_ms: number;
  counts: Partial<Record<BuildState, number>>;
  live: number;
  items: Build[];
}

export interface SelfBuildSettings {
  enabled: boolean;
  silent_days: number;
  memory: Autonomy;
  skill: Autonomy;
  routine: Autonomy;
  agent: Autonomy;
  code: Autonomy;
  trial_days: number;
  trial_uses: number;
  max_builds_per_day: number;
  max_agents_per_week: number;
  max_open_trials: number;
  max_code_runs_per_day: number;
  max_rejections: number;
  /** Repositories (`owner/name`) whose loop pull requests merge after green CI. */
  code_land_repos: string[];
}

export interface SelfBuildSettingsPayload {
  settings: SelfBuildSettings;
  levels: Autonomy[];
  bounds: Partial<Record<keyof SelfBuildSettings, { min: number | null; max: number | null }>>;
}

export interface ProvenanceItem {
  build_id: string;
  type: string;
  id: string;
  state: BuildState;
  title: string;
}

export class SelfBuildApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "SelfBuildApiError";
  }
}

const BASE = "/api/self-build";

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
    throw new SelfBuildApiError(detail, res.status);
  }
  return (await res.json()) as T;
}

const post = <T>(path: string, body?: unknown) =>
  call<T>(path, { method: "POST", body: body === undefined ? undefined : JSON.stringify(body) });

export const selfBuildApi = {
  list: (signal?: AbortSignal) => call<BuildList>("", { signal }),
  detail: (id: string, signal?: AbortSignal) =>
    call<BuildDetail>(`/${encodeURIComponent(id)}`, { signal }),
  digest: (hours = 24, signal?: AbortSignal) =>
    call<BuildDigest>(`/digest?hours=${hours}`, { signal }),
  accept: (id: string) => post<{ build: Build }>(`/${encodeURIComponent(id)}/accept`),
  keep: (id: string) => post<{ build: Build }>(`/${encodeURIComponent(id)}/keep`),
  undo: (id: string, note = "") =>
    post<{ build: Build }>(`/${encodeURIComponent(id)}/undo`, { note }),
  pause: (paused: boolean) => post<SelfBuildStatus>("/pause", { paused }),
  settings: (signal?: AbortSignal) => call<SelfBuildSettingsPayload>("/settings", { signal }),
  saveSettings: (patch: Partial<SelfBuildSettings>) =>
    call<SelfBuildSettingsPayload>("/settings", { method: "PUT", body: JSON.stringify(patch) }),
  provenance: (type?: string, signal?: AbortSignal) =>
    call<{ items: Record<string, ProvenanceItem> }>(
      `/provenance${type ? `?type=${encodeURIComponent(type)}` : ""}`,
      { signal },
    ),
};

/** The society kill switch (dodaios/ui/web/society_routes.py): stops every agent. */
export const societyKillSwitchApi = {
  async status(signal?: AbortSignal): Promise<boolean> {
    const res = await fetch("/api/society/status", { signal });
    if (!res.ok) throw new SelfBuildApiError(`HTTP ${res.status}`, res.status);
    const body = (await res.json()) as { kill_switch?: unknown };
    return Boolean(body.kill_switch);
  },
  async set(engaged: boolean): Promise<void> {
    const res = await fetch(`/api/society/kill-switch${engaged ? "" : "/release"}`, {
      method: "POST",
    });
    if (!res.ok) throw new SelfBuildApiError(`HTTP ${res.status}`, res.status);
  },
};

// ------------------------------------------------------------------ reading a build

const LIFECYCLE: readonly BuildState[] = ["proposed", "building", "proving", "trial", "kept"];

/** The path a build walks, for the lifecycle rail: the five forward steps. */
export function lifecycleSteps(): readonly BuildState[] {
  return LIFECYCLE;
}

/**
 * How far along the forward path a build got: the index of its last reached
 * step. An off-path end state (archived, undone, rejected, failed) reports the
 * step it left from, read from its history when there is one.
 */
export function reachedStep(build: Build, history?: BuildHistoryEntry[]): number {
  const direct = LIFECYCLE.indexOf(build.state);
  if (direct >= 0) return direct;
  const last = history?.filter((h) => LIFECYCLE.includes(h.from as BuildState)).at(-1);
  if (last) return LIFECYCLE.indexOf(last.from as BuildState);
  if (build.state === "archived") return 3;
  if (build.state === "rejected") return 0;
  return build.trial_started_ms ? 3 : 0;
}

/** Which shelf of the view a build sits on — what, if anything, it asks of the person. */
export type Shelf = "waiting" | "trial" | "working" | "kept" | "past";

export function shelfOf(build: Build): Shelf {
  switch (build.state) {
    case "proposed":
      return "waiting";
    case "trial":
      return "trial";
    case "building":
    case "proving":
      return "working";
    case "kept":
      return "kept";
    default:
      return "past";
  }
}

export const DAY_MS = 86_400_000;

/** Days and uses of a trial against its limits; `null` when the build is not on trial. */
export function trialProgress(
  build: Build,
  limits: { trial_days: number; trial_uses: number } | undefined,
  now = Date.now(),
): { days: number; dayLimit: number; uses: number; useLimit: number; share: number } | null {
  if (build.state !== "trial" || !build.trial_started_ms || !limits) return null;
  const days = Math.max(0, Math.floor((now - build.trial_started_ms) / DAY_MS));
  const share = Math.min(
    1,
    Math.max(days / Math.max(1, limits.trial_days), build.uses / Math.max(1, limits.trial_uses)),
  );
  return { days, dayLimit: limits.trial_days, uses: build.uses, useLimit: limits.trial_uses, share };
}
