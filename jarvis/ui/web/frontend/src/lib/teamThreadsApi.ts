import { useQuery, useQueryClient } from "@tanstack/react-query";
import { nextPollIn } from "@/lib/societyChatGroups";

/**
 * Team threads: one task carried by several coding agents as peers
 * (`jarvis/agent_chat/team`, REST under `/api/team-threads`).
 *
 * The lists below are the TypeScript twins of `STATES`, `PHASES`,
 * `ENTRY_KINDS`, `MODES`, `ROLES` and `STEP_STATUSES` in
 * `jarvis/agent_chat/team/store.py`;
 * `tests/unit/agent_chat/test_team_thread_parity.py` keeps them in step.
 */
export const TEAM_THREAD_STATES = ["running", "paused", "needs_input", "done", "stopped", "failed"] as const;
export type TeamThreadState = (typeof TEAM_THREAD_STATES)[number];

export const TEAM_THREAD_PHASES = [
  "draft", "challenge", "converge", "build", "review", "planning", "steps", "final", "done",
] as const;
export type TeamThreadPhase = (typeof TEAM_THREAD_PHASES)[number];

/** The steps each mode works through, in order (both end in "done"). */
export const PEER_PHASES = ["draft", "challenge", "converge", "build", "review"] as const satisfies readonly TeamThreadPhase[];
export const PLANNED_PHASES = ["planning", "steps", "final"] as const satisfies readonly TeamThreadPhase[];

export const TEAM_THREAD_ENTRY_KINDS = [
  "user", "draft", "critique", "plan", "vote", "build", "review", "fix",
  "plan_version", "plan_review", "step_build", "step_review", "notice", "summary",
] as const;
export type TeamThreadEntryKind = (typeof TEAM_THREAD_ENTRY_KINDS)[number];

/** Peers plan, build and review together; or one plans, one builds, the others review. */
export const TEAM_THREAD_MODES = ["peers", "planner_builder"] as const;
export type TeamThreadMode = (typeof TEAM_THREAD_MODES)[number];

export const TEAM_THREAD_ROLES = ["planner", "builder", "reviewer"] as const;
export type TeamRole = (typeof TEAM_THREAD_ROLES)[number];

export const TEAM_PLAN_STEP_STATUSES = ["open", "building", "in_review", "changes", "accepted"] as const;
export type TeamPlanStepStatus = (typeof TEAM_PLAN_STEP_STATUSES)[number];

export interface TeamSeat {
  provider: string;
  label: string;
  family: string;
  runner: string;
  /** The Agentic IDE's key of the coding CLI this seat runs; "" on an API seat. */
  agent: string;
  model: string;
  models: string[];
  ready: boolean;
  local: boolean;
}

export interface TeamSeatPick {
  provider: string;
  model?: string;
  effort?: string;
  /** Planner and builder mode only; left out = by position (plans, builds, reviews). */
  role?: TeamRole;
}

export interface TeamSeats {
  seats: TeamSeat[];
  default: TeamSeatPick[];
  min_members: number;
  max_members: number;
}

export interface TeamMember {
  member_id: string;
  name: string;
  provider: string;
  model: string;
  effort: string;
  family: string;
  /** The member's own thread: every tool call and diff of its turns. */
  session_id: string;
  state: "active" | "left";
  left_reason: string;
  working: boolean;
  since_ms: number;
  /** Its running turn waits for the person (an approval card in its thread). */
  waiting: boolean;
  /** Planner and builder mode: what the member does; "" for peers. */
  role: TeamRole | "";
}

export interface TeamFinding {
  severity: "blocking" | "minor";
  where: string;
  issue: string;
  fix: string;
}

export interface TeamOpenPoint {
  member_id: string;
  name: string;
  items: string[];
}

/** One step of a plan as the planner wrote it. */
export interface TeamPlanStepText {
  title: string;
  goal: string;
  done_when: string;
}

export interface TeamEntry {
  seq: number;
  ts_ms: number;
  kind: TeamThreadEntryKind;
  /** A member id, "user" or "team". */
  author: string;
  phase: TeamThreadPhase;
  round: number;
  payload: {
    text?: string;
    /** A vote. */
    agree?: boolean;
    objections?: string[];
    /** The plan a vote or a plan review is on, by its entry's seq. */
    plan_seq?: number;
    /** A review. */
    approve?: boolean;
    findings?: TeamFinding[];
    /** A build or a fix. */
    files?: string[];
    stat?: string;
    /** A plan version: readable or not, its steps, the accepted steps it carries over. */
    valid?: boolean;
    steps?: TeamPlanStepText[];
    carried?: number[];
    version?: number;
    /** A step build or step review: which step of which plan version. */
    number?: number;
    title?: string;
    status?: "done" | "blocked";
    plan_change?: string;
    /** A notice. */
    code?: string;
    member_id?: string;
    model?: string;
    error?: string;
    note?: string;
    step?: string;
    rounds?: number;
    by?: string;
    after?: string;
    count?: number;
    role?: TeamRole;
    mode?: TeamThreadMode;
    /** A summary. */
    outcome?: string;
    open?: TeamOpenPoint[];
    plan_rounds?: number;
    review_rounds?: number;
    builder?: string;
    finding_count?: number;
    blocking?: number;
    step_count?: number;
    step_rounds?: number;
    open_steps?: number;
  };
}

