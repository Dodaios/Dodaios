import { useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useEventStore } from "@/store/events";
import { spreadDelay } from "@/lib/connectBudget";
import type { TeamGoalState, TeamTaskState } from "@/lib/societyApi";

export interface SocietyChatGroup {
  group_id: string;
  name: string;
  members: string[];
  created_ms: number;
  updated_ms: number;
  /** The member that manages the team; absent or null = no lead. */
  lead_agent_id?: string | null;
  /** The team's standing purpose, read by its lead. */
  mission?: string;
}

async function json<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: unknown } | null;
    throw new Error(typeof body?.detail === "string" ? body.detail : `HTTP ${response.status}`);
  }
  return response.json() as Promise<T>;
}

const body = (data: unknown): RequestInit => ({
  method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(data),
});

/**
 * How long until a polled query is due again, `periodMs` on average.
 *
 * The period is spread around itself (`spreadDelay`: half to one and a half
 * times), so windows and panes that started together do not knock together
 * for ever. The spread is taken from the time of the last answer instead of
 * a fresh random number, for one reason: several components watch the same
 * query (the office stage, the team board, the agents view), each with its
 * own timer. With a number of their own they would drift apart and send one
 * request each; with the same number they stay due at the same moment and
 * React Query folds them into one request.
 *
 * `lastMs` is when the query last answered, with data or with an error (so a
 * failing endpoint is asked again after a period, not at once); 0 = not yet.
 */
export function nextPollIn(lastMs: number, periodMs: number, now: number = Date.now()): number {
  if (lastMs <= 0) return periodMs;
  const phase = (lastMs % POLL_PHASE_MS) / POLL_PHASE_MS;
  return Math.max(POLL_FLOOR_MS, lastMs + spreadDelay(periodMs, () => phase) - now);
}
/** A prime number of milliseconds: answers a few ms apart land on unrelated phases. */
const POLL_PHASE_MS = 9973;
/** An overdue poll (the machine slept) is asked this soon, not in a tight loop; small, so watchers stay in step. */
const POLL_FLOOR_MS = 250;

const GROUPS_POLL_MS = 10_000;
const ROUND_POLL_MS = 2_000;

export function useSocietyChatGroups(enabled = true) {
  return useQuery({
    queryKey: ["society", "chat-groups"],
    queryFn: async () => (await json<{ groups: SocietyChatGroup[] }>("/api/society/chat-groups")).groups,
    enabled,
    staleTime: 15_000,
    // Jittered (AP-33), and not tied to `document.visibilityState`: the desktop WebView reports a visible
    // window as hidden, which would stop this poll for good and leave a team made in chat without its studio.
    // `enabled` is what keeps a caller that is really off screen quiet.
    refetchInterval: (query) => nextPollIn(Math.max(query.state.dataUpdatedAt, query.state.errorUpdatedAt), GROUPS_POLL_MS),
    refetchIntervalInBackground: true,
  });
}

export async function createSocietyChatGroup(name: string, members: string[]) {
  return (await json<{ group: SocietyChatGroup }>("/api/society/chat-groups", body({ name, members }))).group;
}

export async function updateSocietyChatGroup(groupId: string, name: string, members: string[]) {
  return (await json<{ group: SocietyChatGroup }>(`/api/society/chat-groups/${encodeURIComponent(groupId)}`, {
    ...body({ name, members }), method: "PATCH",
  })).group;
}

export async function deleteSocietyChatGroup(groupId: string) {
  await json(`/api/society/chat-groups/${encodeURIComponent(groupId)}`, { method: "DELETE" });
}

/** A group's shared meeting: its transcript, and whether a round is answering. */
export interface SocietyMeeting {
  messages: { id: string; speaker: string; text: string }[];
  running: boolean;
  room: { state: string; settle_reason: string; next_speaker: string | null } | null;
}

const meetingUrl = (groupId: string) => `/api/society/chat-groups/${encodeURIComponent(groupId)}/meeting`;

/** One read of a group's meeting, for callers that schedule their own reads (the office's studio boards). */
export function fetchSocietyMeeting(groupId: string, signal?: AbortSignal): Promise<SocietyMeeting> {
  return signal ? json<SocietyMeeting>(meetingUrl(groupId), { signal }) : json<SocietyMeeting>(meetingUrl(groupId));
}

export function useSocietyMeeting(groupId: string) {
  return useQuery({
    queryKey: ["society", "meeting", groupId],
    queryFn: () => fetchSocietyMeeting(groupId),
    // Poll only while a round runs; an idle transcript changes only when someone sends. Jittered, and not tied
    // to `document.visibilityState` (see useSocietyChatGroups): a running round must not freeze in the desktop window.
    refetchInterval: (query) => (query.state.data?.running
      ? nextPollIn(Math.max(query.state.dataUpdatedAt, query.state.errorUpdatedAt), ROUND_POLL_MS) : false),
    refetchIntervalInBackground: true,
  });
}

export async function sendSocietyMeeting(groupId: string, text: string) {
  return json<SocietyMeeting>(meetingUrl(groupId), body({ text }));
}

export async function stopSocietyMeeting(groupId: string) {
  return json<SocietyMeeting>(`${meetingUrl(groupId)}/stop`, { method: "POST" });
}

