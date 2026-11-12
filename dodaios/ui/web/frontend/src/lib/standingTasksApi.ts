/**
 * Client for the assistant's standing tasks (`/api/agent-chat/lead/standing`).
 *
 * A standing task is something the assistant looks after over time on its
 * own: it checks at its own pace, keeps notes between looks, acts inside the
 * limits the person wrote, and reports only when something matters. The
 * assistant can suggest one itself (`state: "proposed"`); the person accepts
 * or declines it.
 *
 * One list is shared by the assistant's page, its panel on the front page and
 * the suggestion card in the conversation, so an accept in one place shows in
 * the other two without a second request.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

const BASE = "/api/agent-chat/lead/standing";

export type StandingAutonomy = "watch" | "prepare" | "act";
export type StandingState = "proposed" | "active" | "paused" | "ended";
export type StandingOutcome = "" | "quiet" | "reported" | "prepared" | "acted" | "asked" | "failed" | "skipped";
export type StandingAction = "accept" | "decline" | "pause" | "resume" | "end" | "run";

export interface StandingTask {
  id: string;
  title: string;
  goal: string;
  /** How the assistant should go about it; "" leaves that to the assistant. */
  how: string;
  autonomy: StandingAutonomy;
  /** What the assistant may change on its own; required for `act`. */
  limits: string;
  state: StandingState;
  interval_min: number;
  origin: "owner" | "suggested";
  /** Why the assistant suggested it; "" for one the person wrote. */
  reason: string;
  /** The assistant's own notes between looks. Read only. */
  notes: string;
  /** The scheduler task behind it. */
  task_id: string;
  created_ms: number;
  updated_ms: number;
  last_run_ms: number | null;
  next_run_ms: number | null;
  last_outcome: StandingOutcome;
  last_summary: string;
  runs: number;
}

export interface StandingRun {
  id: string;
  standing_id: string;
  at_ms: number;
  outcome: StandingOutcome;
  summary: string;
  /** What the assistant changed in this look. */
  actions: string[];
  next_interval_min: number;
  session_id: string;
}

export interface StandingLimits {
  min_interval_min: number;
  max_interval_min: number;
  default_interval_min: number;
  /** How many tasks may be open (suggested, active or paused) at once. */
  max_open: number;
}

export interface StandingList {
  /** False while the scheduler that runs the looks is not running. */
  available: boolean;
  tasks: StandingTask[];
  limits: StandingLimits;
  autonomy: StandingAutonomy[];
}

export interface StandingDetail {
  task: StandingTask;
  /** Newest first. */
  runs: StandingRun[];
}

export interface StandingDraft {
  title: string;
  goal: string;
  how?: string;
  autonomy?: StandingAutonomy;
  limits?: string;
  interval_min?: number;
}

export type StandingPatch = Partial<StandingDraft>;

/** A refused request: the server's readable sentence and its HTTP status. */
export class StandingApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "StandingApiError";
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
  if (!response.ok) {
    const detail = body.detail;
    const message =
      typeof detail === "string"
        ? detail
        : detail && typeof detail === "object" && typeof (detail as { message?: unknown }).message === "string"
          ? (detail as { message: string }).message
          : `HTTP ${response.status}`;
    throw new StandingApiError(message, response.status);
  }
  return body as T;
}

function write(method: "POST" | "PATCH", body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function localTimezone(): string {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone ?? "";
  } catch {
    return "";
  }
}

const taskUrl = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

export const fetchStandingTasks = () => request<StandingList>(BASE);

export const fetchStandingTask = (id: string) => request<StandingDetail>(taskUrl(id));

export const createStandingTask = async (draft: StandingDraft): Promise<StandingTask> =>
  (await request<{ task: StandingTask }>(BASE, write("POST", { ...draft, timezone: localTimezone() }))).task;

export const patchStandingTask = async (id: string, patch: StandingPatch): Promise<StandingTask> =>
  (await request<{ task: StandingTask }>(taskUrl(id), write("PATCH", patch))).task;

export const postStandingAction = async (id: string, action: StandingAction): Promise<StandingTask> =>
  (await request<{ task: StandingTask }>(`${taskUrl(id)}/${action}`, write("POST"))).task;

// ----------------------------------------------------------------------
// Queries
// ----------------------------------------------------------------------

export const STANDING_KEY = ["lead", "standing"] as const;
export const STANDING_LIST_KEY = [...STANDING_KEY, "list"] as const;
export const standingDetailKey = (id: string) => [...STANDING_KEY, "task", id] as const;

const POLLS = import.meta.env.MODE !== "test";

/** A task that still counts against `max_open`. */
export function isOpen(task: StandingTask): boolean {
  return task.state !== "ended";
}

const STATE_ORDER: Record<StandingState, number> = { proposed: 0, active: 1, paused: 2, ended: 3 };

/**
 * Suggested first, then active, then paused; inside a group the newest task
 * first. By when it was created, not when it last changed: every look
 * changes a task, and a list that reshuffles after each one cannot be read.
 */
export function sortStanding(tasks: readonly StandingTask[]): StandingTask[] {
  return [...tasks]
    .filter(isOpen)
    .sort((a, b) => STATE_ORDER[a.state] - STATE_ORDER[b.state] || b.created_ms - a.created_ms);
}

