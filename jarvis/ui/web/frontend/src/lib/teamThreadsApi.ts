import { useQuery, useQueryClient } from "@tanstack/react-query";
import { nextPollIn } from "@/lib/societyChatGroups";

/**
 * Team threads: one task carried by several coding agents as peers
 * (`jarvis/agent_chat/team`, REST under `/api/team-threads`).
 *
 * The three lists below are the TypeScript twins of `STATES`, `PHASES` and
 * `ENTRY_KINDS` in `jarvis/agent_chat/team/store.py`;
 * `tests/unit/agent_chat/test_team_thread_parity.py` keeps them in step.
 */
export const TEAM_THREAD_STATES = ["running", "paused", "needs_input", "done", "stopped", "failed"] as const;
export type TeamThreadState = (typeof TEAM_THREAD_STATES)[number];

export const TEAM_THREAD_PHASES = ["draft", "challenge", "converge", "build", "review", "done"] as const;
export type TeamThreadPhase = (typeof TEAM_THREAD_PHASES)[number];

export const TEAM_THREAD_ENTRY_KINDS = [
  "user", "draft", "critique", "plan", "vote", "build", "review", "fix", "notice", "summary",
] as const;
export type TeamThreadEntryKind = (typeof TEAM_THREAD_ENTRY_KINDS)[number];

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
    /** A review. */
    approve?: boolean;
    findings?: TeamFinding[];
    /** A build or a fix. */
    files?: string[];
    stat?: string;
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
    /** A summary. */
    outcome?: string;
    open?: TeamOpenPoint[];
    plan_rounds?: number;
    review_rounds?: number;
    builder?: string;
    finding_count?: number;
    blocking?: number;
  };
}

/** Something a member caught in another member's plan or work. */
export interface TeamIssue extends TeamFinding {
  seq: number;
  stage: "plan" | "review";
  round: number;
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
  state: TeamThreadState;
  phase: TeamThreadPhase;
  /** Why it waits, paused or failed: a short code the view puts into words. */
  reason: string;
  note: string;
  limits: TeamLimits;
  usage: { elapsed_ms: number; turns: number; cost_usd: number; cost_partial: boolean };
  rounds: { plan: number; review: number };
  builder: string;
  members: TeamMember[];
  entries: TeamEntry[];
  issues: TeamIssue[];
  created_ms: number;
  updated_ms: number;
}

export interface TeamThreadRow {
  team_id: string;
  title: string;
  cwd: string;
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