/** One task a team lead handed to a member. */
export interface SocietyTeamTask {
  task_id: string;
  goal_id: string;
  agent_id: string;
  title: string;
  brief: string;
  state: TeamTaskState;
  result: string;
  reviewed: boolean;
  created_ms: number;
  updated_ms: number;
  done_ms: number | null;
}

/** A goal the person gave a team, with the tasks its lead handed out. */
export interface SocietyTeamGoal {
  goal_id: string;
  group_id: string;
  lead_agent_id: string;
  title: string;
  text: string;
  state: TeamGoalState;
  /** The lead's latest report: an update, its question, or the result. */
  report: string;
  /** Why the goal waits: a code (`turn_budget`), or `error:<detail>`. */
  note: string;
  lead_turns: number;
  /** Where it came from: `chat` (the person, in the lead's chat), `board`, `jarvis`, `assignment`, or `lead` (its own initiative). */
  source: string;
  created_ms: number;
  updated_ms: number;
  done_ms: number | null;
  tasks: SocietyTeamTask[];
}

/** A team as its board shows it. Reading it never starts a turn. */
export interface SocietyTeam {
  group_id: string;
  lead_agent_id: string | null;
  lead_available: boolean;
  mission: string;
  /** Minutes between the lead's unprompted looks at the team; 0 = off. */
  checkin_minutes: number;
  /** Whether such a look may also set the team's next goal from its mission. */
  initiative: boolean;
  goals: SocietyTeamGoal[];
  /** Whether the lead is in a managing turn right now. */
  working: boolean;
  max_lead_turns: number;
}

/** Goal states in which the lead or a member may still act. */
export const TEAM_GOAL_OPEN: readonly TeamGoalState[] = ["queued", "running", "needs_input", "paused"];

const teamUrl = (groupId: string) => `/api/society/chat-groups/${encodeURIComponent(groupId)}`;
const teamKey = (groupId: string) => ["society", "team", groupId] as const;

/** Bus event names that mean "a team board changed" (jarvis/core/events.py). */
const TEAM_EVENTS = new Set(["SocietyTeamChanged"]);

/**
 * A team's lead, mission, goals and tasks, kept live by the `SocietyTeamChanged`
 * push the WebSocket forwards, with a slow poll as the safety net while a goal
 * is open.
 */
export function useSocietyTeam(groupId: string, enabled = true) {
  const client = useQueryClient();
  const query = useQuery({
    queryKey: teamKey(groupId),
    queryFn: () => json<SocietyTeam>(`${teamUrl(groupId)}/team`),
    enabled,
    staleTime: 1_000,
    refetchInterval: (current) =>
      current.state.data?.goals.some((goal) => TEAM_GOAL_OPEN.includes(goal.state)) ? 5_000 : false,
  });
  useEffect(() => {
    if (!enabled) return;
    let lastId: string | null = useEventStore.getState().events[0]?.id ?? null;
    return useEventStore.subscribe((state) => {
      const top = state.events[0];
      if (!top || top.id === lastId) return;
      lastId = top.id;
      if (!TEAM_EVENTS.has(top.name)) return;
      const payload = top.payload as { group_id?: string; reason?: string } | undefined;
      if (payload?.group_id && payload.group_id !== groupId) return;
      void client.invalidateQueries({ queryKey: teamKey(groupId) });
      // A new lead is a roster change and a group change too.
      if (payload?.reason === "lead") {
        void client.invalidateQueries({ queryKey: ["society", "chat-groups"] });
        void client.invalidateQueries({ queryKey: ["society", "roster"] });
      }
    });
  }, [client, enabled, groupId]);
  return query;
}

export function setSocietyTeamLead(groupId: string, agentId: string | null) {
  return json<SocietyTeam>(`${teamUrl(groupId)}/lead`, { ...body({ agent_id: agentId }), method: "PUT" });
}

/** Create a new agent whose job is managing this team, and make it the lead. */
export function createSocietyTeamLead(groupId: string) {
  return json<SocietyTeam>(`${teamUrl(groupId)}/lead`, body({}));
}

export function setSocietyTeamMission(groupId: string, mission: string) {
  return json<SocietyTeam>(`${teamUrl(groupId)}/mission`, { ...body({ mission }), method: "PUT" });
}

export function setSocietyTeamCheckin(groupId: string, minutes: number, initiative = false) {
  return json<SocietyTeam>(`${teamUrl(groupId)}/checkin`, { ...body({ minutes, initiative }), method: "PUT" });
}

export function startSocietyTeamGoal(groupId: string, text: string) {
  return json<SocietyTeam>(`${teamUrl(groupId)}/goals`, body({ text }));
}

const goalUrl = (groupId: string, goalId: string) => `${teamUrl(groupId)}/goals/${encodeURIComponent(goalId)}`;

export function messageSocietyTeamGoal(groupId: string, goalId: string, text: string) {
  return json<SocietyTeam>(`${goalUrl(groupId, goalId)}/message`, body({ text }));
}

export function resumeSocietyTeamGoal(groupId: string, goalId: string) {
  return json<SocietyTeam>(`${goalUrl(groupId, goalId)}/resume`, { method: "POST" });
}

export function cancelSocietyTeamGoal(groupId: string, goalId: string) {
  return json<SocietyTeam>(`${goalUrl(groupId, goalId)}/cancel`, { method: "POST" });
}
