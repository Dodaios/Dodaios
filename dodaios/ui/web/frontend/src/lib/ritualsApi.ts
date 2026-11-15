/**
 * Client for the person's rituals (`/api/agent-chat/lead/rituals`).
 *
 * A ritual is a sequence the person wrote beforehand and starts with a short
 * phrase, said after the wake word or typed into the chat. Its `now` steps
 * happen the moment the phrase is said; its `ahead` steps (the news, the open
 * pull requests) are gathered by the assistant before that and kept back
 * until the phrase is said.
 *
 * One list is shared by the assistant's panel and the dialog that changes a
 * ritual, so a change in one shows in the other without a second request.
 */
import { useMutation, useQuery, useQueryClient, type QueryClient } from "@tanstack/react-query";

const BASE = "/api/agent-chat/lead/rituals";

/** When a step happens: the moment the phrase is said, or ahead of it. */
export type RitualWhen = "now" | "ahead";
/** Where the gathering of today's `ahead` steps stands; "" while it has not begun. */
export type RitualPrepState = "" | "running" | "ready" | "failed";

/** The one tool call a step comes down to. */
export interface RitualStepCall {
  tool: string;
  args: Record<string, unknown>;
  /** The call in a few plain words for the person: "YouTube Music: liked songs". */
  says: string;
}

export interface RitualStep {
  id: string;
  when: RitualWhen;
  /** What should happen, in the person's own words. */
  text: string;
  /**
   * Only a `now` step can have one. Such a step is done at once when the
   * phrase is said, without a model; a step without it takes an ordinary turn.
   */
  call?: RitualStepCall;
}

export interface Ritual {
  id: string;
  name: string;
  /** What the person says to start it, as they wrote it. */
  phrases: string[];
  enabled: boolean;
  /** `HH:MM` on the person's clock; both empty means any time of day. */
  window_from: string;
  window_to: string;
  /** Monday is 0; empty means every day. */
  weekdays: number[];
  /** The phrase starts it only the first time on a day. */
  once_per_day: boolean;
  /** `HH:MM` from which the `ahead` steps are gathered; "" leaves that to the window. */
  prepare_from: string;
  steps: RitualStep[];
  /** The scheduler task behind the gathering; "" while there is none. */
  task_id: string;
  origin: "owner" | "assistant";
  created_ms: number;
  updated_ms: number;
}

/** One local day of a ritual: what was gathered for it and whether it ran. */
export interface RitualToday {
  /** `YYYY-MM-DD` on the person's clock. */
  day: string;
  prep_state: RitualPrepState;
  /** Why the gathering failed; "" otherwise. */
  prep_error: string;
  prepared_ms: number | null;
  fired_ms: number | null;
  /** How it was started: by voice, in the chat, with the button or by the assistant. */
  fired_via: string;
  /** What each `now` step did, in short lines. */
  results: string[];
  /** When the gathered result reached the person; null while it is owed. */
  delivered_ms: number | null;
  /** When its phrase started it on this day; a click on "Run now" does not count. */
  phrase_ms: number | null;
}

/** A day with what was gathered for it: made for the ear, and written out. */
export interface RitualTodayText extends RitualToday {
  spoken: string;
  written: string;
}

/** A ritual in the list, with where it stands today. */
export interface ListedRitual extends Ritual {
  today: RitualToday | null;
}

export interface RitualLimits {
  max_rituals: number;
  max_name_chars: number;
  max_phrases: number;
  max_phrase_words: number;
  max_phrase_chars: number;
  /** How many steps a ritual takes, both kinds together. */
  max_steps: number;
  max_step_chars: number;
  when: RitualWhen[];
}

export interface RitualList {
  available: boolean;
  rituals: ListedRitual[];
  limits: RitualLimits;
}

/** A ritual and where it stands today, the way every write answers. */
export interface RitualView {
  ritual: Ritual;
  today: RitualToday | null;
}

/** A ritual as its own request reads it: with the text that was gathered today. */
export interface RitualDetail {
  ritual: Ritual;
  today: RitualTodayText | null;
}

export interface RitualRun extends RitualView {
  /** What is gathered ahead was not ready and follows in a second card. */
  pending: boolean;
}

export interface RitualPrepare extends RitualView {
  /** False when a gathering was already under way. */
  started: boolean;
}

/**
 * A step as it is sent: one that is only reworded keeps its id, a new one has
 * none. Its tool call goes back only with the sentence it was read with; a
 * reworded sentence is no longer what that call does.
 */
export interface RitualStepDraft {
  id?: string;
  when: RitualWhen;
  text: string;
  call?: RitualStepCall;
}

export interface RitualDraft {
  name: string;
  phrases: string[];
  steps: RitualStepDraft[];
  enabled?: boolean;
  window_from?: string;
  window_to?: string;
  weekdays?: number[];
  once_per_day?: boolean;
  prepare_from?: string;
}

export type RitualPatch = Partial<RitualDraft>;

/** A refused request: the server's readable sentence and its HTTP status. */
export class RitualApiError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
    this.name = "RitualApiError";
  }
}

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  const body = (await response.json().catch(() => ({}))) as { detail?: unknown };
  if (!response.ok) {
    const detail = body.detail;
    throw new RitualApiError(typeof detail === "string" && detail ? detail : `HTTP ${response.status}`, response.status);
  }
  return body as T;
}

