/**
 * Test helpers for the rituals: a ritual builder, a day builder and a small
 * stand-in for `/api/agent-chat/lead/rituals` that keeps state the way the
 * backend does (a write changes the ritual, a delete takes it off the list,
 * a run marks the day, a gathering marks it as under way).
 * Imported by tests only.
 */
import { vi } from "vitest";

import type { ListedRitual, Ritual, RitualDraft, RitualLimits, RitualStep, RitualTodayText } from "@/lib/ritualsApi";

export const RITUALS_URL = "/api/agent-chat/lead/rituals";
export const RITUAL_LIMITS: RitualLimits = {
  max_rituals: 20, max_name_chars: 60, max_phrases: 5, max_phrase_words: 6, max_phrase_chars: 60,
  max_steps: 12, max_step_chars: 500, when: ["now", "ahead"],
};

/** A ritual in the stand-in: its day may carry the text that was gathered. */
export type KitRitual = Ritual & { today: RitualTodayText | null };

export function ritualDay(more: Partial<RitualTodayText> = {}): RitualTodayText {
  return {
    day: "2026-11-15", prep_state: "", prep_error: "", prepared_ms: null, fired_ms: null, fired_via: "", results: [],
    delivered_ms: null, phrase_ms: null, spoken: "", written: "", ...more,
  };
}

export function ritual(id: string, more: Partial<KitRitual> = {}): KitRitual {
  return {
    id, name: id, phrases: [`Start ${id}`], enabled: true, window_from: "", window_to: "", weekdays: [], once_per_day: true,
    prepare_from: "", steps: [{ id: `${id}-s1`, when: "now", text: "Open my calendar" }], task_id: "", origin: "owner",
    created_ms: 1_000, updated_ms: 2_000, today: null, ...more,
  };
}

/** A moment today on this computer's clock, in ms. */
export function todayAt(hours: number, minutes: number): number {
  const at = new Date();
  at.setHours(hours, minutes, 0, 0);
  return at.getTime();
}

export interface RitualCall {
  method: string;
  path: string;
  body: Record<string, unknown> | undefined;
}

/** A ritual the way the list carries it: its day without the gathered text. */
function listed({ today, ...rest }: KitRitual): ListedRitual {
  if (!today) return { ...rest, today: null };
  const { spoken: _spoken, written: _written, ...day } = today;
  return { ...rest, today: day };
}

/**
 * Stubs `fetch` with a stateful rituals backend. `refuse` makes one request
 * fail with a readable sentence, keyed as "PATCH /rit_1".
 */
export function ritualsBackend(
  initial: KitRitual[],
  options: {
    limits?: Partial<RitualLimits>;
    refuse?: Record<string, { status: number; detail: string }>;
  } = {},
) {
  let rituals = initial.map((row) => ({ ...row }));
  let created = 0;
  const calls: RitualCall[] = [];
  const reply = (status: number, payload: unknown) => new Response(JSON.stringify(payload), { status });
  const view = ({ today, ...rest }: KitRitual, withText = false) =>
    ({ ritual: rest, today: withText ? today : listed({ ...rest, today }).today });
  /** Steps as the server stores them: a step that came without an id gets one, a tool call that came along stays. */
  const stepsOf = (id: string, steps: RitualDraft["steps"]): RitualStep[] =>
    steps.map((step, index) => ({
      id: step.id || `${id}-n${index + 1}`, when: step.when, text: step.text, ...(step.call ? { call: step.call } : {}),
    }));

  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (!url.startsWith(RITUALS_URL)) return reply(404, {});
    const method = init?.method ?? "GET";
    const path = url.slice(RITUALS_URL.length).split("?")[0];
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
    calls.push({ method, path, body });
    const refused = options.refuse?.[`${method} ${path}`];
    if (refused) return reply(refused.status, { detail: refused.detail });

    if (path === "" && method === "GET") {
      return reply(200, { available: true, rituals: rituals.map(listed), limits: { ...RITUAL_LIMITS, ...options.limits } });
    }
    if (path === "" && method === "POST") {
      created += 1;
      const id = `rit_new${created}`;
      const draft = body as unknown as RitualDraft;
      const row = ritual(id, { ...draft, steps: stepsOf(id, draft.steps) });
      rituals = [...rituals, row];
      return reply(201, view(row));
    }
    const [, id, verb] = path.split("/");
    const index = rituals.findIndex((row) => row.id === id);
    if (index < 0) return reply(404, { detail: "No such ritual" });
    const row = rituals[index];
    if (!verb && method === "GET") return reply(200, view(row, true));
    if (!verb && method === "PATCH") {
      const patch = body as unknown as Partial<RitualDraft>;
      rituals[index] = { ...row, ...patch, steps: patch.steps ? stepsOf(id, patch.steps) : row.steps };
      return reply(200, view(rituals[index]));
    }
    if (!verb && method === "DELETE") {
      rituals = rituals.filter((other) => other.id !== id);
      return reply(200, { ok: true, id });
    }
    if (verb === "run" && method === "POST") {
      rituals[index] = { ...row, today: { ...(row.today ?? ritualDay()), fired_ms: Date.now(), fired_via: "button" } };
      return reply(200, { ...view(rituals[index]), pending: false });
    }
    if (verb === "prepare" && method === "POST") {
      rituals[index] = { ...row, today: { ...(row.today ?? ritualDay()), prep_state: "running", prep_error: "" } };
      return reply(200, { started: true, ...view(rituals[index]) });
    }
    return reply(405, { detail: "Not allowed" });
  }));

  return {
    calls,
    /** Everything that changed something, as "PATCH /rit_1". */
    writes: () => calls.filter((call) => call.method !== "GET").map((call) => `${call.method} ${call.path}`),
    bodyOf: (key: string) => calls.find((call) => `${call.method} ${call.path}` === key)?.body,
  };
}
