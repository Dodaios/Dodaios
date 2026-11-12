/**
 * Test helpers for the standing tasks: a task builder and a small stand-in
 * for `/api/agent-chat/lead/standing` that keeps state the way the backend
 * does (accept makes a task active, decline and end take it off the list).
 * Imported by tests only.
 */
import { vi } from "vitest";

import type { StandingList, StandingRun, StandingState, StandingTask } from "@/lib/standingTasksApi";

export const STANDING_URL = "/api/agent-chat/lead/standing";
export const STANDING_LIMITS = { min_interval_min: 15, max_interval_min: 10080, default_interval_min: 180, max_open: 12 };

export function standingTask(id: string, more: Partial<StandingTask> = {}): StandingTask {
  return {
    id, title: id, goal: `Goal of ${id}`, how: "", autonomy: "prepare", limits: "", state: "active", interval_min: 180,
    origin: "owner", reason: "", notes: "", task_id: `t-${id}`, created_ms: 1_000, updated_ms: 2_000,
    last_run_ms: null, next_run_ms: null, last_outcome: "", last_summary: "", runs: 0, ...more,
  };
}

export function standingRun(id: string, standingId: string, more: Partial<StandingRun> = {}): StandingRun {
  return { id, standing_id: standingId, at_ms: Date.now(), outcome: "quiet", summary: "", actions: [], next_interval_min: 180, session_id: "", ...more };
}

export interface StandingCall {
  method: string;
  path: string;
  body: Record<string, unknown> | undefined;
}

const AFTER: Record<string, StandingState> = { accept: "active", resume: "active", pause: "paused", decline: "ended", end: "ended" };

/**
 * Stubs `fetch` with a stateful standing-tasks backend. `refuse` makes one
 * write fail with a readable message, keyed as "POST /s1/accept".
 */
export function standingBackend(
  initial: StandingTask[],
  options: {
    overview?: Partial<StandingList>;
    runs?: Record<string, StandingRun[]>;
    refuse?: Record<string, { status: number; detail: string }>;
    /** The list itself fails with this status. */
    listStatus?: number;
  } = {},
) {
  let tasks = initial.map((task) => ({ ...task }));
  const calls: StandingCall[] = [];
  const reply = (status: number, payload: unknown) => new Response(JSON.stringify(payload), { status });

  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    if (!url.startsWith(STANDING_URL)) return reply(404, {});
    const method = init?.method ?? "GET";
    const path = url.slice(STANDING_URL.length).split("?")[0];
    const body = init?.body ? (JSON.parse(String(init.body)) as Record<string, unknown>) : undefined;
    calls.push({ method, path, body });
    const refused = options.refuse?.[`${method} ${path}`];
    if (refused) return reply(refused.status, { detail: refused.detail });

    if (path === "" && method === "GET") {
      if (options.listStatus) return reply(options.listStatus, { detail: "The list is not there." });
      return reply(200, {
        available: true,
        tasks: tasks.filter((task) => task.state !== "ended"),
        limits: STANDING_LIMITS,
        autonomy: ["watch", "prepare", "act"],
        ...options.overview,
      });
    }
    if (path === "" && method === "POST") {
      const created = standingTask("s-new", { ...(body as Partial<StandingTask>), state: "active" });
      tasks = [created, ...tasks];
      return reply(201, { task: created });
    }
    const [, id, verb] = path.split("/");
    const index = tasks.findIndex((task) => task.id === id);
    if (index < 0) return reply(404, { detail: "No such standing task" });
    if (!verb && method === "GET") return reply(200, { task: tasks[index], runs: options.runs?.[id] ?? [] });
    if (!verb && method === "PATCH") {
      tasks[index] = { ...tasks[index], ...(body as Partial<StandingTask>) };
      return reply(200, { task: tasks[index] });
    }
    if (verb && method === "POST") {
      const state = AFTER[verb];
      if (state) tasks[index] = { ...tasks[index], state };
      return reply(200, { task: tasks[index] });
    }
    return reply(405, { detail: "Not allowed" });
  }));

  return {
    calls,
    /** Everything that changed something, as "POST /s1/accept". */
    writes: () => calls.filter((call) => call.method !== "GET").map((call) => `${call.method} ${call.path}`),
    bodyOf: (key: string) => calls.find((call) => `${call.method} ${call.path}` === key)?.body,
  };
}