/** The open standing tasks. A look happens in the background, so the list is read again now and then. */
export function useStandingTasks() {
  return useQuery<StandingList, Error>({
    queryKey: STANDING_LIST_KEY,
    queryFn: fetchStandingTasks,
    staleTime: 10_000,
    refetchInterval: POLLS ? 60_000 : false,
    retry: false,
  });
}

/** One task with its log. Starts from the list's copy, so the page never opens blank. */
export function useStandingTask(id: string, { enabled = true }: { enabled?: boolean } = {}) {
  const client = useQueryClient();
  return useQuery<StandingDetail, Error>({
    queryKey: standingDetailKey(id),
    queryFn: () => fetchStandingTask(id),
    enabled: enabled && id !== "",
    staleTime: 10_000,
    refetchInterval: POLLS ? 30_000 : false,
    retry: false,
    placeholderData: () => {
      const listed = client.getQueryData<StandingList>(STANDING_LIST_KEY)?.tasks.find((task) => task.id === id);
      return listed ? { task: listed, runs: [] } : undefined;
    },
  });
}

// ----------------------------------------------------------------------
// Writes
// ----------------------------------------------------------------------

/** The list with one task swapped in; an ended task leaves it, a new one joins it. */
function withTask(list: StandingList, task: StandingTask): StandingList {
  const rest = list.tasks.filter((row) => row.id !== task.id);
  if (!isOpen(task)) return { ...list, tasks: rest };
  const index = list.tasks.findIndex((row) => row.id === task.id);
  if (index < 0) return { ...list, tasks: [task, ...rest] };
  return { ...list, tasks: list.tasks.map((row) => (row.id === task.id ? task : row)) };
}

interface Snapshot {
  list?: StandingList;
  detail?: StandingDetail;
}

/** Shows a change before the server answers; returns what to put back if it refuses. */
async function applyLocally(
  client: QueryClient,
  id: string,
  change: (task: StandingTask) => StandingTask,
): Promise<Snapshot> {
  await client.cancelQueries({ queryKey: STANDING_KEY });
  const list = client.getQueryData<StandingList>(STANDING_LIST_KEY);
  const detail = client.getQueryData<StandingDetail>(standingDetailKey(id));
  const listed = list?.tasks.find((task) => task.id === id);
  if (list && listed) client.setQueryData(STANDING_LIST_KEY, withTask(list, change(listed)));
  if (detail) client.setQueryData(standingDetailKey(id), { ...detail, task: change(detail.task) });
  return { list, detail };
}

function putBack(client: QueryClient, id: string, snapshot: Snapshot | undefined): void {
  if (snapshot?.list) client.setQueryData(STANDING_LIST_KEY, snapshot.list);
  if (snapshot?.detail) client.setQueryData(standingDetailKey(id), snapshot.detail);
}

/** Takes the server's copy of a task into the list and its own page. */
function storeTask(client: QueryClient, task: StandingTask): void {
  const list = client.getQueryData<StandingList>(STANDING_LIST_KEY);
  if (list) client.setQueryData(STANDING_LIST_KEY, withTask(list, task));
  const detail = client.getQueryData<StandingDetail>(standingDetailKey(task.id));
  if (detail) client.setQueryData(standingDetailKey(task.id), { ...detail, task });
}

/** The state an action leads to, shown at once; `run` changes nothing to show. */
const NEXT_STATE: Partial<Record<StandingAction, StandingState>> = {
  accept: "active",
  resume: "active",
  pause: "paused",
  decline: "ended",
  end: "ended",
};

export function useStandingAction() {
  const client = useQueryClient();
  return useMutation<StandingTask, Error, { id: string; action: StandingAction }, Snapshot>({
    mutationFn: ({ id, action }) => postStandingAction(id, action),
    onMutate: ({ id, action }) => {
      const state = NEXT_STATE[action];
      return state ? applyLocally(client, id, (task) => ({ ...task, state })) : {};
    },
    onError: (_error, { id }, snapshot) => putBack(client, id, snapshot),
    onSuccess: (task) => storeTask(client, task),
    // A look that was just asked for, or a task that left the list: read the truth again.
    onSettled: (_task, _error, { id }) => {
      void client.invalidateQueries({ queryKey: STANDING_LIST_KEY });
      void client.invalidateQueries({ queryKey: standingDetailKey(id) });
    },
  });
}

export function usePatchStanding() {
  const client = useQueryClient();
  return useMutation<StandingTask, Error, { id: string; patch: StandingPatch }, Snapshot>({
    mutationFn: ({ id, patch }) => patchStandingTask(id, patch),
    onMutate: ({ id, patch }) => applyLocally(client, id, (task) => ({ ...task, ...patch })),
    onError: (_error, { id }, snapshot) => putBack(client, id, snapshot),
    onSuccess: (task) => storeTask(client, task),
  });
}

export function useCreateStanding() {
  const client = useQueryClient();
  return useMutation<StandingTask, Error, StandingDraft>({
    mutationFn: createStandingTask,
    onSuccess: (task) => {
      storeTask(client, task);
      void client.invalidateQueries({ queryKey: STANDING_LIST_KEY });
    },
  });
}