function write(method: "POST" | "PATCH", body?: unknown): RequestInit {
  return body === undefined
    ? { method }
    : { method, headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

const ritualUrl = (id: string) => `${BASE}/${encodeURIComponent(id)}`;

export const fetchRituals = () => request<RitualList>(BASE);

export const fetchRitual = (id: string) => request<RitualDetail>(ritualUrl(id));

export const createRitual = (draft: RitualDraft) => request<RitualView>(BASE, write("POST", draft));

export const patchRitual = (id: string, patch: RitualPatch) => request<RitualView>(ritualUrl(id), write("PATCH", patch));

export const deleteRitual = (id: string) => request<{ ok: boolean; id: string }>(ritualUrl(id), { method: "DELETE" });

/** Starts the ritual now, whatever the clock says. */
export const runRitual = (id: string) => request<RitualRun>(`${ritualUrl(id)}/run`, write("POST"));

/** Gathers now what the ritual wants ready ahead. */
export const prepareRitual = (id: string) => request<RitualPrepare>(`${ritualUrl(id)}/prepare`, write("POST"));

/** Whether the ritual has something to gather before its phrase is said. */
export function gathersAhead(ritual: Pick<Ritual, "steps">): boolean {
  return ritual.steps.some((step) => step.when === "ahead");
}

/** A moment as the time of day on the person's clock, written like a ritual's own times: "08:05". */
export function clockOf(ms: number): string {
  const at = new Date(ms);
  return `${String(at.getHours()).padStart(2, "0")}:${String(at.getMinutes()).padStart(2, "0")}`;
}

// ----------------------------------------------------------------------
// Queries
// ----------------------------------------------------------------------

export const RITUALS_KEY = ["lead", "rituals"] as const;
export const ritualDetailKey = (id: string) => [...RITUALS_KEY, id] as const;

const POLLS = import.meta.env.MODE !== "test";

/** Every ritual with where it stands today. The gathering happens in the background, so the list is read again now and then. */
export function useRituals() {
  return useQuery<RitualList, Error>({
    queryKey: RITUALS_KEY,
    queryFn: fetchRituals,
    staleTime: 15_000,
    refetchInterval: POLLS ? 30_000 : false,
    retry: false,
  });
}

/** One ritual with what was gathered for it today. Starts from the list's copy, so the dialog never opens blank. */
export function useRitual(id: string, { enabled = true }: { enabled?: boolean } = {}) {
  const client = useQueryClient();
  return useQuery<RitualDetail, Error>({
    queryKey: ritualDetailKey(id),
    queryFn: () => fetchRitual(id),
    enabled: enabled && id !== "",
    staleTime: 15_000,
    // A gathering takes a minute or two; while one runs, its end is looked for more often.
    refetchInterval: POLLS
      ? (query) => (query.state.data?.today?.prep_state === "running" ? 5_000 : 30_000)
      : false,
    retry: false,
    placeholderData: () => {
      const listed = client.getQueryData<RitualList>(RITUALS_KEY)?.rituals.find((row) => row.id === id);
      if (!listed) return undefined;
      const { today, ...ritual } = listed;
      return { ritual, today: today ? { ...today, spoken: "", written: "" } : null };
    },
  });
}

// ----------------------------------------------------------------------
// Writes
// ----------------------------------------------------------------------

/**
 * Reads the list again, and the one ritual when it is named. A write waits
 * for this, so whoever asked for it sees the new state the moment it is done.
 */
function readAgain(client: QueryClient, id?: string): Promise<unknown> {
  return Promise.all([
    client.invalidateQueries({ queryKey: RITUALS_KEY, exact: true }),
    id ? client.invalidateQueries({ queryKey: ritualDetailKey(id), exact: true }) : undefined,
  ]);
}

export function useCreateRitual() {
  const client = useQueryClient();
  return useMutation<RitualView, Error, RitualDraft>({
    mutationFn: createRitual,
    onSettled: () => readAgain(client),
  });
}

export function useUpdateRitual() {
  const client = useQueryClient();
  return useMutation<RitualView, Error, { id: string; patch: RitualPatch }>({
    mutationFn: ({ id, patch }) => patchRitual(id, patch),
    onSettled: (_view, _error, { id }) => readAgain(client, id),
  });
}

export function useRemoveRitual() {
  const client = useQueryClient();
  return useMutation<{ ok: boolean; id: string }, Error, string>({
    mutationFn: deleteRitual,
    // Only the list: a ritual that is gone has nothing left to read.
    onSettled: () => readAgain(client),
  });
}

export function useRunRitual() {
  const client = useQueryClient();
  return useMutation<RitualRun, Error, string>({
    mutationFn: runRitual,
    onSettled: (_run, _error, id) => readAgain(client, id),
  });
}

export function usePrepareRitual() {
  const client = useQueryClient();
  return useMutation<RitualPrepare, Error, string>({
    mutationFn: prepareRitual,
    onSettled: (_prepared, _error, id) => readAgain(client, id),
  });
}