/** One step of the living plan and where it stands. */
export interface TeamPlanStep extends TeamPlanStepText {
  number: number;
  status: TeamPlanStepStatus;
  /** Who holds the step right now: its builder, or the reviewers still to read it. */
  holders: string[];
  /** Build rounds so far (a fix after a review is a round). */
  rounds: number;
  /** The person accepted it with findings still open. */
  open_findings: boolean;
}

/** The planner's living plan: its newest version, proposed or agreed. */
export interface TeamPlan {
  version: number;
  seq: number;
  agreed: boolean;
  author: string;
  versions: number;
  /** The builder's open request for a new version. */
  revision: { step: number; title: string; status: string; note: string; plan_change: string; by: string } | null;
  steps: TeamPlanStep[];
}

/** Something a member caught in another member's plan or work. */
export interface TeamIssue extends TeamFinding {
  seq: number;
  stage: "plan" | "step" | "review";
  round: number;
  /** The plan step a step finding is about. */
  number?: number;
  by: string;
  resolved: boolean;
}

export interface TeamLimits {
  max_minutes: number;
  max_turns: number;
  plan_rounds: number;
  review_rounds: number;
  turn_minutes: number;
  max_cost_usd: number;
}

export interface TeamThread {
  team_id: string;
  title: string;
  task: string;
  cwd: string;
  mode: TeamThreadMode;
  state: TeamThreadState;
  phase: TeamThreadPhase;
  /** Why it waits, paused or failed: a short code the view puts into words. */
  reason: string;
  note: string;
  limits: TeamLimits;
  usage: { elapsed_ms: number; turns: number; cost_usd: number; cost_partial: boolean };
  /** Planner and builder mode adds the current step and the bands' round keys. */
  rounds: { plan: number; review: number; step?: number; plan_round?: number; final?: number };
  builder: string;
  members: TeamMember[];
  /** The living plan; null for peers. */
  plan: TeamPlan | null;
  entries: TeamEntry[];
  issues: TeamIssue[];
  created_ms: number;
  updated_ms: number;
}

export interface TeamThreadRow {
  team_id: string;
  title: string;
  cwd: string;
  mode: TeamThreadMode;
  state: TeamThreadState;
  phase: TeamThreadPhase;
  reason: string;
  created_ms: number;
  updated_ms: number;
  members: Pick<TeamMember, "member_id" | "name" | "provider" | "family" | "state">[];
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

const post = (data?: unknown): RequestInit => ({
  method: "POST",
  headers: { "Content-Type": "application/json" },
  body: data === undefined ? undefined : JSON.stringify(data),
});

const base = "/api/team-threads";
const one = (teamId: string) => `${base}/${encodeURIComponent(teamId)}`;

export const TEAM_THREADS_KEY = ["team-threads"] as const;
export const teamThreadKey = (teamId: string) => ["team-threads", teamId] as const;

const LIST_POLL_MS = 8_000;
const WORKING_POLL_MS = 2_000;
const IDLE_POLL_MS = 15_000;

const lastAnswer = (state: { dataUpdatedAt: number; errorUpdatedAt: number }) =>
  Math.max(state.dataUpdatedAt, state.errorUpdatedAt);

/** Every team thread. Polled with jitter (AP-33); `enabled` keeps an off-screen list quiet. */
export function useTeamThreads(enabled = true) {
  return useQuery({
    queryKey: TEAM_THREADS_KEY,
    queryFn: async () => (await json<{ threads: TeamThreadRow[] }>(base)).threads,
    enabled,
    refetchInterval: (query) => nextPollIn(lastAnswer(query.state), LIST_POLL_MS),
    refetchIntervalInBackground: true,
  });
}

/** One shared thread: fast while the team works, slow while it rests. */
export function useTeamThread(teamId: string | null, enabled = true) {
  const client = useQueryClient();
  return useQuery({
    queryKey: teamThreadKey(teamId ?? ""),
    // Entries never change once filed: each poll asks only for the new ones.
    queryFn: async () => {
      const known = client.getQueryData<TeamThread>(teamThreadKey(teamId ?? ""))?.entries ?? [];
      const after = known.length ? known[known.length - 1].seq : 0;
      const next = await json<TeamThread>(`${one(teamId ?? "")}?after=${after}`);
      return { ...next, entries: [...known, ...next.entries.filter((entry) => entry.seq > after)] };
    },
    enabled: enabled && Boolean(teamId),
    refetchInterval: (query) => nextPollIn(
      lastAnswer(query.state),
      query.state.data?.state === "running" ? WORKING_POLL_MS : IDLE_POLL_MS,
    ),
    refetchIntervalInBackground: true,
  });
}

export function useTeamSeats(enabled = true) {
  return useQuery({
    queryKey: ["team-threads", "seats"],
    queryFn: () => json<TeamSeats>(`${base}/seats`),
    enabled,
    staleTime: 30_000,
  });
}

export function startTeamThread(input: {
  task: string;
  cwd: string;
  seats: TeamSeatPick[];
  limits?: Partial<TeamLimits>;
  mode?: TeamThreadMode;
}) {
  return json<TeamThread>(base, post(input));
}

export const messageTeamThread = (teamId: string, text: string) =>
  json<TeamThread>(`${one(teamId)}/message`, post({ text }));

export type TeamCommand = "pause" | "resume" | "accept" | "stop";

export const commandTeamThread = (teamId: string, command: TeamCommand) =>
  json<TeamThread>(`${one(teamId)}/${command}`, post());

export const deleteTeamThread = (teamId: string) =>
  json<{ deleted: boolean }>(one(teamId), { method: "DELETE" });
